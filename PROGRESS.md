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
  - **Gemma 4 26B A4B (MoE):** Installed via MLX for high-level reasoning with MoE efficiency.
  - **Gemma 4 31B Dense:** Installed via MLX as the "Elite" frontier model for maximum intelligence.

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

## 🐛 Bug Fixes & Multimodal Investigation — April 22, 2026 (Session 2)

### Initial Code Bugs (Fixed First)
- **Fixed `<|image|>` double-token injection:** The bridge was manually injecting a `<|image|>` token into the prompt text, but the LiteRT engine's Jinja chat template *also* inserts one for every `{"type": "image"}` content item. The result was 2 tokens for 1 image, which the engine rejected with `INVALID_ARGUMENT: Provided less images than expected`. Removed the manual injection and let the engine handle its own template.
- **Fixed MLX models silently dropping images:** The `handle_mlx_request` path was stripping all image content without any error or warning, causing multimodal requests to the 26B/31B models to silently produce text-only responses. Now raises a descriptive `ValueError` directing the user to use the LiteRT model or switch to `mlx_vlm`.
- **Fixed `list_models` copy-paste bug:** The MLX model directory scan checked `MODELS_BASE_DIR` instead of `MLX_MODELS_DIR`, so MLX models never appeared in the `/v1/models` endpoint response.

### Root Cause Investigation: Segfault on Image Inference
After fixing the above, every image request still caused the Python bridge process to crash (exit code 139 — segfault), with the LiteRT C++ engine dying silently mid-generation. Investigation steps taken:
- Confirmed both servers were running via `lsof`.
- Isolated the crash to the LiteRT engine by testing the bridge and proxy independently.
- Read the `litert_lm` Python interfaces source to confirm `send_message()` signature: `str | Mapping`, **not** a list — fixed a secondary bug where the content list was being passed directly instead of the wrapping message dict.
- Ran direct Python tests to capture the C++ log output, revealing `max_num_images: 0` in the engine's runtime config and a crash immediately after `<|turn>model` (start of decode).
- Confirmed via exit code 139 (SIGSEGV) that the crash was in C++, not Python — no Python traceback was ever produced.

### Root Cause Found & Fixed
- **`vision_backend=Backend.CPU` was not being set on the engine.** Without this parameter, LiteRT initialises the engine with `max_num_images: 0` — the vision decode path is never wired up, so image embeddings have no tensor slots in the decode graph and cause a segfault. The Gemma 4 E4B model fully supports images; the runtime just needed to be told to activate the vision path.
- **Fix:** Added `vision_backend=Backend.CPU` to `litert_lm.Engine(model_path, vision_backend=Backend.CPU)` in `get_litert_engine()` and imported `Backend` from `litert_lm`.
- **Result:** Image inference now works end-to-end. Both the bridge (`localhost:9379`) and the Node proxy (`localhost:3001`) return correct vision responses.

### Summary of All Changes to `gemma_bridge.py`
| Location | Change |
|---|---|
| `get_litert_engine()` | Added `vision_backend=Backend.CPU` to Engine constructor — root cause fix |
| `handle_litert_request()` | `send_message(last_msg)` passes full message dict (not bare content list) |
| `process_multimodal_content()` | Removed manual `<|image|>` token injection — engine template handles it |
| `handle_mlx_request()` | Raises `ValueError` on image input instead of silently dropping images |
| `list_models()` | Fixed MLX scan to check `MLX_MODELS_DIR` not `MODELS_BASE_DIR` |

## 📈 Current Status (as of April 22, 2026)

- **Backend:** `server.js` (Express) running on port 3001.
- **Bridge:** `gemma_bridge.py` (FastAPI/MLX/LiteRT) running on port 9379.
- **Storage:** Models stored in `~/.litert-lm/models` and `./mlx_models`.
- **Formatting:** All files formatted with Prettier for consistency.

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

### Bug Fixes

- **Circular import (`__main__`):** `agent.py` originally imported `run_inference` at module top level. When `gemma_bridge.py` is run as a script it registers as `__main__` (not `gemma_bridge`) in `sys.modules`, causing `agent.py`'s import to re-execute the file and hit the circular dependency. Fixed by making the import lazy (inside the wrapper function).
- **SSE sentinel not guaranteed:** `_react_loop_sse` could hang SSE connections if `run_inference` threw. Wrapped the loop in `try/finally` to always send the `None` sentinel.
- **Queue memory leak:** SSE and confirm queues were never cleaned up after a task finished. Added `finally` cleanup in `event_gen` to pop both queues after the stream closes.

## 📈 Current Status (as of April 27, 2026)

- **Backend:** `gemma_bridge.py` (FastAPI/MLX/LiteRT + agent router) on port 9379, managed by `com.gemini.litert` launchd agent — auto-starts on login and restarts on crash.
- **Proxy:** `server.js` (Express) on port 3001, managed by `com.gemini.gemma-bridge` launchd agent.
- **Agent:** Available via the `🤖 Agent` toggle in the UI. Send any prompt to kick off a ReAct loop.
- **Scheduler:** In-app tasks survive restarts via `scheduler_tasks.json`; system cron entries tagged `# gemma:<name>`.

