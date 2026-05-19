# Source Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline citation chips to assistant messages so users can hover for a source preview and click to open the source URL (or PDF chunk modal for RAG).

**Architecture:** A new `citations.py` module defines the `Source` shape and helpers. `_google_search` and `_web_fetch` return citation-aware results; `react_loop_sse` accumulates them per run, assigns global indices, emits a new `{"type": "sources"}` SSE event, and rewrites tool results with `[N]` prefixes. RAG injects numbered chunks into the system prompt and emits the same sources event before the ReAct loop starts. The frontend parses `[N]` markers in rendered HTML, replacing them with `<button class="citation-chip">` elements that show a hover popover and either open a URL or a RAG modal on click. Sources persist on the message object in `localStorage`.

**Tech Stack:** Python 3 / FastAPI / asyncio / pytest on backend; vanilla JS + `marked` for markdown + Tailwind CSS classes on frontend; SSE for streaming.

**Spec:** `docs/superpowers/specs/2026-05-19-source-citations-design.md`

**User decisions locked in for this plan:**

- Work directly on `main` (no feature branch).
- Push only after the full feature is implemented and `bash .git/hooks/pre-push` is green.
- Ship the whole feature in a single bundled set of commits (one task = one commit).

---

## File Map

| File                         | Role                                                                                                                                                            | Status         |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| `citations.py`               | Source dataclass, dedupe helper, index assignment, snippet trimming, model-text formatter                                                                       | **New**        |
| `agent_utils.py`             | `_google_search` / `_web_fetch` return citation-aware dict; AGENT_SYSTEM_PROMPT gains CITATIONS block                                                           | Modify         |
| `agent.py`                   | `react_loop_sse` consumes citation-aware results, emits sources SSE event, threads index assignment                                                             | Modify         |
| `pdf_pipeline.py`            | New `build_numbered_document_context()` alongside existing `build_document_context` (legacy kept until callers move)                                            | Modify         |
| `gemma_bridge.py`            | `/v1/chat/stream` handler emits a sources event into the SSE queue when RAG chunks are present; uses numbered context builder                                   | Modify         |
| `gemma-web/server.js`        | No code change required — `/api/chat/stream/:taskId` already proxies all event types verbatim.                                                                  | Verify only    |
| `gemma-web/index.html`       | New chip + popover CSS, `renderCitations()` post-processor, hover/focus/click handlers, RAG modal, fallback footer, `sources` field added to persisted messages | Modify         |
| `tests/test_citations.py`    | Unit tests for `citations.py` helpers                                                                                                                           | **New**        |
| `tests/test_agent.py`        | New cases: structured tool returns, global indexing across calls, sources SSE emission, CITATIONS block in prompt                                               | Modify         |
| `tests/test_pdf_pipeline.py` | New cases: `build_numbered_document_context` format                                                                                                             | New if missing |

---

## Task 1: Source helpers module + tests

**Files:**

- Create: `citations.py`
- Create: `tests/test_citations.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_citations.py`:

```python
from citations import (
    Source,
    assign_indices,
    dedupe_by_url,
    format_sources_for_model,
    trim_snippet,
)


def test_trim_snippet_caps_to_200_chars():
    long = "x" * 400
    out = trim_snippet(long)
    assert len(out) <= 200
    assert out.endswith("…")


def test_trim_snippet_passes_short_strings_through():
    assert trim_snippet("hello") == "hello"


def test_trim_snippet_handles_none():
    assert trim_snippet(None) == ""


def test_assign_indices_starts_from_one_on_empty_run():
    new = [{"kind": "web", "title": "a", "url": "https://a.com"}]
    out = assign_indices(new, existing_count=0)
    assert out[0]["idx"] == 1


def test_assign_indices_continues_from_existing_count():
    new = [
        {"kind": "web", "title": "a", "url": "https://a.com"},
        {"kind": "web", "title": "b", "url": "https://b.com"},
    ]
    out = assign_indices(new, existing_count=3)
    assert [s["idx"] for s in out] == [4, 5]


def test_dedupe_by_url_keeps_lower_index():
    sources = [
        {"idx": 1, "kind": "web", "title": "a", "url": "https://x.com"},
        {"idx": 2, "kind": "web", "title": "a2", "url": "https://x.com"},
        {"idx": 3, "kind": "web", "title": "b", "url": "https://y.com"},
    ]
    out = dedupe_by_url(sources)
    urls = [s["url"] for s in out]
    assert urls == ["https://x.com", "https://y.com"]
    assert out[0]["idx"] == 1


def test_dedupe_by_url_leaves_file_and_rag_alone():
    sources = [
        {"idx": 1, "kind": "file", "title": "a.txt", "url": None},
        {"idx": 2, "kind": "file", "title": "a.txt", "url": None},
        {"idx": 3, "kind": "rag", "title": "doc.pdf", "url": None},
    ]
    out = dedupe_by_url(sources)
    assert len(out) == 3


def test_format_sources_for_model_renders_indexed_block():
    sources = [
        {
            "idx": 1,
            "kind": "web",
            "title": "ESPN — NBA Scores",
            "url": "https://espn.com/nba",
            "domain": "espn.com",
            "snippet": "Lakers 112, Celtics 108.",
        },
        {
            "idx": 2,
            "kind": "web",
            "title": "NBA.com Recap",
            "url": "https://nba.com/recap",
            "domain": "nba.com",
            "snippet": "LeBron scored 35.",
        },
    ]
    out = format_sources_for_model(sources)
    assert "[1] ESPN — NBA Scores (espn.com)" in out
    assert "Lakers 112, Celtics 108." in out
    assert "[2] NBA.com Recap (nba.com)" in out


def test_format_sources_for_model_handles_file_kind_without_domain():
    sources = [
        {
            "idx": 1,
            "kind": "file",
            "title": "src/app.py",
            "url": None,
            "domain": None,
            "snippet": "def main():",
        }
    ]
    out = format_sources_for_model(sources)
    assert "[1] src/app.py" in out
    assert "def main():" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_citations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'citations'`

- [ ] **Step 3: Implement `citations.py`**

Create `citations.py`:

```python
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
    """Mutates the dicts in `sources` to add a 1-indexed `idx` that
    continues from `existing_count`. Returns the same list for chaining."""
    for i, s in enumerate(sources):
        s["idx"] = existing_count + i + 1
    return sources


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_citations.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add citations.py tests/test_citations.py
git commit -m "feat(citations): add Source helpers (trim, dedupe, format, index)"
```

