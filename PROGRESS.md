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

## 📈 Current Status

- **Backend:** `server.js` (Express) running on port 3001.
- **Bridge:** `gemma_bridge.py` (FastAPI/MLX/LiteRT) running on port 9379.
- **Storage:** Models stored in `~/.litert-lm/models` and `./mlx_models`.
- **Formatting:** All files formatted with Prettier for consistency.
