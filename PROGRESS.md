# Gemma 4 Local Project Progress - April 22, 2026

Today we transformed the local Gemma 4 environment from a broken prototype into a high-performance, multi-model, multimodal AI suite.

## 🛠 Fixes & Infrastructure

- **Resolved LiteRT-LM Incompatibility:** Fixed an issue where the Go-based `lit.macos_arm64` binary was incompatible with the local model files, causing 404/500 errors.
- **Created Python Bridge:** Developed `gemma_bridge.py`, a FastAPI-based server that provides an OpenAI-compatible API.
- **Persistent Service:** Updated the macOS Launch Agent (`com.gemini.litert.plist`) to automatically manage the new Python bridge in the background.
- **Multi-Engine Support:** Updated the bridge to intelligently switch between **LiteRT-LM** (for small models) and **MLX-LM** (Apple Silicon native) for heavy lifting.

## 🧠 Model Suite Expansion

- **64GB RAM Optimization:** Leveraged the system's high RAM to enable elite-tier local models.
- **Active Models:**
  - **Gemma 4 E4B:** Optimized for speed and daily tasks (LiteRT).
  - **Phi-4 Mini:** Added as a high-quality 3.6B alternative (LiteRT).
  - **Gemma 4 26B A4B (MoE):** Installed via MLX for high-level reasoning and vision tasks.
  - **Gemma 4 31B Dense:** Installed via MLX as the "Elite" frontier model for intelligence and vision.

## 🎨 UI & UX Enhancements

- **Markdown & Code Highlighting:** Enabled full rich-text rendering with syntax highlighting for technical responses.
- **Theme Engine:** Implemented Light/Dark mode with automatic system preference detection and a manual toggle.
- **Conversation History:** Added a persistent sidebar that saves and restores multiple chats locally via `localStorage`.
- **Multimodal Support:**
  - Added a **Plus (+) button** and **Drag & Drop** for file uploads.
  - Enabled support for **Images** (vision tasks) and **Text Files** (.txt/.md) within the chat flow.
- **Clean UI:** Removed focus outlines (blue rings) from the chat box for a more premium, minimalist feel.

## 🧠 Intelligent Memory System

- **Autonomous Learning:** Added a background "Learner Subagent" that analyzes every interaction.
- **Persistent Knowledge:** Created `USER_MEMORY.md` to store facts, preferences, and technical context learned over time.
- **System Injection:** The bridge now automatically injects this learned context into the system prompt of every conversation, giving the model long-term memory.
- **Live Memory View:** Added a real-time "Learned Memory" preview to the sidebar.

---

## 🤖 Agentic Layer — April 27, 2026

Evolved the app from a pure chat interface into a full agentic tool. The model can now orchestrate multi-step work via a ReAct loop, interact with the filesystem and shell, manage scheduled tasks, and ask for user approval before running anything risky.

### Architecture

A new `agent.py` FastAPI router is mounted on `gemma_bridge.py` at `/v1/agent/*`. It calls model inference via direct Python function calls (no HTTP loopback) and streams results to the frontend via SSE.

```
Browser → server.js (port 3001) → gemma_bridge.py (port 9379)
                                     ├─ /v1/chat/*      (existing)
                                     └─ /v1/agent/*     (new)
                                          ├─ Tool Registry (10 tools)
                                          ├─ ReAct Loop (max 20 steps)
                                          ├─ Confirmation Gate
                                          ├─ SSE Streaming
                                          └─ APScheduler + crontab
```

### Tool Registry

| Risk | Tools |
|---|---|
| Safe (auto-run) | `read_file`, `list_dir`, `list_crons`, `list_scheduled_tasks` |
| Risky (ask first) | `write_file`, `append_file`, `shell`, `create_cron`, `delete_cron`, `create_scheduled_task` |

### ReAct Loop