---

## Task 2: Structured returns from `_google_search` and `_web_fetch`

**Files:**

- Modify: `agent_utils.py:289-303` (`_google_search`)
- Modify: `agent_utils.py:324-348` (`_web_fetch`)
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests for new return shape**

Append to `tests/test_agent.py`:

```python
import asyncio

import pytest

from agent_utils import _google_search, _web_fetch


@pytest.mark.asyncio
async def test_google_search_returns_dict_with_sources(monkeypatch):
    fake_results = [
        {"title": "ESPN — NBA Scores", "href": "https://espn.com/nba",
         "body": "Lakers 112, Celtics 108. Final score from last night's game."},
        {"title": "NBA.com Recap", "href": "https://www.nba.com/recap",
         "body": "LeBron scored 35 points."},
    ]

    class FakeDDGS:
        def text(self, query, max_results=5):
            return fake_results

    import sys
    import types
    fake_mod = types.ModuleType("ddgs")
    fake_mod.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_mod)

    out = await _google_search("nba scores")

    assert isinstance(out, dict)
    assert "sources" in out
    assert "model_text" in out
    assert len(out["sources"]) == 2
    s0 = out["sources"][0]
    assert s0["kind"] == "web"
    assert s0["title"] == "ESPN — NBA Scores"
    assert s0["url"] == "https://espn.com/nba"
    assert s0["domain"] == "espn.com"
    assert "Lakers 112" in s0["snippet"]
    assert s0.get("idx") in (None, 0)


@pytest.mark.asyncio
async def test_google_search_handles_empty_results(monkeypatch):
    class FakeDDGS:
        def text(self, q, max_results=5):
            return []
    import sys
    import types
    fake_mod = types.ModuleType("ddgs")
    fake_mod.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_mod)

    out = await _google_search("nothing matches")
    assert out == {"sources": [], "model_text": "No results found."}


@pytest.mark.asyncio
async def test_web_fetch_returns_dict_with_one_source(monkeypatch):
    html = (
        b"<html><head><title>ESPN NBA</title></head>"
        b"<body><p>Lakers won 112-108.</p></body></html>"
    )

    class FakeResp:
        status_code = 200
        text = html.decode()

        def raise_for_status(self):
            pass

    class FakeRequests:
        @staticmethod
        def get(url, timeout=10):
            return FakeResp()

    import sys
    monkeypatch.setitem(sys.modules, "requests", FakeRequests)

    out = await _web_fetch("https://espn.com/nba")
    assert isinstance(out, dict)
    assert len(out["sources"]) == 1
    s = out["sources"][0]
    assert s["kind"] == "web"
    assert s["url"] == "https://espn.com/nba"
    assert s["domain"] == "espn.com"
    assert "Lakers won" in out["model_text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent.py::test_google_search_returns_dict_with_sources tests/test_agent.py::test_google_search_handles_empty_results tests/test_agent.py::test_web_fetch_returns_dict_with_one_source -v`
Expected: FAIL — current implementations return strings, not dicts.

- [ ] **Step 3: Modify `_google_search` to return the new dict shape**

In `agent_utils.py`, replace the existing `_google_search` (lines 289–303) with:

```python
async def _google_search(query: str) -> dict:
    from urllib.parse import urlparse

    from citations import trim_snippet

    try:
        from ddgs import DDGS

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None, lambda: DDGS().text(query, max_results=5)
        )
        if not results:
            return {"sources": [], "model_text": "No results found."}

        sources = []
        for r in results:
            url = r.get("href") or ""
            domain = urlparse(url).hostname or None
            sources.append(
                {
                    "kind": "web",
                    "title": r.get("title", "Untitled"),
                    "url": url or None,
                    "domain": domain,
                    "snippet": trim_snippet(r.get("body")),
                    "meta": {},
                }
            )
        return {"sources": sources, "model_text": ""}
    except Exception as e:
        logger.error("google_search failed: %s", e, extra={"query": query})
        return {"sources": [], "model_text": f"ERROR: {e}"}
```

- [ ] **Step 4: Modify `_web_fetch` to return the new dict shape**

In `agent_utils.py`, replace the existing `_web_fetch` (lines 324–348) with:

```python
async def _web_fetch(url: str) -> dict:
    from urllib.parse import urlparse

    from citations import trim_snippet

    try:
        validate_url(url)
        import requests
        from bs4 import BeautifulSoup

        loop = asyncio.get_running_loop()

        def _sync_fetch():
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title_tag = soup.find("title")
            title = title_tag.get_text().strip() if title_tag else url
            for tag in soup(["script", "style"]):
                tag.decompose()
            lines = [
                line.strip()
                for line in soup.get_text(separator="\n").splitlines()
                if line.strip()
            ]
            body = "\n".join(lines)[:5000]
            return title, body

        title, body = await loop.run_in_executor(None, _sync_fetch)
        domain = urlparse(url).hostname or None
        source = {
            "kind": "web",
            "title": title,
            "url": url,
            "domain": domain,
            "snippet": trim_snippet(body),
            "meta": {},
        }
        return {"sources": [source], "model_text": body}
    except Exception as e:
        logger.error("web_fetch failed: %s", e, extra={"url": url})
        return {"sources": [], "model_text": f"ERROR: {e}"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_agent.py -k "google_search or web_fetch" -v`
Expected: new tests pass.

- [ ] **Step 6: Update any pre-existing assertions about string returns**

Search for legacy assumptions:

```bash
grep -n "google_search\|web_fetch" tests/test_agent.py
```

For any existing test that asserted on a string return from these two tools, update it to handle the new dict (e.g., `out["model_text"]` or `out["sources"]`).

Then re-run the full agent test file:

```bash
.venv/bin/python -m pytest tests/test_agent.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agent_utils.py tests/test_agent.py
git commit -m "feat(citations): structured returns from google_search and web_fetch"
```

---

## Task 3: Wire Sources accumulator + emit sources SSE event

**Files:**

- Modify: `agent.py:408-628` (`react_loop_sse`)
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests for the SSE behavior**

Append to `tests/test_agent.py`:

