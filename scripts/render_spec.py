#!/usr/bin/env python3
"""Render a Markdown design spec to docs/superpowers/specs/spec_preview.html.

Dependency-free (stdlib only). Handles the Markdown subset our specs use:
ATX headings, bold, inline code, fenced code blocks, ordered/unordered lists
(with indentation-based nesting), blockquotes, horizontal rules, and links.

Usage:
    python scripts/render_spec.py docs/superpowers/specs/<spec>.md
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

STYLE = """\
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 15px; line-height: 1.65; color: #1a1a2e;
      background: #f4f6fb; padding: 40px 20px 80px;
    }
    .container {
      max-width: 860px; margin: 0 auto; background: #fff; border-radius: 12px;
      box-shadow: 0 2px 20px rgba(0, 0, 0, 0.08); padding: 48px 56px;
    }
    h1 { font-size: 2rem; font-weight: 700; margin-bottom: 8px; color: #0f172a; }
    h2 {
      font-size: 1.25rem; font-weight: 600; margin: 36px 0 12px; color: #1e3a5f;
      border-bottom: 2px solid #e2e8f0; padding-bottom: 6px;
    }
    h3 { font-size: 1.05rem; font-weight: 600; margin: 24px 0 8px; color: #334155; }
    h4 { font-size: 0.95rem; font-weight: 600; margin: 18px 0 6px; color: #475569; }
    p { margin: 10px 0; color: #374151; }
    a { color: #2563eb; }
    code {
      font-family: "SF Mono", "Fira Code", monospace; font-size: 0.85em;
      background: #f1f5f9; padding: 2px 6px; border-radius: 4px; color: #0f5132;
    }
    pre {
      background: #0f172a; color: #e2e8f0; padding: 20px 24px; border-radius: 8px;
      overflow-x: auto; margin: 16px 0; font-size: 0.88em; line-height: 1.6;
    }
    pre code { background: none; color: inherit; padding: 0; }
    ul, ol { padding-left: 24px; margin: 10px 0; color: #374151; }
    li { margin: 4px 0; }
    blockquote {
      border-left: 4px solid #3b82f6; margin: 16px 0; padding: 8px 16px;
      background: #eff6ff; color: #1e3a5f; border-radius: 0 6px 6px 0;
    }
    strong { color: #0f172a; }
    hr { border: none; border-top: 1px solid #e2e8f0; margin: 32px 0; }
"""


def _inline(text: str) -> str:
    """Escape HTML then apply inline Markdown (code, bold, links)."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def render(md: str) -> str:
    lines = md.split("\n")
    parts: list[str] = []
    list_stack: list[tuple[int, str]] = []  # (indent, "ul"|"ol")
    i = 0

    def close_lists(to_indent: int = -1) -> None:
        while list_stack and list_stack[-1][0] > to_indent:
            parts.append(f"</{list_stack.pop()[1]}>")

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.lstrip().startswith("```"):
            close_lists()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1  # consume closing fence
            parts.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            continue

        stripped = line.strip()

        if not stripped:
            close_lists()
            i += 1
            continue

        # Horizontal rule
        if re.fullmatch(r"-{3,}", stripped):
            close_lists()
            parts.append("<hr />")
            i += 1
            continue

        # Headings
        m = re.match(r"(#{1,6})\s+(.*)", stripped)
        if m:
            close_lists()
            level = len(m.group(1))
            parts.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            close_lists()
            parts.append(f"<blockquote>{_inline(stripped[1:].strip())}</blockquote>")
            i += 1
            continue

        # List items (indentation-based nesting)
        indent = len(line) - len(line.lstrip(" "))
        ul = re.match(r"[-*]\s+(.*)", stripped)
        ol = re.match(r"\d+\.\s+(.*)", stripped)
        if ul or ol:
            kind = "ul" if ul else "ol"
            content = (ul or ol).group(1)
            if not list_stack or indent > list_stack[-1][0]:
                parts.append(f"<{kind}>")
                list_stack.append((indent, kind))
            else:
                close_lists(indent)
                if not list_stack or list_stack[-1][0] < indent:
                    parts.append(f"<{kind}>")
                    list_stack.append((indent, kind))
            parts.append(f"<li>{_inline(content)}</li>")
            i += 1
            continue

        # Paragraph (gather consecutive non-blank, non-special lines)
        close_lists()
        buf = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or re.match(r"(#{1,6}\s|[-*]\s|\d+\.\s|>|```|-{3,})", nxt):
                break
            buf.append(nxt)
            i += 1
        parts.append("<p>" + _inline(" ".join(buf)) + "</p>")

    close_lists()
    return "\n      ".join(parts)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/render_spec.py <spec.md>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"not found: {src}", file=sys.stderr)
        return 1

    md = src.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.*)", md, re.MULTILINE)
    title = title_match.group(1) if title_match else src.stem
    body = render(md)

    doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{html.escape(title)}</title>
    <style>
{STYLE}    </style>
  </head>
  <body>
    <div class="container">
      {body}
    </div>
  </body>
</html>
"""
    # Match the established per-directory preview filename convention.
    preview_name = (
        "plan_preview.html" if src.parent.name == "plans" else "spec_preview.html"
    )
    out = src.parent / preview_name
    out.write_text(doc, encoding="utf-8")

    # Keep the generated file prettier-clean (repo mandate). Best-effort.
    # Run from the repo root (nearest ancestor with .prettierrc) so prettier
    # picks up the project config exactly as CI does.
    if shutil.which("npx"):
        root = next(
            (p for p in out.resolve().parents if (p / ".prettierrc").exists()),
            out.resolve().parent,
        )
        subprocess.run(
            ["npx", "prettier", "--write", str(out.resolve())],
            cwd=root,
            capture_output=True,
        )

    print(f"rendered {src.name} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