Text-based tool invocation (Gemma doesn't emit native function-call JSON). Model outputs `TOOL: name("arg1", "arg2")` or `DONE: summary`. Bridge parses, executes, and feeds `TOOL_RESULT:` back — up to 20 iterations per run.

### Confirmation Gate

Risky tools pause execution and emit a `confirm_request` SSE event. Frontend renders an inline card showing the exact tool call and args. User clicks Allow or Deny → `POST /v1/agent/confirm/{task_id}` → loop resumes.

### Dual Scheduler

- **In-App (APScheduler):** `AsyncIOScheduler` running inside FastAPI's asyncio loop. Tasks persist in `scheduler_tasks.json` and run full ReAct loops on schedule. Results logged to `scheduler_log.jsonl`.
- **System Crontab:** Read/write via `crontab -l` / `crontab -`. Agent-managed entries tagged `# gemma:<name>` to isolate them from pre-existing cron jobs.

### UI Changes (`index.html`)

1. **Agent Mode Toggle** — pill above the input switches Chat ↔ Agent mode
2. **Hybrid Trace** — collapsed `⚙ N steps · Xs` summary, expandable to per-call detail with results
3. **Confirmation Modal** — inline card with tool name, args, risk description, Allow/Deny buttons (no browser alerts)
4. **Scheduled Tasks Panel** — collapsible sidebar section listing in-app tasks and a cron placeholder; inline add/delete form

### Files Changed

| File | Change |
|---|---|
| `agent.py` | New — 315 lines: tool registry, ReAct loops, SSE streaming, scheduler, API endpoints |
| `scheduler_tasks.json` | New — persisted in-app task definitions |
| `gemma_bridge.py` | Added `run_inference` shared helper; mounted agent router; added APScheduler startup |
| `gemma-web/server.js` | Added 6 agent proxy routes (SSE-aware stream handler) |
| `gemma-web/index.html` | Agent toggle, hybrid trace UI, confirmation modal, scheduled tasks panel |
| `tests/test_agent.py` | 24 tests covering inference routing, all 10 tools, parser, ReAct loop, scheduler CRUD |
| `pytest.ini` | New — `asyncio_mode = auto` |
| `requirements.txt` | Added `apscheduler` |

---

## 🔀 Unified mlx_vlm Migration — April 28, 2026

Replaced the two-engine backend (LiteRT for E4B, mlx_lm for 26B/31B) with a single `mlx_vlm` stack covering all three models — text and vision — through one code path.

### Motivation

- LiteRT is a single-threaded C++ engine; inference blocked the asyncio event loop even after a ThreadPoolExecutor workaround.
- mlx_lm (used for 26B/31B) had no vision support — image inputs were silently discarded.
- mlx_vlm is a superset of mlx_lm, natively supports both text and vision, and is optimised for Apple Silicon.

### Architecture Changes

**Removed from `gemma_bridge.py`:**
- `import litert_lm` / `from litert_lm import Backend`
- `get_litert_engine`, `get_mlx_model`, `process_multimodal_content`, `handle_litert_request`, `handle_mlx_request`
- `MODELS_BASE_DIR`, `litert_engines`, `mlx_models_cache`

**Added to `gemma_bridge.py`:**
- Single persistent daemon thread (`mlx-inference`) that owns all mlx GPU state — required because mlx GPU streams are thread-local and must be created on the thread that runs inference.
- `mlx_vlm` imported inside the worker thread so `generation_stream` is created in the right thread context.
- `_run_in_inference_thread()` bridges the asyncio event loop to the worker via `asyncio.Future` + `call_soon_threadsafe`.
- `_inference_ready` threading Event guards against requests arriving before the worker finishes its import.
- `get_mlx_vlm_model(model_id)` — loads and caches `(model, processor)` pairs with `_MODEL_DIR_MAP` for canonical ID → directory resolution.
- `handle_mlx_vlm_request(model_id, messages)` — unified handler: extracts text + optional base64 image (written to temp file, cleaned up in `finally`), renders chat template, calls `mlx_vlm.generate`, extracts `.text` from `GenerationResult`.
- `run_inference` simplified — no more `is_mlx` routing condition.
- `list_models` returns canonical model IDs (e.g. `"gemma4-e4b"`) not directory names, with `provider: "mlx_vlm"`.

### New Model

- **Gemma 3 E4B (mlx_vlm):** Downloaded `mlx-community/gemma-3-4b-it-4bit` (~3.2 GB) to `mlx_models/gemma-3-4b-it-4bit/`. Replaces the old LiteRT E4B model with full vision support.

### Files Changed

| File | Change |
|---|---|
| `gemma_bridge.py` | Full engine replacement — removed LiteRT/mlx_lm, added mlx_vlm worker thread architecture |
| `requirements.txt` | Added `mlx-vlm`, `Pillow`; removed `mlx-lm` direct dependency |
| `tests/test_agent.py` | Updated inference routing tests to mock `handle_mlx_vlm_request`; added `mlx_vlm` to stub list |
| `docs/superpowers/specs/` | New: mlx_vlm migration design spec |
| `docs/superpowers/plans/` | New: mlx_vlm migration implementation plan |

---

## 🛠 Advanced Tool Access: Web Research — April 28, 2026 (Session 2)

Implemented the first phase of the Advanced Tool Access plan, adding web research capabilities to the agent.

### New Tools

- **_google_search(query)**: Uses `googlesearch-python` to retrieve the top 5 URLs for a given query.
- **_web_fetch(url)**: Uses `requests` and `BeautifulSoup` to fetch and clean the content of a webpage (removing scripts/styles and limiting to 5000 chars).

### Files Changed

| File | Change |
|---|---|
| `agent.py` | Implemented `_google_search` and `_web_fetch` internal methods |
| `tests/test_agent_tools.py` | New — tests for the new web research tools |

---

## 🛠 Stability Fixes & Restart Button — April 28, 2026 (Session 4)

Fixed all bugs introduced by the Session 3 unified agentic chat refactor, then added a user-friendly backend restart button to the Settings UI.

### Restart Backend Button

Added to the Settings modal so users can restart the Python bridge without terminal access.

**Backend (`gemma-web/server.js`):**
- `GET /api/backend/status` — pings port 9379 with a 3 s timeout; returns `{ online: true/false }`
- `POST /api/backend/restart` — kills any `gemma_bridge.py` process, waits 1.5 s, then spawns a fresh one.

**Frontend (`gemma-web/index.html`):** Inline Restart Backend button in the Settings modal. Polls `/api/backend/status` every 2 s after clicking and shows "Restarting… Online / Failed" state.

---

## 🎨 Dark/Light Mode Fix — April 28, 2026 (Session 4, continued)

Audited the entire UI for dark/light mode breakage, established a CSS token system and design rules doc, then fixed every broken component.

### Token System

| Token | Light | Dark | Use for |
|---|---|---|---|
| `--color-bg` | `#f8f9fa` | `#0e0e11` | Page background, confirm cards |
| `--color-surface` | `#ffffff` | `#1e1f20` | Cards, inputs, code blocks |
| `--color-border` | `#e5e7eb` | `#3c3d40` | All borders, dividers |
| `--color-text` | `#111827` | `#f3f4f6` | Primary text, input values |
| `--color-text-muted` | `#6b7280` | `#9ca3af` | Timestamps, labels, placeholders |
| `--color-accent` | `#3b82f6` | `#3b82f6` | Focus rings, active states, buttons |

### Files Changed

| File | Change |
|---|---|
| `gemma-web/index.html` | Token definitions, 19 consumer renames, hardcoded color replacements, dead rule deletions, highlight.js href swap |
| `gemma-web/THEME.md` | New — quick-reference token table, design rules |

---

## 🪵 Robust Error Logging — April 29, 2026

Implemented end-to-end structured logging across all layers: JSON lines to a rotating file (`app.log`) for machine parsing, human-readable stdout for live debugging.

### Files Changed

| File | Change |
|---|---|
| `logging_config.py` | **New** — `setup_logging()`, `JsonLinesFormatter`, `HumanFormatter`, `task_id_var` |
| `gemma_bridge.py` | Replaced `basicConfig` → `setup_logging()`; added `RequestLoggingMiddleware` |
| `gemma-web/server.js` | `log()` helper + structured logs on every route |

---

## 🔧 Model Suite Overhaul & Bug Fixes — April 29, 2026 (Session 2)

### Model Corrections

Discovered that `gemma4-e4b` was mapped to `mlx-community/gemma-3-4b-it-4bit` (Gemma **3**) — a mismatch left over from the mlx_vlm migration. All four models are now correctly mapped to Gemma 4 releases.

**Corrected `_MODEL_DIR_MAP`:**

| Model ID | Directory | HF Source |
|---|---|---|
| `gemma4-e4b` | `gemma-4-e4b-it-4bit` | `mlx-community/gemma-4-e4b-it-4bit` |
| `phi4-mini` | `phi-4-mini-4bit` | `mlx-community/Phi-4-mini-instruct-4bit` |
| `gemma4-26b-mlx` | `gemma-4-26b-a4b-it-4bit` | `mlx-community/gemma-4-26b-a4b-it-4bit` |
| `gemma4-31b-mlx` | `gemma-4-31b-it-4bit` | `mlx-community/gemma-4-31b-it-4bit` |

---

## 🔧 26B Model Response Fixes — May 2, 2026

Investigated and fixed a multi-root-cause bug where the Gemma 4 26B model produced no visible response on the frontend.

### Fixes
- **`agent_utils.py`**: New `strip_thinking_blocks()` helper covering Gemma 4 channel format.
- **`agent.py`**: Both react loops strip thinking blocks before `done` event.
- **`gemma-web/server.js`**: `res.socket.setTimeout(0)` in SSE proxy to prevent 120 s kill.

---

## 🛡️ Security Audit & Longevity Layer — May 2, 2026 (Session 2)

Performed a comprehensive security and stability audit, resulting in a hardened project structure and a new layer for long-term reliability.

### Files Changed

| File | Change |
|---|---|
| `agent_utils.py` | Added `validate_path`, `validate_url`, `log_audit`. |
| `inference_engine.py` | **Major Refactor** — Consolidated all MLX/GPU state, implemented LRU cache, and added the Inference Watchdog. |
| `SECURITY.md` | **New** — Comprehensive documentation of findings, fixes, and future roadmap. |

---

## 🔧 SSE Pipeline Fix: Tool-Calling Models Now Deliver Results to UI — May 6, 2026

Fixed a multi-factor bug where multi-step tool-calling requests with the 26B model would complete successfully in the Python backend but the frontend was permanently stuck in "Thinking…".

### Files Changed

| File | Change |
|---|---|
| `agent.py` | 15-second SSE heartbeat; `Cache-Control`/`X-Accel-Buffering` headers |
| `gemma-web/server.js` | Upstream Node→Python socket timeout disabled |
| `gemma-web/index.html` | `taskDone` flag; 90-second stall timer; smarter `onerror` |

---

## 🛡️ Code Integrity & Health Roadmap — May 6, 2026

Implemented a multi-layered verification and monitoring suite to protect the project from regressions, library rot, and performance degradation.

### Files Changed

| File | Change |
|---|---|
| `scripts/smoke_test.py` | **New** — Connectivity and functional roundtrip utility with JSON support |
| `tests/contracts/` | **New** — Suite of unmocked integration tests for external dependencies |
| `inference_engine.py` | Added latency tracking, thread-safe cache locking, and telemetry helpers |
| `gemma-web/index.html` | Redesigned Settings modal with tabbed interface and Vitals dashboard |

---

## 🎨 UI Polish & Stability Fixes — May 6, 2026 (Session 2)

Refined the Vitals dashboard and Settings modal for better user experience and system resilience.

---

## 🐛 Confirmation Gate Fix & "Always Allow" — May 6, 2026 (Session 3)

Fixed a critical bug where the agent confirmation modal was non-functional and added session-level "Always Allow".

---

## 🧠 DeepSeek-V4-Mini Integration — May 6, 2026 (Session 4)

Integrated the latest DeepSeek reasoning capabilities into the Gemma 4 suite.

---

## 🔧 Gemma 4 26B/31B Vision Fix — May 6, 2026 (Session 5)

Resolved a bug where the elite models were behaving as text-only despite having multimodal weights.

---

## 🧠 System Prompt Improvements — May 6, 2026 (Session 6)

Rewrote both system prompts to improve model behavior and ground responses in the current date.

---

## 🔧 Tool Expansion — May 7, 2026

Expanded the agent tool registry to 26 tools, including `git_diff`, `find_file`, `edit_file`, `read_pdf`, `notify`, `system_info`, `sqlite_query`, and `diff_files`.

---

## 📄 PDF Read/Write Tools — May 7, 2026

Implemented first-class PDF read and write capabilities using `fpdf2`.

---

## 🛠️ System Prompt Transparency — May 7, 2026 (Session 2)

Implemented a dedicated "Prompt" tab in the Settings UI to expose the core behavioral instructions of the LLM.

### Files Changed

| File | Change |
|---|---|
| `gemma_bridge.py` | Exposed `AGENT_SYSTEM_PROMPT` via new endpoint; cleaned up imports |
| `gemma-web/server.js` | Added proxy route for system prompt |
| `gemma-web/index.html` | Implemented "Prompt" tab UI and fetch logic |

---

## 🖥️ CLI Tool Wrappers: gh, aws, hf — May 7, 2026 (Session 3)

Added dedicated wrapper tools for `gh`, `aws`, and `huggingface-cli` with per-CLI timeouts and JSON pretty-printing.

### Files Changed

| File | Change |
|---|---|
| `agent_utils.py` | Added `_parse_cli_output` helper; added `_gh_run`, `_aws_run`, `_hf_run`; registered all three |

---

## 🐛 UI Fixes — May 7, 2026 (Session 2, Cont.)

- **Sidebar Restoration**: Fixed a structural HTML error (extra closing `div`) that caused the chat history to disappear.
- **Settings Modal Restoration**: Fixed the "messed up" Settings pane by restoring the full HTML content for the Vitals tab.
- **Verification**: UI integrity confirmed via manual inspection and 100% pass on smoke tests.

---

## 📄 Word & Excel Support — May 8, 2026

Added comprehensive `.docx` and `.xlsx` read/write capabilities to both the agent tool registry and the RAG ingestion pipeline.

### New Module: `office_pipeline.py`

Mirrors `pdf_pipeline.py` in structure and return shape. `chunk_text` and `embed_texts` are reused — no duplication.

| Function | Description |
|---|---|
| `extract_text_from_word(file_bytes)` | Returns `(sections, metadata)` — body text split at heading boundaries; metadata includes comments, tracked changes, footnotes, endnotes, document properties |
| `extract_text_from_excel(file_bytes)` | Returns `(sheets, metadata)` — per-sheet TSV cell dump; metadata includes cell notes, threaded comments, formulas + cached values, embedded OLE objects (macros flagged, never executed) |
| `ingest_office(file_bytes, filename)` | Routes by extension; returns same `{doc_id, filename, page_count, chunks, embeddings}` shape as `ingest_pdf` |
| `write_word_document(path, spec)` | Creates `.docx` from a spec dict — headings, paragraphs (bold/italic/underline), tables with merges, footnotes, endnotes, document properties |
| `write_excel_document(path, spec)` | Creates `.xlsx` from a spec dict — multi-sheet, cell values/formulas, styling (bold/italic/fill/border/alignment/number_format), merges, bar/line/pie charts |

### New Agent Tools

| Tool | Risk | Description |
|---|---|---|
| `read_word(path)` | safe | Extract text, comments, tracked changes, footnotes, and metadata from a `.docx` file |
| `write_word(path, spec)` | risky | Create a Word file from a JSON spec dict |
| `read_excel(path)` | safe | Extract cell values, formulas, notes, and threaded comments from an `.xlsx` file |
| `write_excel(path, spec)` | risky | Create an Excel file from a JSON spec dict |

### Upload Routing

`gemma_bridge.py` `/v1/document` endpoint now routes `.docx` and `.xlsx` to `ingest_office`; all other types continue to `ingest_pdf`.

### UI: Universal Drag & Drop

Removed the file type filter from the upload widget. All file types are now accepted via drag-and-drop and the attach button:
- Images → inline base64 preview (unchanged)
- `.txt` / `.md` → read as text (unchanged)
- **Everything else** → uploaded to `/api/document` and shown as an indexed attachment chip; unsupported types surface an error in the chip rather than being silently ignored

### Files Changed

| File | Change |
|---|---|
| `office_pipeline.py` | **New** — ~540 lines: full Word/Excel extraction and writing |
| `agent_utils.py` | Added 4 tool functions + registrations + system prompt entries |
| `gemma_bridge.py` | Extended upload endpoint with extension-based routing |
| `gemma-web/index.html` | Universal drag-and-drop; removed `accept` filter |
| `requirements.txt` | Added `python-docx`, `openpyxl`, `oletools`, `olefile` |
| `tests/test_office_pipeline.py` | **New** — 25 tests covering extraction, ingestion, tool roundtrips |

---

## 📊 Vitals Dashboard Expansion — May 10, 2026

Transformed the basic Vitals tab into a comprehensive "Command Center" featuring deep system, agent, and pipeline telemetry.

### Architecture

The Vitals pane in the Settings modal now features a sub-tabbed interface. Data is aggregated in the Python Bridge via a new `TelemetryManager` singleton and hardware hooks, then exposed through an expanded `/v1/stats` JSON payload.

### Telemetry Domains

- **System Resources**: Real-time tracking of Process RAM, GPU VRAM, CPU Load, and macOS Thermal Pressure (Nominal to Critical).
- **Agent Analytics**: Tracks total tasks, success rates (excluding in-progress runs), and a "Top Tools" leaderboard. Includes a recent task history table (Status, Duration, ID).
- **Pipeline Health**: Monitors the RAG system, including total document/chunk counts and real-time processing speeds (ingestion and embedding latency).

### Files Changed

| File | Change |
|---|---|
| `agent_utils.py` | **New** — Added `TelemetryManager` singleton for thread-safe session tracking. |
| `agent.py` | Instrumented `react_loop_sse` and `_react_loop_internal` with telemetry hooks. |
| `gemma_bridge.py` | Expanded `/v1/stats` to include hardware (cpu, thermals) and pipeline analytics. |
| `pdf_pipeline.py` | Added embedding latency tracking to `embed_texts` and `retrieve_chunks`. |
| `office_pipeline.py` | Added telemetry parity for Word/Excel ingestion speeds. |
| `gemma-web/index.html` | Redesigned Vitals UI with sub-tabs, robust JS switching logic, and new metric widgets. |
| `tests/` | Added `test_telemetry_manager.py` and `test_bridge_stats.py`. |

### UI Enhancements

- **Sub-Tab Navigation**: Clean, professional toggles for System, Agent, and Pipeline views.
- **Dynamic Widgets**: Color-coded badges for task status and thermal pressure; real-time sorting for top tools.
- **Robust JS**: Refactored tab-switching logic using `classList` and `addEventListener` for better maintainability.

---

## 🎨 Advanced Sidebar & History Revamp — May 10, 2026 (Session 1)

Transformed the chat history from a simple list into a robust management system.

### Features
- **Recents & Starred**: Renamed history to "Recents"; added a dedicated "Starred" section for pinned conversations.
- **Context Menu**: Right-click (or kebab menu) support for Star, Rename, and Delete actions.
- **All Chats Modal**: New full-screen management interface with real-time search and bulk delete capabilities.
- **UI Persistence**: Starred items are mirrored in the Recents list for quick access while remaining fixed in the Starred section.

### Files Changed

| File | Change |
|---|---|
| `gemma-web/index.html` | Implemented Starred section, Context Menu, All Chats modal, and search logic. |

---

## 🧠 Deep Thinking Mode — May 10, 2026

Implemented a multi-stage "Deep Thinking" pipeline that trades inference time for maximum reasoning quality.

### The "Council of Three" Pipeline

When Deep Thinking is enabled, the agent executes a three-stage pre-reasoning process before entering the main ReAct loop:
1. **Diversify (Tree of Thought)**: Generates 3 distinct, high-level strategies (Path A, B, and C) to solve the problem.
2. **Critique (Self-Correction)**: Acts as a critical reviewer to identify logical flaws and edge cases in each path, assigning robustness scores.
3. **Synthesize (Extended CoT)**: Merges the best elements into a single, robust "master reasoning" plan that addresses all identified flaws.

### UI: Thinking Visibility

Enhanced the frontend to provide transparency into the model's internal reasoning process.
- **Multi-Stage Blocks**: Thinking content is rendered in a dedicated, collapsible `<details>` block with a "Deep Thinking Process" summary.
- **Markdown Support**: Internal thoughts are parsed as Markdown for better readability of complex logic.

---

## ☁️ Remote Repository Setup — May 10, 2026 (Session 2)

Connected the local project to a remote GitHub repository to enable collaboration and off-site backup.

### Actions Taken

- **GitHub Integration**: Linked the local repository to `https://github.com/Ic3burG/LocalLLM.git` using the GitHub CLI (`gh`).
- **Clean Sync**: 
  - Updated `.gitignore` to comprehensively exclude Python cache, logs, virtual environments, large model weights, and node modules.
  - Purged ~5,000 tracked files that should have been ignored (primarily `node_modules` and `__pycache__`) from the git index.
  - Established `main` as the default branch.
- **Source of Truth**: Performed a force-push to align the remote repository with the mature local state.

### Files Changed

| File | Change |
|---|---|
| `.gitignore` | **Major Update** — Added comprehensive ignores for Python, Node.js, Logs, and Models. |
| `PROGRESS.md` | Updated with remote setup details. |

---

## 📈 Current Status (as of May 10, 2026)

- **Backend (`agent.py`)**: 
  - New `run_deep_thinking_pipeline` handles sequential inference calls and emits real-time SSE `type: "status"` updates (e.g., "Deep Thinking: Exploring paths...").
  - Final synthesized reasoning is injected into the conversation as a `<thought>` block to guide subsequent tool use.
- **Frontend (`index.html`)**: Added a high-contrast toggle next to the model selector; updated request payload to support the `deep_think` flag.
- **Verification**: 100% test coverage for the pipeline logic, SSE emissions, and integration within the ReAct loop.

### Files Changed

| File | Change |
|---|---|
| `agent.py` | Implemented pipeline logic, SSE status events, and ReAct loop integration |
| `gemma_bridge.py` | Updated `chat_stream` to pass the `deep_think` flag |
| `gemma-web/index.html` | Added Deep Think UI toggle and updated request payload |
| `tests/test_deep_think_support.py` | New — tests for API model changes |
| `tests/test_deep_think_logic.py` | New — tests for the "Council of Three" pipeline logic |
| `tests/test_deep_think_integration.py` | New — tests for end-to-end integration and SSE behavior |

---

## 🎨 FLUX.1-schnell Image Generation — May 10, 2026 (Sessions 3–4)

Full end-to-end on-device image generation, from backend pipeline through agent tool, SSE delivery, and frontend UI.

### Architecture

```
Browser (Image mode) → server.js /api/image/* → gemma_bridge /v1/image/*
                                                     └─ image_pipeline.generate_image()
                                                          └─ mflux FLUX.1-schnell (4-bit, MLX)

Agent ReAct loop → generate_image tool → __image__ JSON marker
                                             └─ react_loop_sse detects marker
                                                  └─ SSE {"type":"image"} → appendImageCard()
```

### Key Technical Decisions

- **mflux (not mlx-stable-diffusion)**: The planned `mlx-stable-diffusion` package doesn't exist on PyPI. `mflux` v0.17.5 provides FLUX.1-schnell via `from mflux.models.flux.variants.txt2img.flux import Flux1`.
- **4 inference steps default**: FLUX.1-schnell is trained to converge in 4 steps; range capped at 1–12.
- **Metal memory management**: `_should_swap()` unloads the text model before loading Flux if it's a large (non-fast) model. `mx.metal.clear_cache()` is also called *after* generation to free Flux weights immediately.
- **`_imageStore` Map**: Base64 image data is stored in a module-level `Map()` keyed by sequential IDs. DOM buttons carry only `data-image-id` — never raw base64 — to prevent XSS and avoid breaking HTML attribute parsers.
- **`__image__` SSE marker**: `_generate_image()` returns `json.dumps({"__image__": True, ...})`. `react_loop_sse` detects this via `json.loads()` + `.get("__image__")` (not a fragile `startswith` check) and emits a `{"type": "image"}` SSE event.
- **`generate_image` registered as `"risky"`**: Requires user confirmation gate — prevents the agent from running costly multi-GB GPU operations autonomously.
- **Size allowlist**: `_parse_size` validates against a fixed set (`512x512`, `768x768`, `512x768`, `768x512`, `1024x1024`) and raises `ValueError` on anything else; the bridge route catches it and returns HTTP 400.

### Files Changed

| File | Change |
|---|---|
| `image_pipeline.py` | **New** — `generate_image()` with threading lock, model swap, size allowlist, style presets, Metal cache clear after generation |
| `gemma_bridge.py` | Added `POST /v1/image/generate` and `GET /v1/image/models`; catches `ValueError` → 400 |
| `gemma-web/server.js` | Added `/api/image/generate` and `/api/image/models` proxy routes |
| `agent_utils.py` | Added `_generate_image` async tool; registered as `"risky"`; added to `AGENT_SYSTEM_PROMPT` |
| `agent.py` | `react_loop_sse` detects `__image__` marker via JSON parse and emits `type: "image"` SSE event |
| `gemma-web/index.html` | Mode pill (Chat / Image); size/steps/style controls; shimmer; image card with copy/download; lightbox with keyboard nav; send button disabled during generation |
| `scripts/download_sd.sh` | **New** — Downloads and smoke-tests FLUX.1-schnell 4-bit weights |
| `requirements.txt` | Added `mflux`; restored full package list |
| `tests/test_image_pipeline.py` | **New** — 15 tests: style, size validation (including invalid/malformed), swap logic, full generate mock |
| `tests/test_agent_tools.py` | Added 2 tests for `_generate_image` tool (success marker, error path) |
| `scripts/smoke_test.py` | Added `test_image_models()` connectivity check |

---

## 🎨 UI Refinements & Integrity Mandates — May 10, 2026 (Session 4)

Refined the interface for maximum stability and established strict architectural mandates to prevent future regressions.

### Interface Polishing
- **Advanced Sidebar Finalized**:
    - **Pinned "All Chats"**: Moved the management button outside the scrollable area; it is now permanently visible at the bottom of the sidebar.
    - **No-Scroll History**: Disabled scrolling for the "Recents" list. The sidebar now dynamically adjusts its visible item count based on browser window height, maintaining a clean, fixed layout.
    - **Renaming**: Simplified "All Chats & Management" to "All Chats".
- **Implicit Agent Mode**: Removed the manual "Chat/Agent" toggle. The model now handles tool-use implicitly, decluttering the main interaction area.
- **Settings Centralization**: Confirmed the removal of the sidebar "Learned Memory" preview; all memory and technical system configurations are now centralized in the Settings modal.

### Feature Integrity (`GEMINI.md`)
Created a project-level **`GEMINI.md`** file that establishes absolute mandates for all AI agents:
- **Zero-Deletion Policy**: Forbidden from removing features without explicit user instruction.
- **Architectural Guardrails**: Strict rules for preserving sidebar structure, memory locations, and reasoning persistence.
- **Audit Requirement**: Mandatory consultation of `PROGRESS.md` before any structural UI/UX changes.

### Files Changed
| File | Change |
|---|---|
| `gemma-web/index.html` | Refined sidebar layout, removed redundant toggles, fixed history persistence. |
| `GEMINI.md` | **New** — Project mandates and feature integrity policy. |
| `agent.py` | Finalized reasoning emission logic and state injection. |

---

## 🔧 Stability & Integrity Fixes — May 10, 2026 (Session 5)

### Smoke Test Dependency Fix
Resolved a `ModuleNotFoundError: requests` that occurred when running the System Integrity check from the Vitals dashboard.

- **Root Cause**: The Node.js server (`server.js`) was hardcoded to use the system `python3` for the `/api/backend/check` endpoint, which lacked the necessary dependencies installed in the project's virtual environment.
- **Fix**: Updated `gemma-web/server.js` to dynamically resolve the Python interpreter path using the project's `.venv` directory.
- **Verification**: Confirmed that the smoke test now executes successfully when triggered via the UI and through manual CLI runs using the venv.

---

## 📈 Current Status (as of May 10, 2026)

- **Backend:** `gemma_bridge.py` on port 9379; `server.js` on port 3001.
- **Models:** E4B, 26B MoE, 31B Dense, Phi-4 Mini (all vision-capable); DeepSeek-V4-Mini (reasoning); FLUX.1-schnell (image generation).
- **Tools:** 37 registered tools.
- **Document Support:** PDF, Word (.docx), Excel (.xlsx) — all indexed for RAG.
- **UI:** Universal drag-and-drop; sub-tabbed "Command Center" Vitals; **Deep Thinking** (Council of Three); **Fixed Sidebar** (Starred/Recents/All Chats); **Implicit Agent Mode**.
- **Integrity:** 115 tests passing; strict feature integrity mandates established in `GEMINI.md`.

