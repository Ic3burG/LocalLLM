# Source Citations Design — LocalLLM

**Date:** 2026-05-19
**Status:** Approved

---

## Overview

Add inline citation chips to assistant messages so users can verify _where_ a claim came from. When the agent calls `google_search` or `web_fetch`, or when chat mode grounds an answer in an uploaded PDF (RAG), each cited claim is followed by a small numbered chip. Hovering shows a preview (title, domain, snippet); clicking opens the source — a URL in a new tab for web sources, an inline modal for PDF chunks.

The feature spans all four content-source paths in the codebase: `google_search`, `web_fetch`, RAG chunk retrieval, and local file reads (`read_file` / `grep_search`). Web sources are clickable links; file sources are hoverable but not clickable.

---

## Goals

- Users can verify any factual claim the model makes by hovering or clicking a chip.
- The chip UI is part of the existing glass-style chat interface — low-contrast at rest, expressive on interaction.
- Sources persist with the chat history (`localStorage`) so reopening an old chat does not produce orphan markers.
- Works for both **agent mode** (tool results) and **chat mode** (RAG chunks).
- Gracefully degrades when the local model forgets to emit citation markers.

## Non-goals

- Validating that a cited source actually supports the claim (no fact-checking).
- Jumping to a specific page inside an embedded PDF viewer.
- Exporting or sharing a "sources only" view of a chat.
- Aggregating citations across the whole conversation into a global panel.

---

## Architecture

### Source data shape

A single `Source` schema covers all four origins:

```js
{
  idx: 1,                           // 1-indexed; matches model's [N] markers
  kind: "web" | "file" | "rag",     // drives chip color + click behavior
  title: "ESPN — NBA Scores",       // popover header
  url: "https://espn.com/nba",      // null for file/rag
  domain: "espn.com",               // derived from url; null for file/rag
  snippet: "Lakers 112, Celtics…",  // ~200 chars
  meta: { page: 4, file: "..." }    // optional, RAG/file kinds
}
```

### Data flow

```
                                            ┌── google_search → [{title, url, snippet}, …]
   Agent mode ─→ ReAct loop in agent.py ────┼── web_fetch     → [{title, url, snippet}]
                  │                          ├── read_file    → [{title=path, url=null, snippet}]
                  │ emits SSE                └── grep_search  → [{title=matched file, snippet=line}]
                  ▼
            { type: "sources", items: [Source, …] }   ← NEW SSE event
                  │
   Chat mode  ─→ gemma_bridge.py RAG path ───────────→ same { type: "sources", … } payload
                  │                                    items: [{title=PDF name, page, snippet=chunk text}]
                  ▼
   index.html buffers Sources for the in-flight assistant message,
   then renders inline chips by replacing [N] markers in the rendered
   HTML with <button class="citation-chip" data-idx="N">.
```

Sources are streamed as a _separate SSE event_, not embedded in the response stream. The message markdown stays clean; the frontend renders chips in a post-processing pass once the message is complete.

### File-level changes

| File                                              | Change                                                                                                                                                                                                   |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent_utils.py` — `_google_search`, `_web_fetch` | Return structured records alongside the existing string. Add a small helper that formats the string for the model with `[N]` prefixes.                                                                   |
| `agent.py` — `react_loop_sse`                     | After each tool call, append new Sources to a per-task accumulator. When a tool produces new sources, emit `{"type": "sources", "items": [...]}` SSE event. Pass numbered TOOL_RESULT back to the model. |
| `gemma_bridge.py` — RAG path                      | When chunks are retrieved, number them `[N] (file, page): "…"` in the system prompt and emit the same `sources` event over the chat SSE stream.                                                          |
| `agent_utils.py` — system prompt                  | Add the CITATIONS block (see "Prompt strategy").                                                                                                                                                         |
| `gemma_bridge.py` — chat system prompt            | Append the CITATIONS block when RAG chunks are present.                                                                                                                                                  |
| `gemma-web/server.js`                             | Pass through the new `sources` SSE event for chat-mode streaming. (Agent SSE proxy is already event-type-agnostic.)                                                                                      |
| `gemma-web/index.html`                            | Add `.citation-chip` / `.citation-popover` CSS, marker→chip post-processor, hover/click logic, RAG modal, `📎 N sources` fallback footer, persistence of `sources` in `localStorage`.                    |
| `tests/test_agent.py`                             | New cases: structured tool return shape, global indexing across multiple tool calls, SSE event emission, CITATIONS block presence in prompts.                                                            |
| `tests/test_rag.py` (or equivalent existing file) | Numbered chunk formatting; sources event for chat mode.                                                                                                                                                  |

---

## Prompt strategy

### Agent mode

Tool results are reformatted with bracketed prefixes so the model never has to invent numbers. Indices are global to the whole ReAct run.

```
TOOL_RESULT:
[1] ESPN — NBA Scores (espn.com)
    Lakers 112, Celtics 108. Final score from Tuesday's game…