```python
@pytest.mark.asyncio
async def test_react_loop_emits_sources_event_for_tool_with_citations(monkeypatch):
    """When a tool returns {sources, model_text}, the loop should
    enqueue a `{type: 'sources', items: [...]}` event."""
    import json as _json
    import agent as agent_mod

    fake_dict_result = {
        "sources": [
            {"kind": "web", "title": "ESPN", "url": "https://espn.com",
             "domain": "espn.com", "snippet": "Lakers won.", "meta": {}}
        ],
        "model_text": "",
    }

    class FakeTool:
        risk = "safe"

        async def fn(self, *_args):
            return fake_dict_result

    monkeypatch.setitem(agent_mod.TOOL_REGISTRY, "google_search", FakeTool())

    replies = iter(
        ['TOOL: google_search("lakers")', 'DONE: Lakers won [1].']
    )

    async def fake_inference(messages, model_id):
        return next(replies)

    monkeypatch.setattr(agent_mod, "run_inference", fake_inference)
    monkeypatch.setattr(
        agent_mod, "summarize_history", lambda m: asyncio.sleep(0, result=m)
    )
    monkeypatch.setattr(agent_mod, "is_model_loaded", lambda mid: True)

    task_id = "test-task-citations"
    agent_mod.sse_queues[task_id] = asyncio.Queue()

    await agent_mod.react_loop_sse(
        task_id, [{"role": "user", "content": "lakers score"}], "gemma4-e4b"
    )

    events = []
    while True:
        item = agent_mod.sse_queues[task_id].get_nowait()
        if item is None:
            break
        events.append(_json.loads(item))

    sources_events = [e for e in events if e.get("type") == "sources"]
    assert len(sources_events) == 1
    items = sources_events[0]["items"]
    assert items[0]["idx"] == 1
    assert items[0]["url"] == "https://espn.com"


@pytest.mark.asyncio
async def test_react_loop_indexes_sources_globally_across_two_calls(monkeypatch):
    """Two google_search calls in one run should produce indices 1,2 then 3,4."""
    import json as _json
    import agent as agent_mod

    first_call = {
        "sources": [
            {"kind": "web", "title": "A", "url": "https://a.com",
             "domain": "a.com", "snippet": "x", "meta": {}},
            {"kind": "web", "title": "B", "url": "https://b.com",
             "domain": "b.com", "snippet": "y", "meta": {}},
        ],
        "model_text": "",
    }
    second_call = {
        "sources": [
            {"kind": "web", "title": "C", "url": "https://c.com",
             "domain": "c.com", "snippet": "z", "meta": {}},
            {"kind": "web", "title": "D", "url": "https://d.com",
             "domain": "d.com", "snippet": "w", "meta": {}},
        ],
        "model_text": "",
    }
    results = iter([first_call, second_call])

    class FakeTool:
        risk = "safe"

        async def fn(self, *_args):
            return next(results)

    monkeypatch.setitem(agent_mod.TOOL_REGISTRY, "google_search", FakeTool())

    replies = iter(
        [
            'TOOL: google_search("first")',
            'TOOL: google_search("second")',
            "DONE: ok",
        ]
    )

    async def fake_inference(messages, model_id):
        return next(replies)

    monkeypatch.setattr(agent_mod, "run_inference", fake_inference)
    monkeypatch.setattr(
        agent_mod, "summarize_history", lambda m: asyncio.sleep(0, result=m)
    )
    monkeypatch.setattr(agent_mod, "is_model_loaded", lambda mid: True)

    task_id = "test-task-global-idx"
    agent_mod.sse_queues[task_id] = asyncio.Queue()
    await agent_mod.react_loop_sse(
        task_id, [{"role": "user", "content": "x"}], "gemma4-e4b"
    )

    events = []
    while True:
        item = agent_mod.sse_queues[task_id].get_nowait()
        if item is None:
            break
        events.append(_json.loads(item))

    sources_events = [e for e in events if e.get("type") == "sources"]
    assert len(sources_events) == 2
    assert [s["idx"] for s in sources_events[0]["items"]] == [1, 2]
    assert [s["idx"] for s in sources_events[1]["items"]] == [3, 4]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent.py::test_react_loop_emits_sources_event_for_tool_with_citations tests/test_agent.py::test_react_loop_indexes_sources_globally_across_two_calls -v`
Expected: FAIL — no sources events emitted yet.

- [ ] **Step 3: Modify `react_loop_sse` to handle citation-aware tool results**

Open `agent.py`. Add an import near the top alongside the other module imports:

```python
from citations import (
    assign_indices,
    format_sources_for_model,
)
```

Inside `react_loop_sse` (function defined at `agent.py:408`), immediately after `q = sse_queues[task_id]` near line 418, add a per-run accumulator:

```python
    run_sources: list[dict] = []
```

Then in the section that handles a successful tool call (currently `agent.py:565-617`, the block starting with `telemetry.record_tool_use(name_or_msg)`), replace from that line through the `messages.append({"role": "user", ...})` line at the end of the tool-handling block with:

