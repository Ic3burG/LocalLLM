"""Helpers for inline source citations across agent tools and RAG.

A Source is a plain dict with this shape (we use TypedDict for static help
but the runtime values are ordinary dicts so they serialise cleanly to JSON):

    {
        "idx":     int,
        "kind":    "web" | "file" | "rag",
        "title":   str,
        "url":     str | None,
        "domain":  str | None,
        "snippet": str,
        "meta":    dict,
    }
"""

from __future__ import annotations

from typing import TypedDict


class Source(TypedDict, total=False):
    idx: int
    kind: str
    title: str
    url: str | None
    domain: str | None
    snippet: str
    meta: dict


SNIPPET_CAP = 200


def trim_snippet(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= SNIPPET_CAP:
        return text
    return text[: SNIPPET_CAP - 1].rstrip() + "…"


def assign_indices(sources: list[dict], existing_count: int) -> list[dict]:
    """Return a new list of Sources with 1-indexed `idx` continuing
    from `existing_count`. The input dicts are not mutated."""
    return [{**s, "idx": existing_count + i + 1} for i, s in enumerate(sources)]


def dedupe_by_url(sources: list[dict]) -> list[dict]:
    """Remove later web sources whose URL already appeared. file/rag
    kinds are left alone because they have no canonical URL."""
    seen: set[str] = set()
    out: list[dict] = []
    for s in sources:
        url = s.get("url")
        if s.get("kind") == "web" and url:
            if url in seen:
                continue
            seen.add(url)
        out.append(s)
    return out


def format_sources_for_model(sources: list[dict]) -> str:
    """Render the per-call sources block that gets fed to the model
    as the TOOL_RESULT (or prefixed to it)."""
    lines: list[str] = []
    for s in sources:
        idx = s["idx"]
        title = s.get("title", "Untitled")
        domain = s.get("domain")
        header = f"[{idx}] {title}" + (f" ({domain})" if domain else "")
        lines.append(header)
        snippet = s.get("snippet")
        if snippet:
            for snip_line in snippet.splitlines():
                lines.append(f"    {snip_line}")
        lines.append("")
    return "\n".join(lines).rstrip()
