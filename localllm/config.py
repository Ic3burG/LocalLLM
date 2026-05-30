"""Reads ~/.localllm/config.toml. Falls back to sensible defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# tomllib is stdlib on 3.11+; fall back to the tomli backport on 3.10 so the
# CI matrix (Python 3.10) still works.
try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover  -- exercised on 3.10 only
    import tomli as tomllib  # type: ignore[import-not-found, no-redef]

CONFIG_DIR = Path.home() / ".localllm"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_BRIDGE_URL = "http://127.0.0.1:9379"
DEFAULT_MODEL = "gemma4-e4b"


@dataclass
class Config:
    bridge_url: str = DEFAULT_BRIDGE_URL
    model: str = DEFAULT_MODEL


def ensure_dir() -> None:
    CONFIG_DIR.mkdir(mode=0o700, exist_ok=True, parents=True)


def load() -> Config:
    ensure_dir()
    if not CONFIG_FILE.exists():
        return Config()
    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)
    return Config(
        bridge_url=data.get("bridge_url", DEFAULT_BRIDGE_URL),
        model=data.get("model", DEFAULT_MODEL),
    )