---

## 🛠 Subagent & Title Generation Fixes — April 27, 2026 (Session 2)

### Bug Fixes
- **Fixed `strip_thinking` logic:** The regular expressions for stripping internal model thoughts were failing to catch Gemma 4's specific channel markers (`<|channel>thought\n...<channel|>`). Updated the logic to be more robust and cover multiple tag variations.
- **Title Generation Reliability:** Resolved an issue where chat titles were either remaining generic ("New Chat") or containing raw model thoughts.
- **Clean Memory Updates:** The improved stripping logic ensures that `USER_MEMORY.md` is updated with clean text, preventing internal model reasoning from leaking into the long-term knowledge base.

### Refactoring
- **Consolidated Inference:** Refactored `generate_title` and `update_memory_task` to use the shared `run_inference` helper. This ensures that all subagents benefit from the same routing logic, error handling, and formatting standards as the main chat and agent loops.

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

### Bugs Discovered & Fixed

- **mlx GPU stream error (`RuntimeError: There is no Stream(gpu, 1) in current thread`):** mlx creates `generation_stream` at import time, so `mlx_vlm` must be imported on — and all inference must run on — the same OS thread. `ThreadPoolExecutor` violated this. Fixed by replacing the executor with a single persistent daemon thread backed by `queue.Queue`.
- **`break` outside `if` block:** In the image extraction loop, `break` fired on the first `image_url` item regardless of type, silently dropping non-base64 images. Moved inside the `data:image` branch.
- **`list_models` returning directory names:** Reversed `_MODEL_DIR_MAP` at response time so canonical IDs are returned.
- **Thread startup race:** `_mlx_vlm_load` was `None` until the worker finished importing mlx_vlm. Added `threading.Event` so `get_mlx_vlm_model` waits (up to 30s) before trying to call it.
- **Silent chat template fallback:** Bare `except Exception` hid the original error before the tokenizer fallback. Added `logger.warning` to surface it.

### Cleanup

- Deleted all unused LiteRT model files (~9.3 GB reclaimed):
  - `~/.litert-lm/models/gemma4-e4b` (5.7 GB)
  - `~/.litert-lm/models/phi4-mini` (3.6 GB)
  - `~/.litert-lm/models/gemma4-26b` (empty)

### Files Changed

| File | Change |
|---|---|
| `gemma_bridge.py` | Full engine replacement — removed LiteRT/mlx_lm, added mlx_vlm worker thread architecture |
| `requirements.txt` | Added `mlx-vlm`, `Pillow`; removed `mlx-lm` direct dependency |
| `tests/test_agent.py` | Updated inference routing tests to mock `handle_mlx_vlm_request`; added `mlx_vlm` to stub list |
| `docs/superpowers/specs/` | New: mlx_vlm migration design spec |
| `docs/superpowers/plans/` | New: mlx_vlm migration implementation plan |

## 📈 Current Status (as of April 28, 2026)

- **Backend:** `gemma_bridge.py` (FastAPI + mlx_vlm + agent router) on port 9379, managed by `com.gemini.litert` launchd agent.
- **Proxy:** `server.js` (Express) on port 3001, managed by `com.gemini.gemma-bridge` launchd agent.
- **Models:** All three served via mlx_vlm from `mlx_models/`:
  - `gemma4-e4b` → `gemma-3-4b-it-4bit` (3.2 GB, text + vision)
  - `gemma4-26b-mlx` → `gemma-4-26b-it-4bit` (15 GB, text + vision)
  - `gemma4-31b-mlx` → `gemma-4-31b-it-4bit` (17 GB, text + vision)
- **Agent:** Unchanged — ReAct loop, SSE streaming, confirmation gate, scheduler all intact.
- **Tests:** 26 passing.

---

## 🛠 Advanced Tool Access: Web Research — April 28, 2026 (Session 2)

Implemented the first phase of the Advanced Tool Access plan, adding web research capabilities to the agent.

### New Tools

- **_google_search(query)**: Uses `googlesearch-python` to retrieve the top 5 URLs for a given query.
- **_web_fetch(url)**: Uses `requests` and `BeautifulSoup` to fetch and clean the content of a webpage (removing scripts/styles and limiting to 5000 chars).

### Testing

- Created `tests/test_agent_tools.py` with 100% coverage for the new tools.
- Used `unittest.mock` to ensure no actual network calls are made during tests.
- Verified both tools handle errors gracefully (e.g., connection issues).

### Files Changed

| File | Change |
|---|---|
| `agent.py` | Implemented `_google_search` and `_web_fetch` internal methods |
| `tests/test_agent_tools.py` | New — tests for the new web research tools |
| `requirements.txt` | (Already contained `googlesearch-python`, `requests`, `beautifulsoup4`) |