```python
            telemetry.record_tool_use(name_or_msg)
            t0 = time.monotonic()
            try:
                result = await tool.fn(*args)
            except Exception as e:
                logger.error(
                    "tool execution failed",
                    extra={"tool": name_or_msg, "error": str(e)},
                    exc_info=True,
                )
                result = f"ERROR: {e}"
            elapsed = int((time.monotonic() - t0) * 1000)

            # Citation-aware tool result?
            new_sources: list[dict] = []
            if isinstance(result, dict) and "sources" in result:
                new_sources = list(result.get("sources") or [])
                model_text = result.get("model_text", "")
                existing_urls = {
                    s["url"] for s in run_sources
                    if s.get("kind") == "web" and s.get("url")
                }
                new_sources = [
                    s for s in new_sources
                    if not (s.get("kind") == "web" and s.get("url") in existing_urls)
                ]
                assign_indices(new_sources, existing_count=len(run_sources))
                run_sources.extend(new_sources)

                if new_sources:
                    await q.put(
                        json.dumps({"type": "sources", "items": new_sources})
                    )

                header = format_sources_for_model(new_sources)
                if header and model_text:
                    formatted_result_for_model = f"{header}\n\n{model_text}"
                elif header:
                    formatted_result_for_model = header
                else:
                    formatted_result_for_model = model_text
                display_result = formatted_result_for_model
            else:
                formatted_result_for_model = result
                display_result = result

            await q.put(
                json.dumps(
                    {
                        "type": "step",
                        "tool": name_or_msg,
                        "args": dict(enumerate(args)),
                        "result": display_result,
                        "elapsed_ms": elapsed,
                    }
                )
            )

            model_tool_result = formatted_result_for_model
            if isinstance(formatted_result_for_model, str):
                # Image-tool special case: legacy path may still return a JSON
                # blob marked __image__. Preserve that behavior.
                try:
                    img_data = json.loads(formatted_result_for_model)
                    if not img_data.get("__image__"):
                        raise ValueError
                    await q.put(
                        json.dumps(
                            {
                                "type": "image",
                                "image_b64": img_data["image_b64"],
                                "width": img_data["width"],
                                "height": img_data["height"],
                                "steps": img_data["steps"],
                                "elapsed_ms": img_data["elapsed_ms"],
                                "prompt": img_data["prompt"],
                                "size": img_data.get("size", "512x512"),
                            }
                        )
                    )
                    model_tool_result = (
                        f"[IMAGE GENERATED: {img_data['width']}x{img_data['height']}, "
                        f"{img_data['steps']} steps — displayed in chat]"
                    )
                except Exception:
                    pass

            messages.append(
                {"role": "user", "content": f"TOOL_RESULT: {model_tool_result}"}
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_agent.py -v`
Expected: all pass, including the two new SSE tests.

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat(citations): emit sources SSE event and index globally per run"
```

---

## Task 4: Add CITATIONS block to AGENT_SYSTEM_PROMPT

**Files:**

- Modify: `agent_utils.py:960-1016` (`AGENT_SYSTEM_PROMPT`)
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write a failing test**

Append to `tests/test_agent.py`:

```python
def test_agent_system_prompt_contains_citations_block():
    from agent_utils import AGENT_SYSTEM_PROMPT

    assert "CITATIONS:" in AGENT_SYSTEM_PROMPT
    assert "[1]" in AGENT_SYSTEM_PROMPT
    assert "TOOL_RESULT" in AGENT_SYSTEM_PROMPT
    # The example must show inline citations to anchor the model's behavior.
    assert "[1]" in AGENT_SYSTEM_PROMPT.split("EXAMPLE")[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent.py::test_agent_system_prompt_contains_citations_block -v`
Expected: FAIL.

- [ ] **Step 3: Modify `AGENT_SYSTEM_PROMPT`**

In `agent_utils.py`:

1. Insert a new block immediately before the `EXAMPLE:` line (currently around line 1012):

```
CITATIONS:
- TOOL_RESULTs are numbered like [1], [2], [3]. These indices are stable
  across the whole conversation turn.
- When you state a fact from a tool result, append the matching index in
  square brackets at the end of the claim. Multiple sources: [1][3].
- Do NOT invent or renumber citations. Only cite indices that appeared
  in a TOOL_RESULT above.
- In your final DONE: answer, keep the [N] markers inline.

```

2. Replace the EXAMPLE block (currently lines 1012–1016) with:

```
EXAMPLE:
User: What's the score of last night's Lakers game?
TOOL: google_search("Lakers score last night")
TOOL_RESULT:
[1] ESPN — NBA Scores (espn.com)
    Lakers 112, Celtics 108. Final score from last night's game.
DONE: The Lakers beat the Celtics 112–108 last night [1].
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_agent.py::test_agent_system_prompt_contains_citations_block -v
.venv/bin/python -m pytest tests/test_agent.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent_utils.py tests/test_agent.py
git commit -m "feat(citations): teach agent to emit [N] markers"
```

---

## Task 5: RAG numbered chunks + sources emission in chat-stream

**Files:**

- Modify: `pdf_pipeline.py` (add new function alongside existing)
- Modify: `gemma_bridge.py` (`/v1/chat/stream` handler, lines 588–613)
- Create or modify: `tests/test_pdf_pipeline.py`

- [ ] **Step 1: Write failing tests for the numbered context builder**

Create `tests/test_pdf_pipeline.py` (or append if it already exists):

```python
from pdf_pipeline import build_numbered_document_context, chunks_to_sources


def _fake_chunks():
    return [
        {"filename": "annual_report.pdf", "pages": [4],
         "text": "Q3 revenue grew 18% year-over-year.", "score": 0.91},
        {"filename": "annual_report.pdf", "pages": [7, 8],
         "text": "Operating margin expanded to 22.3%.", "score": 0.83},
    ]


def test_build_numbered_document_context_format():
    ctx = build_numbered_document_context(_fake_chunks())
    assert "[1] (annual_report.pdf, p.4):" in ctx
    assert "Q3 revenue grew 18% year-over-year." in ctx
    assert "[2] (annual_report.pdf, p.7, p.8):" in ctx
    assert "RELEVANT EXCERPTS" in ctx


def test_chunks_to_sources_yields_rag_records():
    sources = chunks_to_sources(_fake_chunks())
    assert len(sources) == 2
    s0 = sources[0]
    assert s0["kind"] == "rag"
    assert s0["title"] == "annual_report.pdf"
    assert s0["meta"]["page"] == 4
    assert "Q3 revenue" in s0["snippet"]
    assert s0["url"] is None


def test_build_numbered_document_context_empty():
    assert build_numbered_document_context([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pdf_pipeline.py -v`
Expected: FAIL — functions don't exist.

- [ ] **Step 3: Add `build_numbered_document_context` and `chunks_to_sources` to `pdf_pipeline.py`**

Append to `pdf_pipeline.py`:

```python
def build_numbered_document_context(chunks: list[dict]) -> str:
    """Render RAG chunks with [N] prefixes so the model can cite them.

    Format matches the agent-mode TOOL_RESULT convention:
        RELEVANT EXCERPTS FROM USER'S DOCUMENTS:
        [1] (file.pdf, p.4): "chunk text"
        [2] (file.pdf, p.7, p.8): "chunk text"
    """
    if not chunks:
        return ""
    lines = ["RELEVANT EXCERPTS FROM USER'S DOCUMENTS:"]
    for idx, ch in enumerate(chunks, start=1):
        pages = ", ".join(f"p.{p}" for p in ch.get("pages", []))
        loc = f"{ch['filename']}, {pages}" if pages else ch["filename"]
        text = ch.get("text", "").strip()
        lines.append(f'[{idx}] ({loc}): "{text}"')
    lines.append(
        "When you state a fact from these excerpts, append [N] at the end "
        "of the claim, matching the index above."
    )
    return "\n".join(lines)


def chunks_to_sources(chunks: list[dict]) -> list[dict]:
    """Convert retrieved chunks into Source records (without idx — the
    caller assigns indices)."""
    from citations import trim_snippet

    sources = []
    for ch in chunks:
        pages = ch.get("pages") or []
        first_page = pages[0] if pages else None
        sources.append(
            {
                "kind": "rag",
                "title": ch["filename"],
                "url": None,
                "domain": None,
                "snippet": trim_snippet(ch.get("text")),
                "meta": {"page": first_page, "pages": pages,
                         "file": ch["filename"]},
            }
        )
    return sources
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pdf_pipeline.py -v`
Expected: 3 passed.

- [ ] **Step 5: Wire numbered context + sources event into `/v1/chat/stream`**

In `gemma_bridge.py`, modify the `chat_stream` handler (defined at line 550). Locate the RAG block beginning at line 588 (`if doc_ids:`). Replace the section from `chunks, emb_latency = ...` through `messages.insert(0, {"role": "system", "content": context_block})` with:

```python
            chunks, emb_latency = pdf_pipeline.retrieve_chunks(
                last_user_text, doc_ids, doc_store, top_k=5
            )
            record_embedding_latency(emb_latency)
            pending_rag_sources: list[dict] = []
            if chunks:
                context_block = pdf_pipeline.build_numbered_document_context(chunks)
                system_injected = False
                for msg in messages:
                    if msg.get("role") == "system":
                        msg["content"] = f"{context_block}\n\n{msg['content']}"
                        system_injected = True
                        break
                if not system_injected:
                    messages.insert(0, {"role": "system", "content": context_block})

                from citations import assign_indices
                rag_sources = pdf_pipeline.chunks_to_sources(chunks)
                assign_indices(rag_sources, existing_count=0)
                pending_rag_sources = rag_sources
        else:
            pending_rag_sources = []
```

Then locate the block that creates the SSE queue (around line 617). Immediately after `sse_queues[task_id] = asyncio.Queue()` and `confirm_queues[task_id] = asyncio.Queue()`, insert:

```python
        if pending_rag_sources:
            await sse_queues[task_id].put(
                json.dumps({"type": "sources", "items": pending_rag_sources})
            )
```

If `json` is not already imported in `gemma_bridge.py`, add `import json` near the top (verify via `grep -n "^import json" gemma_bridge.py`).

- [ ] **Step 6: Run all backend tests**

Run: `.venv/bin/python -m pytest -q -m "not needs_gpu" --ignore=tests/contracts/test_mlx_contract.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add pdf_pipeline.py gemma_bridge.py tests/test_pdf_pipeline.py
git commit -m "feat(citations): number RAG chunks and emit sources event"
```

---

## Task 6: Frontend — chip CSS + marker post-processor

**Files:**

- Modify: `gemma-web/index.html`

This is a manual-smoke task; we add code, then verify in browser. No JS test runner is present in this repo.

- [ ] **Step 1: Add chip + popover CSS**

In `gemma-web/index.html`, locate the existing `.agent-trace` CSS block (around line 1000–1030) and insert a new CSS block immediately after it:

```css
/* ── Citation chips ── */
.citation-chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 16px;
  padding: 0 6px;
  margin: 0 2px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  border: 1px solid var(--chip-border, rgb(199 210 254));
  background: var(--chip-bg, rgb(238 242 255));
  color: var(--chip-fg, rgb(67 56 202));
  cursor: pointer;
  vertical-align: baseline;
  text-decoration: none;
  transition:
    background 120ms ease,
    transform 120ms ease;
}
.citation-chip:hover,
.citation-chip:focus-visible {
  background: var(--chip-bg-hover, rgb(224 231 255));
  outline: none;
  transform: translateY(-1px);
}
.citation-chip[data-kind="web"] {
  --chip-border: rgb(199 210 254);
  --chip-bg: rgb(238 242 255);
  --chip-bg-hover: rgb(224 231 255);
  --chip-fg: rgb(67 56 202);
}
.citation-chip[data-kind="rag"] {
  --chip-border: rgb(167 243 208);
  --chip-bg: rgb(236 253 245);
  --chip-bg-hover: rgb(209 250 229);
  --chip-fg: rgb(4 120 87);
}
.citation-chip[data-kind="file"] {
  --chip-border: rgb(203 213 225);
  --chip-bg: rgb(248 250 252);
  --chip-bg-hover: rgb(241 245 249);
  --chip-fg: rgb(51 65 85);
  cursor: default;
}
.citation-popover {
  position: fixed;
  z-index: 1000;
  max-width: 320px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgb(226 232 240);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
  font-size: 12px;
  color: rgb(30 41 59);
  opacity: 0;
  pointer-events: none;
  transition: opacity 120ms ease;
}
.dark .citation-popover {
  background: rgba(15, 23, 42, 0.92);
  border-color: rgb(51 65 85);
  color: rgb(226 232 240);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.citation-popover.visible {
  opacity: 1;
  pointer-events: auto;
}
.citation-popover-title {
  font-weight: 700;
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.citation-popover-domain {
  font-size: 10px;
  opacity: 0.7;
  margin-bottom: 6px;
}
.citation-popover-snippet {
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  max-height: 160px;
  overflow: auto;
}
.citation-popover-action {
  margin-top: 8px;
  font-size: 11px;
  opacity: 0.7;
}
.citation-footer {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed rgb(226 232 240);
  font-size: 11px;
  color: rgb(71 85 105);
}
.citation-footer-summary {
  cursor: pointer;
  user-select: none;
}
.citation-footer-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
```

- [ ] **Step 2: Add the marker→chip post-processor and source store**

Locate the `<script>` block. Add the following helpers near the top of the assistant-message rendering area (right before or after `appendMessage`):

```javascript
// ── Citation chip rendering ──────────────────────────────────────
const _citationSourceStore = new WeakMap();
const KIND_ICON = { web: "🌐", rag: "📄", file: "📁" };

function renderCitations(containerEl, sources) {
  if (!sources || sources.length === 0) return;
  _citationSourceStore.set(containerEl, sources);

  const proseEl = containerEl.querySelector(".prose") || containerEl;
  const skipTags = new Set(["CODE", "PRE", "A", "BUTTON"]);
  const walker = document.createTreeWalker(proseEl, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      let p = node.parentElement;
      while (p && p !== proseEl) {
        if (skipTags.has(p.tagName)) return NodeFilter.FILTER_REJECT;
        p = p.parentElement;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const textNodes = [];
  let n;
  while ((n = walker.nextNode())) textNodes.push(n);

  const markerPattern = /\[(\d+)\]/g;
  const validIdx = new Set(sources.map((s) => s.idx));

  for (const node of textNodes) {
    const text = node.nodeValue;
    const matches = [...text.matchAll(markerPattern)];
    if (matches.length === 0) continue;

    const frag = document.createDocumentFragment();
    let last = 0;
    let touched = false;
    for (const m of matches) {
      const idx = parseInt(m[1], 10);
      if (!validIdx.has(idx)) continue;
      touched = true;
      const start = m.index;
      const end = start + m[0].length;
      if (start > last) {
        frag.appendChild(document.createTextNode(text.slice(last, start)));
      }
      const source = sources.find((s) => s.idx === idx);
      frag.appendChild(buildChipEl(source));
      last = end;
    }
    if (!touched) continue;
    if (last < text.length) {
      frag.appendChild(document.createTextNode(text.slice(last)));
    }
    node.parentNode.replaceChild(frag, node);
  }

  renderCitationFooterIfNeeded(containerEl, sources);
}

function buildChipEl(source) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "citation-chip";
  btn.dataset.kind = source.kind;
  btn.dataset.idx = String(source.idx);
  btn.setAttribute("aria-label", `Source ${source.idx}: ${source.title}`);
  btn.textContent = String(source.idx);
  attachChipBehavior(btn, source);
  return btn;
}

function renderCitationFooterIfNeeded(containerEl, sources) {
  const used = new Set();
  containerEl.querySelectorAll(".citation-chip").forEach((c) => {
    used.add(parseInt(c.dataset.idx, 10));
  });
  const unused = sources.filter((s) => !used.has(s.idx));
  if (unused.length === 0) return;
  const footer = document.createElement("div");
  footer.className = "citation-footer";
  const summary = document.createElement("div");
  summary.className = "citation-footer-summary";
  summary.textContent = `📎 ${unused.length} source${unused.length === 1 ? "" : "s"}`;
  const list = document.createElement("div");
  list.className = "citation-footer-list";
  list.style.display = "none";
  unused.forEach((s) => list.appendChild(buildChipEl(s)));
  summary.addEventListener("click", () => {
    list.style.display = list.style.display === "none" ? "flex" : "none";
  });
  footer.appendChild(summary);
  footer.appendChild(list);
  containerEl.appendChild(footer);
}

function attachChipBehavior(btn, source) {
  // Click stub only; popover wiring added in Task 7, RAG modal in Task 8.
  btn.addEventListener("click", () => {
    if (source.kind === "web" && source.url) {
      window.open(source.url, "_blank", "noopener,noreferrer");
    }
  });
}
```

- [ ] **Step 3: Wire the streaming handler to pass sources events to the renderer**

Find `handleAgentEvent` (around `gemma-web/index.html:4687`). Add a new branch — place it before the `if (event.type === "done")` branch:

```javascript
if (event.type === "sources") {
  // Buffer until 'done' so we can render once the message exists.
  const existing = traceContainer.dataset.pendingSources
    ? JSON.parse(traceContainer.dataset.pendingSources)
    : [];
  traceContainer.dataset.pendingSources = JSON.stringify(
    existing.concat(event.items || [])
  );
  return;
}
```

Then, inside the existing `done` branch, after `appendMessage(...)` is called (around line 4745), add:

```javascript
if (traceContainer.dataset.pendingSources) {
  const sources = JSON.parse(traceContainer.dataset.pendingSources);
  const lastAssistant = chatBox.querySelector(".message-gemma:last-of-type");
  if (lastAssistant && sources.length) {
    renderCitations(lastAssistant, sources);
  }
  if (currentChat && currentChat.messages.length) {
    const last = currentChat.messages[currentChat.messages.length - 1];
    if (last.role === "assistant") {
      last.sources = sources;
      saveChats();
    }
  }
  delete traceContainer.dataset.pendingSources;
}
```

- [ ] **Step 4: Manual smoke**

Run the bridge + Node proxy and ask a query that triggers `google_search`:

```bash
# Shell A:
.venv/bin/python gemma_bridge.py
# Shell B:
cd gemma-web && node server.js
```

Open `http://localhost:3001`, ask "What was the score of the last Lakers game?" in agent mode. Expected: at least one indigo chip appears next to the score. Click → opens the source URL in a new tab. No console errors.

If chips do not appear, log `event.items` in the sources branch. Common cause: the model didn't emit `[1]` — restart the bridge so AGENT_SYSTEM_PROMPT updates from Task 4 are live.

- [ ] **Step 5: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(citations): render chip markers in assistant messages"
```

---

## Task 7: Hover popover with safe-triangle pinning

**Files:**

- Modify: `gemma-web/index.html`

The popover content is built with DOM methods (no string templates) so user-controlled fields can't be interpreted as HTML.

- [ ] **Step 1: Replace `attachChipBehavior` with full hover + focus logic**

In `gemma-web/index.html`, replace the stub `attachChipBehavior` from Task 6 with:

```javascript
const _popover = (() => {
  let el = null;
  let openTimer = null;
  let closeTimer = null;

  function ensure() {
    if (el) return el;
    el = document.createElement("div");
    el.className = "citation-popover";
    el.setAttribute("role", "tooltip");
    document.body.appendChild(el);
    el.addEventListener("mouseenter", () => {
      clearTimeout(closeTimer);
    });
    el.addEventListener("mouseleave", scheduleClose);
    return el;
  }

  function position(chip) {
    ensure();
    const r = chip.getBoundingClientRect();
    el.style.left = "-9999px";
    el.style.top = "-9999px";
    el.classList.add("visible");
    const pr = el.getBoundingClientRect();
    const margin = 8;
    let top = r.top - pr.height - margin;
    if (top < margin) top = r.bottom + margin;
    let left = r.left + r.width / 2 - pr.width / 2;
    left = Math.max(
      margin,
      Math.min(left, window.innerWidth - pr.width - margin)
    );
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }

  function render(source) {
    ensure();
    // Replace children via DOM methods — never interpret user data as HTML.
    el.replaceChildren();

    const titleEl = document.createElement("div");
    titleEl.className = "citation-popover-title";
    titleEl.textContent = `${KIND_ICON[source.kind] || "🔗"} ${source.title || "Untitled"}`;
    el.appendChild(titleEl);

    if (source.kind === "rag" && source.meta && source.meta.page) {
      const pageEl = document.createElement("div");
      pageEl.className = "citation-popover-domain";
      pageEl.textContent = `page ${source.meta.page}`;
      el.appendChild(pageEl);
    } else if (source.domain) {
      const domEl = document.createElement("div");
      domEl.className = "citation-popover-domain";
      domEl.textContent = source.domain;
      el.appendChild(domEl);
    }

    const snipEl = document.createElement("div");
    snipEl.className = "citation-popover-snippet";
    snipEl.textContent = source.snippet || "";
    el.appendChild(snipEl);

    let actionText = "";
    if (source.kind === "web") actionText = "Click chip to open ↗";
    else if (source.kind === "rag") actionText = "Click chip for full chunk →";
    if (actionText) {
      const actEl = document.createElement("div");
      actEl.className = "citation-popover-action";
      actEl.textContent = actionText;
      el.appendChild(actEl);
    }
  }

  function open(chip, source) {
    clearTimeout(closeTimer);
    clearTimeout(openTimer);
    openTimer = setTimeout(() => {
      render(source);
      position(chip);
    }, 150);
  }

  function scheduleClose() {
    clearTimeout(openTimer);
    closeTimer = setTimeout(() => {
      if (el) el.classList.remove("visible");
    }, 120);
  }

  function closeNow() {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    if (el) el.classList.remove("visible");
  }

  return { open, scheduleClose, closeNow };
})();

function attachChipBehavior(btn, source) {
  btn.addEventListener("mouseenter", () => _popover.open(btn, source));
  btn.addEventListener("mouseleave", () => _popover.scheduleClose());
  btn.addEventListener("focus", () => _popover.open(btn, source));
  btn.addEventListener("blur", () => _popover.scheduleClose());
  btn.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      _popover.closeNow();
      btn.blur();
    }
  });
  btn.addEventListener("click", () => {
    if (source.kind === "web" && source.url) {
      window.open(source.url, "_blank", "noopener,noreferrer");
    }
    // RAG modal wiring added in Task 8.
  });
}
```

- [ ] **Step 2: Manual smoke**

Reload the page. Hover a chip → popover appears with title, domain (or page for RAG), snippet. Move mouse off → popover closes after ~120ms. Tab to a chip via keyboard → popover opens. `Esc` closes.

- [ ] **Step 3: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(citations): hover/focus popover with safe-triangle"
```

---

## Task 8: RAG modal on click

**Files:**

- Modify: `gemma-web/index.html`

- [ ] **Step 1: Add modal CSS**

In `gemma-web/index.html`, append to the citation CSS block from Task 6:

```css
.citation-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  z-index: 2000;
  display: none;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(2px);
}
.citation-modal-backdrop.visible {
  display: flex;
}
.citation-modal {
  max-width: 560px;
  width: calc(100vw - 32px);
  max-height: 80vh;
  background: white;
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.dark .citation-modal {
  background: rgb(15 23 42);
  color: rgb(226 232 240);
}
.citation-modal-title {
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}
.citation-modal-meta {
  font-size: 12px;
  opacity: 0.7;
}
.citation-modal-body {
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow: auto;
  flex: 1 1 auto;
  padding: 12px;
  border-radius: 8px;
  background: rgb(248 250 252);
}
.dark .citation-modal-body {
  background: rgb(30 41 59);
}
.citation-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.citation-modal-actions button {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid rgb(203 213 225);
  background: white;
  cursor: pointer;
}
.dark .citation-modal-actions button {
  background: rgb(30 41 59);
  border-color: rgb(71 85 105);
  color: rgb(226 232 240);
}
.citation-modal-actions button.primary {
  background: rgb(16 185 129);
  color: white;
  border-color: rgb(16 185 129);
}
```

- [ ] **Step 2: Add modal JS + wire chip clicks**

Append after the popover IIFE from Task 7:

```javascript
function openRagModal(source) {
  const backdrop = document.createElement("div");
  backdrop.className = "citation-modal-backdrop visible";
  const modal = document.createElement("div");
  modal.className = "citation-modal";

  const pages =
    source.meta && source.meta.pages && source.meta.pages.length
      ? source.meta.pages.map((p) => `p.${p}`).join(", ")
      : source.meta && source.meta.page
        ? `p.${source.meta.page}`
        : "";

  const titleEl = document.createElement("div");
  titleEl.className = "citation-modal-title";
  titleEl.textContent = `📄 ${source.title || "Document chunk"}`;

  const metaEl = document.createElement("div");
  metaEl.className = "citation-modal-meta";
  metaEl.textContent = pages ? `${source.title} · ${pages}` : source.title;

  const bodyEl = document.createElement("div");
  bodyEl.className = "citation-modal-body";
  bodyEl.textContent = source.snippet || "(no excerpt available)";

  const actions = document.createElement("div");
  actions.className = "citation-modal-actions";
  const closeBtn = document.createElement("button");
  closeBtn.textContent = "Close";
  closeBtn.addEventListener("click", () => backdrop.remove());

  const file = source.meta && source.meta.file;
  const att = (currentAttachments || []).find(
    (a) => a.type === "pdf" && a.name === file
  );
  if (att && att.doc_id) {
    const openBtn = document.createElement("button");
    openBtn.className = "primary";
    openBtn.textContent = "Open PDF";
    openBtn.addEventListener("click", () => {
      window.open(
        `/api/document/${att.doc_id}`,
        "_blank",
        "noopener,noreferrer"
      );
    });
    actions.appendChild(openBtn);
  }
  actions.appendChild(closeBtn);

  modal.appendChild(titleEl);
  modal.appendChild(metaEl);
  modal.appendChild(bodyEl);
  modal.appendChild(actions);
  backdrop.appendChild(modal);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) backdrop.remove();
  });
  document.body.appendChild(backdrop);

  const onKey = (e) => {
    if (e.key === "Escape") {
      backdrop.remove();
      document.removeEventListener("keydown", onKey);
    }
  };
  document.addEventListener("keydown", onKey);
}
```

Then replace the click handler inside `attachChipBehavior` (from Task 7) with:

```javascript
btn.addEventListener("click", () => {
  _popover.closeNow();
  if (source.kind === "web" && source.url) {
    window.open(source.url, "_blank", "noopener,noreferrer");
  } else if (source.kind === "rag") {
    openRagModal(source);
  }
  // file kind: no-op
});
```

- [ ] **Step 3: Verify the document resource route**

Run:

```bash
grep -n "/api/document" gemma-web/server.js
```

If a `GET /api/document/:id` route exists, the modal's "Open PDF" link will work. If only `POST /api/document` exists (upload), the button will 404 — in that case, remove the `if (att && att.doc_id)` branch so the button never renders. Either path is acceptable per the spec (page-jumping is out of scope).

- [ ] **Step 4: Manual smoke**

Upload a PDF in chat mode, ask a grounded question. Expected: emerald chips next to claims. Click a chip → modal opens with the chunk text. `Esc` and clicking the backdrop close it.

- [ ] **Step 5: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(citations): RAG chunk modal on chip click"
```

---

## Task 9: Persist sources with chat messages

**Files:**

- Modify: `gemma-web/index.html`

- [ ] **Step 1: Update message reload to render persisted sources**

Find the chat-reload loop (around `gemma-web/index.html:3266`):

```javascript
chat.messages.forEach((msg) => {
  if (msg.role !== "system") {
    appendMessage(msg.role, msg.content, [], false, msg.reasoning);
  }
});
```

Replace with:

```javascript
chat.messages.forEach((msg) => {
  if (msg.role !== "system") {
    appendMessage(msg.role, msg.content, [], false, msg.reasoning);
    if (msg.role === "assistant" && msg.sources && msg.sources.length) {
      const lastAssistant = chatBox.querySelector(
        ".message-gemma:last-of-type"
      );
      if (lastAssistant) {
        renderCitations(lastAssistant, msg.sources);
      }
    }
  }
});
```

- [ ] **Step 2: Manual smoke**

Have an agent-mode conversation that produces chips. Reload the page. Open the same chat from the sidebar. Expected: chips reappear with full hover popover behavior.

- [ ] **Step 3: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(citations): persist sources in localStorage and rehydrate"
```

---

## Task 10: CI gate + push verification

**Files:**

- None modified — verification only.

- [ ] **Step 1: Run the full pre-push pipeline locally**

Run (per `CLAUDE.md` mandate):

```bash
bash .git/hooks/pre-push
```

Expected: exit code 0. Ruff, Prettier, and pytest (excluding `needs_gpu`) all pass.

If any check fails, fix the root cause and re-run. Do **not** use `--no-verify`.

- [ ] **Step 2: Frontend sanity check**

Start the bridge and Node proxy in two shells:

```bash
.venv/bin/python gemma_bridge.py
cd gemma-web && node server.js
```

Open `http://localhost:3001` and complete the manual checklist:

1. Agent mode → ask "lakers game score last night" → web chips appear, hover popover works, click opens new tab.
2. Chat mode → upload a PDF, ask a grounded question → RAG chips appear, click opens modal.
3. Reload page → existing chats show chips with working popovers.
4. Force a no-marker case: ask agent something with low citation pressure ("hi how are you") → no chips, no errors.
5. Markers inside code blocks: ask agent to write code with a literal `[1]` → that `[1]` stays text, not a chip.

- [ ] **Step 3: Push and watch CI**

```bash
git push
```

Then monitor GitHub Actions for `main`:

```bash
gh run list --branch main --limit 1
gh run watch
```

If CI fails on GitHub, diagnose the failure, fix it, push again, and re-watch until green.

- [ ] **Step 4: Final commit (if any fixes were needed)**

If you had to make follow-up fixes after CI red, commit them with a clear message:

```bash
git add -p
git commit -m "fix(citations): <root cause of red CI>"
git push
```

When CI is green, the feature is done per the `CLAUDE.md` Definition of Done.

---

## Self-Review

**Spec coverage check** (each spec section → which task covers it):

- Source data shape → Task 1 (`citations.py`)
- Data flow / new SSE event → Task 3
- File-level changes table → covered across Tasks 1–6
- Prompt strategy: agent CITATIONS block → Task 4
- Prompt strategy: numbered TOOL_RESULTs → Task 3 (formatting in `react_loop_sse`)
- Prompt strategy: RAG chunks numbered → Task 5
- Chip UI / visual style / colors → Task 6
- Hover popover / safe triangle / keyboard → Task 7
- Click behavior: web → Task 6/7; RAG modal → Task 8; file no-op → Task 7
- Marker→chip post-processor with code/pre/anchor skip → Task 6
- Fallback footer → Task 6 (`renderCitationFooterIfNeeded`)
- Accessibility (button + aria, icon as kind signal) → Task 6 + Task 7
- RAG modal "Open PDF" button → Task 8
- Persistence in `localStorage` → Task 9
- Edge case: duplicate URLs → Task 3 (dedupe in `react_loop_sse`)
- Edge case: markers without matching source → Task 6 (`validIdx` guard)
- Edge case: zero results / model_text only → Task 2 (`_google_search` empty path)
- Edge case: markers inside fenced code → Task 6 (walker skip)
- Edge case: cross-turn — indices reset because `run_sources` is local to each `react_loop_sse` invocation
- Investigation tasks from spec → `retrieve_chunks` confirmed to return `pages` (verified during plan prep); `/v1/chat/stream` confirmed to reuse `react_loop_sse` so SSE transport is unified — no `server.js` changes needed
- CI gate → Task 10

**Placeholder scan:** No TBD, TODO, or "implement later" in any task. All code blocks contain runnable code; all commands have expected output stated.

**Type / name consistency:** `Source` dict keys (`idx`, `kind`, `title`, `url`, `domain`, `snippet`, `meta`) used consistently across `citations.py`, tool returns, SSE events, frontend rendering, and persistence. `kind` values are exactly `"web" | "rag" | "file"` across backend and frontend. Function names match across tasks: `assign_indices`, `dedupe_by_url`, `format_sources_for_model`, `trim_snippet`, `build_numbered_document_context`, `chunks_to_sources`, `renderCitations`, `attachChipBehavior`, `openRagModal`.

No gaps found. Plan ready for execution.
