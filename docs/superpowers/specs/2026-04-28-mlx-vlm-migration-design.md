# mlx_vlm Migration Design

**Date:** 2026-04-28  
**Approach:** Option B — Full replacement (no LiteRT fallback)

---

## Goal

Replace the current two-engine backend (LiteRT for E4B, mlx_lm for 26B/31B) with a single unified `mlx_vlm` stack that handles all three models — text and vision — through one code path.

## Architecture

All inference goes through `handle_mlx_vlm_request`. The asyncio event loop stays free via the existing `ThreadPoolExecutor(max_workers=1)`. Model instances are cached after first load. The rest of the server (chat endpoint, agent loop, memory, RAG, title generation) is unchanged.

```
Browser → server.js (3001) → gemma_bridge.py (9379)
                               ├─ run_inference()          ← simplified, always mlx_vlm
                               │    └─ handle_mlx_vlm_request()
                               │         └─ get_mlx_vlm_model()  ← (model, processor) cache
                               └─ /v1/agent/*             ← unchanged
```

## What Gets Removed from `gemma_bridge.py`

| Symbol | Reason |
|---|---|
| `import litert_lm` / `from litert_lm import Backend` | LiteRT gone |
| `litert_engines: dict` | Replaced by `_vlm_cache` |
| `get_litert_engine(model_id)` | Replaced by `get_mlx_vlm_model` |
| `process_multimodal_content(content, temp_files)` | mlx_vlm handles images directly via PIL |
| `handle_litert_request(model_id, messages)` | Replaced by unified handler |
| `mlx_lm_module` global + lazy import | Replaced by mlx_vlm static import |
| `mlx_models_cache` | Renamed to `_vlm_cache` |
| `get_mlx_model(model_id)` | Replaced by `get_mlx_vlm_model` |
| `handle_mlx_request(model_id, messages)` | Replaced by unified handler |
| LiteRT path logic in `list_models` | Only `MLX_MODELS_DIR` remains |
| `MODELS_BASE_DIR` | No longer needed |

## What Gets Added

### `get_mlx_vlm_model(model_id) -> (model, processor)`

Resolves `model_id` to a directory in `mlx_models/` via `_MODEL_DIR_MAP`, then calls `mlx_vlm.load(path)`. Caches the result in `_vlm_cache`.

```python
_MODEL_DIR_MAP = {
    "gemma4-e4b":     "gemma-3-4b-it-4bit",
    "gemma4-26b-mlx": "gemma-4-26b-it-4bit",
    "gemma4-31b-mlx": "gemma-4-31b-it-4bit",
}
```

If `model_id` is not in the map, the directory name falls back to `model_id` directly (forward-compat for future models).

### `handle_mlx_vlm_request(model_id, messages) -> dict`

Single sync function (runs in thread executor). Steps:
1. Call `get_mlx_vlm_model(model_id)` → `(model, processor)`
2. Walk messages; build a clean list (text-only for non-final messages)
3. For the final message, extract:
   - text parts → assembled string
   - first `image_url` item (base64 `data:image/...`) → decode to `PIL.Image`
4. Format prompt string (exact call — `processor.apply_chat_template` or `mlx_vlm.utils` helper — confirmed against installed version during implementation)
5. Call `mlx_vlm.generate(model, processor, prompt, image=pil_image_or_none, max_tokens=2048, verbose=False)`
6. Return `format_openai_response(model_id, generated_text)`

No temp files. Image lives in memory as a PIL object for the duration of the call.

### `run_inference` (simplified)

```python
async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _inference_executor, handle_mlx_vlm_request, model_id, messages
    )
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"run_inference: unexpected response structure: {e}") from e
```

Routing condition (`is_mlx` check) is removed entirely.

## Model Paths

| model_id | Directory | Status |
|---|---|---|
| `gemma4-e4b` | `mlx_models/gemma-3-4b-it-4bit` | **Needs download** — currently only exists as LiteRT format |
| `gemma4-26b-mlx` | `mlx_models/gemma-4-26b-it-4bit` | Already present, likely compatible |
| `gemma4-31b-mlx` | `mlx_models/gemma-4-31b-it-4bit` | Already present, likely compatible |

E4B download during implementation:
```bash
python -m mlx_lm.convert --hf-path google/gemma-3-4b-it -q --q-bits 4 \
    --mlx-path mlx_models/gemma-3-4b-it-4bit
```
Or pull directly from Hub if mlx-community has a pre-quantised version:
```bash
huggingface-cli download mlx-community/gemma-3-4b-it-4bit \
    --local-dir mlx_models/gemma-3-4b-it-4bit
```

## Image Handling

**Before (LiteRT):** base64 → temp file on disk → `{"type": "image", "path": tmp.name}` → LiteRT reads file → temp file deleted in `finally`.

**After (mlx_vlm):** base64 → `PIL.Image.open(BytesIO(decoded))` → passed as `image=` kwarg to `mlx_vlm.generate()`. No disk I/O, no cleanup needed.

## `list_models` Endpoint

Remove the LiteRT scan block. Keep only the `MLX_MODELS_DIR` scan. Update `provider` field to `"mlx_vlm"`.

## `requirements.txt` Changes

- **Remove:** `litert-lm` (if listed)
- **Remove:** `mlx-lm` (mlx_vlm is a superset)
- **Add:** `mlx-vlm`
- **Add:** `Pillow` (for PIL.Image; likely already present transitively, but explicit is safer)

## Test Changes (`tests/test_agent.py`)

The two inference routing tests currently mock `handle_litert_request` and `handle_mlx_request`. After migration:
- Both are replaced by a single mock of `handle_mlx_vlm_request`
- Test for "routes litert for default model" → "routes mlx_vlm for E4B model"
- Test for "routes mlx for mlx model" → "routes mlx_vlm for 26B model"
- The malformed-response test is unchanged (still patches at `run_inference` level via `handle_mlx_vlm_request`)

## Error Handling

- `FileNotFoundError` if model directory missing → raised from `get_mlx_vlm_model`, propagates to 500 response
- Invalid/corrupt base64 image → caught in handler, logged, image treated as `None` (graceful degradation)
- `mlx_vlm.generate` exception → propagates as 500

## Out of Scope

- Streaming token-by-token output (mlx_vlm supports it but not wired up today — unchanged)
- Multi-image support (only first image used, same as current LiteRT behaviour)
- Fine-tuning or quantisation (models used as-is)
