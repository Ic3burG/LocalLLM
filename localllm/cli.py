"""Entry point for the `localllm` command."""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from localllm import __version__
from localllm.agent_client import AgentClient
from localllm.config import load as load_config

LOG_PATH = Path.home() / ".localllm" / "cli.log"


def _setup_logging() -> Path:
    """Attach a rotating file handler to the `localllm` logger so TUI errors are
    captured to ~/.localllm/cli.log (the TUI owns the terminal, so stderr is not
    usable). Honors LOCALLLM_LOG_LEVEL (default INFO)."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = os.environ.get("LOCALLLM_LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger("localllm")
    logger.setLevel(level)
    # Idempotent: don't stack handlers if main() is called more than once.
    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers
    ):
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    return LOG_PATH


async def _bridge_is_up(base_url: str) -> bool:
    return await AgentClient(base_url=base_url).health()


async def _bridge_health_detail(base_url: str, model_id: str) -> dict | None:
    # Retry across a freshly-(re)started bridge's bind window: a connection
    # refused while uvicorn is still binding the port returns immediately, so a
    # bigger timeout alone wouldn't help — we briefly retry instead. ~3.5s total.
    client = AgentClient(base_url=base_url)
    try:
        for delay in (0.0, 0.5, 1.0, 2.0):
            if delay:
                await asyncio.sleep(delay)
            detail = await client.health_detail(model_id)
            if detail is not None:
                return detail
        return None
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="localllm", description="LocalLLM CLI")
    parser.add_argument(
        "--version", action="version", version=f"localllm {__version__}"
    )
    parser.add_argument(
        "--bridge-url",
        default=os.environ.get("LOCALLLM_BRIDGE_URL", cfg.bridge_url),
        help="Bridge base URL (default: from ~/.localllm/config.toml or http://127.0.0.1:9379)",
    )
    parser.add_argument(
        "--model",
        default=cfg.model,
        help=f"Model id (default: {cfg.model})",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Probe bridge health and exit (no TUI launch). For tests and CI.",
    )
    args = parser.parse_args(argv)

    if not sys.stdout.isatty() and not args.no_tui:
        print("localllm requires a TTY (no rich-TUI fallback in v1).", file=sys.stderr)
        return 3

    detail = asyncio.run(_bridge_health_detail(args.bridge_url, args.model))
    if detail is None:
        print(
            f"Bridge unreachable at {args.bridge_url}.\n"
            f"Start it with: launchctl kickstart -k gui/$UID/com.localllm.bridge",
            file=sys.stderr,
        )
        return 2

    ready = detail.get("ready", False)

    # --no-tui is a diagnostic probe: report exact readiness and exit. The
    # interactive TUI does NOT need a preloaded model — it loads lazily on the
    # first prompt — so reachability (detail is not None) is enough to launch.
    if args.no_tui:
        if not ready:
            print(
                f"Bridge is up at {args.bridge_url} but model {args.model!r} is not loaded yet.\n"
                f"This usually means the bridge just started; the model loads on first use.\n"
                f"Either wait a few seconds and re-run, or send a chat request via the web UI to warm it.",
                file=sys.stderr,
            )
            return 4
        print(f"Bridge OK at {args.bridge_url} (model {args.model} ready)")
        return 0

    # Import here so tests can run without Textual installed/initialized
    from localllm.app import LocalLLMApp

    log_path = _setup_logging()
    logging.getLogger("localllm").info(
        "starting TUI: version=%s bridge=%s model=%s ready=%s",
        __version__,
        args.bridge_url,
        args.model,
        ready,
    )
    print(f"localllm {__version__} — logging to {log_path}")

    app = LocalLLMApp(
        bridge_url=args.bridge_url, model_id=args.model, model_ready=ready
    )
    try:
        app.run()
    except Exception:
        logging.getLogger("localllm").exception("fatal: TUI crashed")
        print(f"localllm crashed — see {log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
