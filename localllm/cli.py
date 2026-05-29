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

    up = asyncio.run(_bridge_is_up(args.bridge_url))
    if not up:
        print(
            f"Bridge unreachable at {args.bridge_url}.\n"
            f"Start it with: launchctl kickstart -k gui/$UID/com.gemini.litert",
            file=sys.stderr,
        )
        return 2

    if args.no_tui:
        print(f"Bridge OK at {args.bridge_url}")
        return 0

    # Import here so tests can run without Textual installed/initialized
    from localllm.app import LocalLLMApp

    app = LocalLLMApp(bridge_url=args.bridge_url, model_id=args.model)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