[2] NBA.com — Game Recap (nba.com)
    LeBron James scored 35 points in the win…
```

A second `google_search` later in the run continues numbering at `[3]`, `[4]`, etc.

A new CITATIONS block is added to the system prompt near the existing tool-use rules:

```
CITATIONS:
- Tool results are numbered like [1], [2], [3]. These indices are stable
  for the whole conversation turn.
- When stating a fact from a tool result, append the matching index in
  square brackets at the end of the claim. Multiple sources: [1][3].
- Do NOT invent or renumber citations. Only cite indices that appeared
  in a TOOL_RESULT above.
- In your final answer (DONE: …), keep the [N] markers inline.

Example:
  The Lakers beat the Celtics 112–108 [1]. LeBron James led with 35
  points [1][2].
```

### Chat mode (RAG)

RAG chunks are injected with the same `[N]` prefix scheme:

```
RELEVANT EXCERPTS FROM USER'S DOCUMENTS:
[1] (annual_report.pdf, p. 4): "Q3 revenue grew 18% year-over-year…"
[2] (annual_report.pdf, p. 7): "Operating margin expanded to 22.3%…"
```

…and the CITATIONS block is appended to the chat-mode system prompt only when chunks are present.

### Why this works for local models

Gemma- and Phi-class models are reliable at echoing format that is _visible in their input_. "Cite using these indices" is far easier than "invent your own citation scheme." We do not rely on tool-calling JSON or any model-specific structured-output feature.

---

## Chip UI

### Visual style

Inline chip renders where `[N]` appeared in the message. Small, pill-shaped, ~16px tall. Color encodes kind:

| Kind                             | Border      | Number bg  | Click does…                                       |
| -------------------------------- | ----------- | ---------- | ------------------------------------------------- |
| `web` (search / fetch)           | indigo-200  | indigo-50  | opens URL in new tab (`noopener,noreferrer`)      |
| `rag` (PDF chunk)                | emerald-200 | emerald-50 | opens inline modal with chunk + "Open PDF" button |
| `file` (read_file / grep_search) | slate-200   | slate-50   | no-op (chip is still hoverable for the snippet)   |

Icon (🌐 / 📄 / 📁) duplicates the kind so color is never the only signal.

### Interaction contract

| State               | Behavior                                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Hover (after 150ms) | Popover fades in above chip; flips below if no vertical room. Pins while pointer is in chip or popover (safe-triangle pattern). |
| Focus (keyboard)    | Popover opens immediately. `Esc` closes. `Enter` activates click action.                                                        |
| Click — `web` chip  | `window.open(url, '_blank', 'noopener,noreferrer')`                                                                             |
| Click — `rag` chip  | Opens modal with full chunk, filename, page, "Open PDF" button (if file is in the chat's attachment list).                      |
| Click — `file` chip | No-op.                                                                                                                          |
| Touch               | Tap → opens popover. Second tap on chip → click action. Tap outside → closes.                                                   |

### Marker → chip post-processor

After markdown rendering, walk text nodes in the rendered HTML, find `[N]` substrings, and replace them with chip elements. The walker **skips** text inside `<code>`, `<pre>`, and `<a>` so markers inside code blocks or existing links are left alone.

### Fallback footer

When the model returns zero markers but the sources list is non-empty, render a small `📎 N sources` strip at the end of the message. Clicking expands a list of the same chip components inline. This keeps the feature valuable even on turns where the model forgets to mark its claims.

### Accessibility

- Chip is a `<button>` with `aria-describedby` pointing to the popover element.
- Popover uses `role="tooltip"` with the snippet as accessible text.
- Color is never the sole signal — the icon (🌐/📄/📁) carries the kind.

---

## RAG behavior detail

| User action         | What happens                                                                                                                     |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Hover on `rag` chip | Popover shows filename, page (if known), and exact chunk text.                                                                   |
| Click on `rag` chip | Modal opens with: full chunk, filename, page, **"Open PDF" button**.                                                             |
| "Open PDF" button   | If the PDF is in the current chat's attachment list, opens it via the Node proxy's static route. Otherwise the button is hidden. |

Page-jumping inside an embedded PDF viewer is out of scope — users navigate manually using the displayed page number.

If `retrieve_chunks` does not expose page metadata, `meta.page` is `null` and the chip popover omits the page line.

**Investigation tasks for the implementation plan (known unknowns):**

1. Read `pdf_pipeline.retrieve_chunks` to confirm what metadata it returns per chunk. If page numbers are already threaded through, plumb them straight to the Source record. If not, decide whether adding them is in scope for this cycle or whether `meta.page` stays `null`.
2. Confirm the chat-mode streaming transport in `gemma_bridge.py`. If it's already `text/event-stream` (SSE), the new `sources` event drops in next to the existing `chat.completion.chunk` events. If it uses a different protocol, the implementation plan needs an additional step to add SSE there.

---

## Persistence

Each assistant message gets a new `sources` field stored alongside `content` and `trace`:

```js
{
  role: "assistant",
  content: "The Lakers beat the Celtics 112–108 [1] …",
  trace: [...],          // existing
  sources: [             // NEW
    { idx: 1, kind: "web", title: "ESPN — NBA Scores",
      url: "https://espn.com/nba", domain: "espn.com",
      snippet: "Lakers 112, Celtics 108…", meta: {} },
    ...
  ]
}
```

On chat reload, the marker→chip post-processor runs on the persisted content and rebuilds chips from the stored `sources`. **No re-fetching, no migrations** — old messages lacking a `sources` array render `[N]` as plain text (graceful degradation).

---

## Edge cases

- **Duplicate sources** (same URL fetched twice in one run) — dedupe by URL; reuse the lower index.
- **Markers without a matching source** (model hallucinates `[7]` when only 3 sources exist) — render `[7]` as plain text; log a warning.
- **Zero search results** — no sources event, no chips. Model receives that information in the TOOL_RESULT and chooses what to say.
- **Cross-turn references** — source numbering does _not_ carry across turns; each turn starts at `[1]`. A follow-up that re-cites prior content must re-cite via a fresh tool call.
- **Markers inside fenced code** — post-processor skips `<code>` and `<pre>` text nodes, so `like [1] in code` stays literal.
- **Marker collision with prose** (e.g., user-supplied text already contains `[1]`) — accepted limitation; the post-processor only runs on assistant messages, not user messages.

---

## Testing strategy

### Backend (pytest)

- `test_google_search_returns_structured()` — verify the new shape `{title, url, snippet}` and that the legacy string formatting still feeds the model with `[N]` prefixes.
- `test_web_fetch_emits_source()` — single-source case, derives `title` and `domain` correctly.
- `test_sources_indexing_is_global_per_run()` — two `google_search` calls in one ReAct loop produce `[1][2][3][4][5][6]`, not `[1][2]` twice.
- `test_rag_chunks_get_numbered_in_prompt()` — verify `[N] (file.pdf, p.4): "…"` format.
- `test_sse_emits_sources_event()` — assert a `"type": "sources"` event was queued after each citing tool call.
- `test_citation_instructions_in_system_prompts()` — both agent and RAG prompts contain the CITATIONS block (and chat-mode prompt omits it when no chunks are present).
- `test_duplicate_source_dedup()` — same URL twice yields one Source with the lower index.

### Frontend (manual smoke; existing repo has no JS test runner)

- Agent mode: "what's the score of last night's Lakers game" → chip appears next to the score; hover shows ESPN snippet; click opens new tab.
- Chat mode with RAG: upload a PDF, ask a question → `rag` chips appear; hover shows chunk; click opens modal with "Open PDF".
- Reload page → existing chat renders chips correctly from `localStorage`.
- Force model to skip markers (manual test or stubbed turn) → `📎 N sources` footer appears.
- Marker inside a fenced code block → not converted to a chip.

### CI gate

`bash .git/hooks/pre-push` must pass (mandated by `CLAUDE.md`). All new tests must run under the existing pytest configuration; GPU-only paths stay marked `needs_gpu`.

---

## Out of scope (deferred)

- Citation accuracy validation.
- Embedded PDF viewer with page anchors.
- Sources export / share view.
- Global per-chat sources panel.
- Cross-turn source persistence.

These are reasonable follow-ups but would expand scope beyond a single implementation cycle.
