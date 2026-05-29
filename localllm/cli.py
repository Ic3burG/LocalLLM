"""Entry point for the `localllm` command."""

from __future__ import annotations

import argparse
import sys

from localllm import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localllm", description="LocalLLM CLI")
    parser.add_argument(
        "--version", action="version", version=f"localllm {__version__}"
    )
    parser.parse_args(argv)
    print("localllm CLI scaffold — not yet implemented", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
