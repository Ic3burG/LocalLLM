# MLX Stable Diffusion — Design Spec
**Date:** 2026-05-10
**Status:** Approved for implementation

---

## Overview

Add on-device image generation to the Gemma4 local LLM tool using MLX Stable Diffusion. Users can generate images directly from the chat UI via a dedicated image mode or through the agent's tool system. All inference runs locally on Apple Silicon via the same MLX stack already used for text models.

---

## Goals

- On-device SD image generation with no cloud dependency
- Two entry points: a direct image mode toggle and an agent `generate_image` tool
- Inline image rendering in chat with Save / Regenerate / Edit prompt actions
- Graceful RAM management via auto model swap — no OOM crashes
- Zero changes to existing inference pipeline for text/vision models

---

## Architecture

Five additive touch points. No existing files are restructured.

### New: `image_pipeline.py`

Owns the full SD lifecycle. Public API:

```python
def generate_image(
    prompt: str,
    size: str = "512x512",          # "512x512" | "768x768" | "512x768"
    steps: int = 20,
    style: str = "default",         # "default" | "photorealistic" | "anime" | "sketch"
    model_id: str = "sd-1.5",
) -> dict:
    # returns {"image_b64": str, "width": int, "height": int,
    #          "steps": int, "elapsed_ms": int}
```

Style presets are implemented as prompt suffix injections (e.g. `"photorealistic"` appends `", photorealistic, 8k, detailed"`).

**Model swap logic:**
1. Call `get_loaded_models()` from `inference_engine`
2. If a large text model is active (gemma-4-*), unload it: `mx.metal.clear_cache()` + release model refs
3. Load SD weights from `mlx_models/sd-1.5/` (downloaded separately via a helper script)
4. Run diffusion loop, return base64 PNG
5. Schedule text model reload in a background thread (non-blocking)

**Fast-mode detection:** If `get_loaded_models()` returns `phi-4-mini` or `deepseek-v4-mini`, skip the swap entirely — both models co-reside comfortably with SD 1.5 (~2 GB).

**Module-level lock:** A `threading.Lock()` prevents concurrent generation requests from racing on model state.

### Modified: `gemma_bridge.py`

Two new routes:

```
POST /v1/image/generate
  Body: {prompt, size?, steps?, style?}
  Response: {image_b64, width, height, steps, elapsed_ms}
  Errors: {error: "insufficient_memory" | "model_not_found" | "timeout"}

GET /v1/image/models
  Response: {available: ["sd-1.5"], downloaded: ["sd-1.5"]}
```

`/v1/image/generate` runs synchronously (not streamed) — generation is a single blocking call. FastAPI's thread pool handles it without blocking the event loop via `asyncio.run_in_executor`.

### Modified: `agent_utils.py`

New async tool:

```python
async def _generate_image(prompt: str, size: str = "512x512", steps: int = 20) -> str:
    # POSTs to /v1/image/generate internally
    # Returns a markdown-style result the agent can describe:
    # "[IMAGE GENERATED: 512x512, 20 steps — displayed in chat]"
```

Registered in `TOOLS` list with name `generate_image`, args `prompt`, `size`, `steps`. The agent system prompt gets a one-line addition describing the tool. When the agent tool returns, `gemma_bridge`'s agent loop detects an `image_b64` key in the tool result, emits a dedicated `image` SSE event to the frontend before continuing the text stream, and the frontend renders it as an image card. The agent's surrounding text renders as normal assistant text.

### Modified: `gemma-web/index.html`

#### Mode pill
A two-button toggle (💬 Chat / 🎨 Image) sits left of the prompt input in the toolbar. Switching to Image mode:
- Changes input placeholder to "Describe an image…"
- Replaces the Send button with a purple Generate button
- Reveals the generation controls row beneath the input

#### Generation controls row (image mode only)
Inline beneath the prompt bar:
- **Size** — select: 512×512 / 768×768 / 512×768
- **Steps** — range slider 10–50, live value display, default 20
- **Style** — select: Default / Photorealistic / Anime / Sketch

#### Warm-up banner
When image mode is first activated with a large text model loaded, a dismissible banner appears: `● Image model ready · text model will reload on switch`. Animated dot indicates the swap is in progress.

#### Image message card
Generated images appear as assistant-side chat bubbles:
- **Thumbnail** — full-width rendered image, hover shows 🔍 Expand hint, click opens lightbox
- **Meta line** — `512×512 · 20 steps · 8.4s · photorealistic`
- **Action bar** — three equal-width buttons: ⬇ Save · 🔄 Regenerate · ✏ Edit prompt

**Save** triggers a browser download from the base64 data URI (client-side only, no route needed).
**Regenerate** re-POSTs to `/v1/image/generate` with the same params.
**Edit prompt** pre-fills the image input with the original prompt and focuses it.

#### Generating state
While generation is in progress, a shimmer placeholder card appears with a spinner and estimated time label ("Warming up image model… ~14s est." on first use, "Generating… ~4s est." on subsequent).

#### Lightbox
Clicking a thumbnail opens a full-screen overlay:
- Left: full-size image (up to viewport)
- Right sidebar: prompt text, metadata, Save / Regenerate / Edit prompt buttons
- Click outside or ✕ to dismiss

#### Agent-triggered images
When the agent calls `generate_image`, the resulting image card renders in the chat stream between the agent's text segments. The agent's surrounding text (e.g. "Here's what I came up with:") renders as normal.

### Modified: `requirements.txt`

```
mlx-stable-diffusion
```

A one-time model download script (`scripts/download_sd.sh`) pulls `sd-1.5` weights into `mlx_models/sd-1.5/`. Not run automatically.

---

## Error Handling

| Error | Cause | UI response |
|---|---|---|
| `insufficient_memory` | OOM during model swap | Inline error card: "Try a smaller size or switch to a lighter text model" |
| `model_not_found` | SD weights not downloaded | Inline error card: "Run `scripts/download_sd.sh` to download the image model" |
| `timeout` | Generation exceeded 120s | Inline error card with Retry button |
| Text model reload failure | Reload thread crashes post-generation | Warning banner: "Text model unloaded. Switch to Chat mode to reload." |

All errors are logged via the existing `logging_config` infrastructure at `ERROR` level with full stack trace.

---

## Testing

| Test file | What it covers |
|---|---|
| `tests/test_image_pipeline.py` | `generate_image()` with mocked MLX SD pipeline; fast-mode detection; model swap logic; style prefix injection |
| `tests/test_agent_tools.py` | Extend existing file with `generate_image` tool call and response parsing |
| `scripts/smoke_test.py` | POST to `/v1/image/generate` with minimal prompt, assert base64 PNG in response, assert elapsed_ms present |

Mocking pattern follows existing tests: patch `mlx_stable_diffusion` at the module boundary, return a 1×1 white PNG as base64.

---

## Out of Scope

- SDXL or FLUX models (can be added later as model options in the size/style controls)
- Negative prompts (foundation is laid — `generate_image` can accept `negative_prompt` in a future iteration)
- Image-to-image / inpainting
- Persistent gallery panel (images exist in chat history only)
- Prompt history / favorites
