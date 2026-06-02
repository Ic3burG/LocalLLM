"""Entry point for the `localllm` command."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from localllm import __version__
from localllm.agent_client import AgentClient
from localllm.config import load as load_config


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
            f"Start it with: launchctl kickstart -k gui/$UID/com.gemini.litert",
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

    app = LocalLLMApp(
        bridge_url=args.bridge_url, model_id=args.model, model_ready=ready
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
