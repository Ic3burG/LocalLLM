"""Pure @-mention expansion: turn `@path` into an inlined <file> block."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 100_000  # 100 KB per @-mention

# @ at start-of-string or after whitespace, then a run of non-space chars.
# The lookbehind keeps emails like a@b.com from matching.
_MENTION_RE = re.compile(r"(?:(?<=\s)|^)@(\S+)")
_TRAILING = ".,;:!?)]}"  # punctuation stripped before resolving a path


@dataclass
class Expansion:
    text: str  # prompt for the bridge: original line + appended <file> blocks
    attached: list[tuple[str, int]] = field(default_factory=list)  # (rel, bytes)
    warnings: list[str] = field(default_factory=list)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def expand_mentions(
    text: str, cwd: str | Path, *, max_bytes: int = MAX_FILE_BYTES
) -> Expansion:
    cwd_resolved = Path(os.path.expanduser(str(cwd))).resolve()
    exp = Expansion(text=text)
    blocks: list[str] = []
    seen: set[str] = set()

    for match in _MENTION_RE.finditer(text):
        rel = match.group(1).rstrip(_TRAILING)
        if not rel or rel in seen:
            continue
        seen.add(rel)

        candidate = Path(os.path.expanduser(rel))
        target = (
            candidate.resolve()
            if candidate.is_absolute()
            else (cwd_resolved / candidate).resolve()
        )
        try:
            target.relative_to(cwd_resolved)
        except ValueError:
            exp.warnings.append(f"skipped @{rel} (outside the session directory)")
            continue
        if not target.is_file():
            exp.warnings.append(f"skipped @{rel} (not found)")
            continue
        try:
            data = target.read_bytes()
        except OSError as e:
            exp.warnings.append(f"skipped @{rel} ({e.__class__.__name__})")
            continue
        if b"\x00" in data[:8192]:
            exp.warnings.append(f"skipped @{rel} (binary file)")
            continue

        truncated = len(data) > max_bytes
        sent = data[:max_bytes]
        content = sent.decode("utf-8", errors="replace")
        if truncated:
            dropped = len(data) - max_bytes
            content += f"\n[truncated {dropped} bytes]"
            exp.warnings.append(
                f"truncated @{rel} to {human_size(max_bytes)} "
                f"({human_size(dropped)} dropped)"
            )
        blocks.append(f'<file path="{rel}">\n{content}\n</file>')
        exp.attached.append((rel, len(sent)))

    if blocks:
        exp.text = text + "\n\n" + "\n\n".join(blocks)
    return exp
