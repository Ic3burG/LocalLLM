# mlx_vlm Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-engine backend (LiteRT + mlx_lm) with a single `mlx_vlm` stack that handles all three models — text and vision — through one code path.

**Architecture:** `handle_mlx_vlm_request` is the single sync inference function; it loads `(model, processor)` via `mlx_vlm.load()`, renders the chat template, decodes any base64 image to a PIL object, and calls `mlx_vlm.generate()`. `run_inference` is simplified to always call this one function via the existing `ThreadPoolExecutor`. The agent loop, memory, RAG, and title endpoints are unchanged.

**Tech Stack:** Python 3.11+, mlx-vlm, Pillow, FastAPI, APScheduler, pytest-asyncio

---

## File Map

| File                  | Change                                                                                                                           |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `gemma_bridge.py`     | Remove LiteRT + mlx_lm code; add `get_mlx_vlm_model`, `handle_mlx_vlm_request`; simplify `run_inference`; simplify `list_models` |
| `requirements.txt`    | Add `mlx-vlm`, `Pillow`; remove `mlx-lm` if present                                                                              |
| `tests/test_agent.py` | Update two inference-routing tests to mock `handle_mlx_vlm_request`                                                              |

---

## Task 1: Install mlx_vlm and download E4B model

**Files:**

- Modify: `requirements.txt`

- [ ] **Step 1: Install mlx_vlm in the project venv**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
.venv/bin/pip install -U mlx-vlm Pillow
```

Expected: packages install without error; `mlx_vlm` importable.

- [ ] **Step 2: Verify mlx_vlm API**

```bash
.venv/bin/python -c "
from mlx_vlm import load, generate
from mlx_vlm.utils import load_image
print('mlx_vlm API OK')
# Print generate signature so we know the exact kwargs
import inspect
print(inspect.signature(generate))
"
```

Expected: prints `mlx_vlm API OK` and the `generate` signature. Note down the exact parameter names — they're needed in Task 3.

- [ ] **Step 3: Download E4B model from mlx-community**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
.venv/bin/python -m huggingface_hub download mlx-community/gemma-3-4b-it-4bit \
    --local-dir mlx_models/gemma-3-4b-it-4bit \
    --local-dir-use-symlinks False
```

If `huggingface_hub` CLI is unavailable, use:

```bash
.venv/bin/pip install huggingface_hub
.venv/bin/huggingface-cli download mlx-community/gemma-3-4b-it-4bit \
    --local-dir mlx_models/gemma-3-4b-it-4bit
```

Expected: `mlx_models/gemma-3-4b-it-4bit/` directory created with model weights (~2.5 GB).

- [ ] **Step 4: Verify model loads**

```bash
.venv/bin/python -c "
from mlx_vlm import load
model, processor = load('mlx_models/gemma-3-4b-it-4bit')
print('E4B loaded OK, processor type:', type(processor).__name__)
"
```

Expected: prints `E4B loaded OK` without error (first load may take 30-60s).

- [ ] **Step 5: Update requirements.txt**

Replace the full contents of `requirements.txt` with:

```
pdfplumber
sentence-transformers
numpy
python-multipart
apscheduler
mlx-vlm
Pillow
```

(Remove `mlx-lm` if it appears — mlx_vlm is a superset.)

- [ ] **Step 6: Commit**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
git add requirements.txt
git commit -m "chore: add mlx-vlm and Pillow to requirements"
```

---

## Task 2: Update inference routing tests first (TDD)

**Files:**

- Modify: `tests/test_agent.py` (lines 38–62)

The two routing tests currently reference `handle_litert_request` and `handle_mlx_request`. Updating them _before_ changing `gemma_bridge.py` means they'll fail first (red), then pass after the implementation (green).

- [ ] **Step 1: Open tests/test_agent.py and replace the two routing tests**

Find and replace lines 38–62 with:

```python
@pytest.mark.asyncio
async def test_run_inference_routes_mlx_vlm_for_e4b():
    with patch.object(gemma_bridge, "handle_mlx_vlm_request", return_value=FAKE_RESPONSE) as mock_vlm:
        result = await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-e4b")
        assert result == "hello"
        mock_vlm.assert_called_once()


@pytest.mark.asyncio
async def test_run_inference_routes_mlx_vlm_for_26b():
    with patch.object(gemma_bridge, "handle_mlx_vlm_request", return_value=FAKE_RESPONSE) as mock_vlm:
        result = await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-26b-mlx")
        assert result == "hello"
        mock_vlm.assert_called_once()


@pytest.mark.asyncio
async def test_run_inference_raises_on_malformed_response():
    with patch.object(gemma_bridge, "handle_mlx_vlm_request", return_value={}):
        with pytest.raises(RuntimeError, match="unexpected response structure"):
            await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-e4b")
```

Note: the old tests also used `mock_litert.assert_not_called()` / `mock_mlx.assert_not_called()` — those cross-checks are gone because there's now only one handler.

- [ ] **Step 2: Run the updated tests to confirm they FAIL (red)**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
.venv/bin/pytest tests/test_agent.py::test_run_inference_routes_mlx_vlm_for_e4b \
                 tests/test_agent.py::test_run_inference_routes_mlx_vlm_for_26b \
                 tests/test_agent.py::test_run_inference_raises_on_malformed_response \
                 -v
```

Expected: all three FAIL with `AttributeError: <module 'gemma_bridge'> does not have the attribute 'handle_mlx_vlm_request'`

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_agent.py
git commit -m "test: update inference routing tests for mlx_vlm (red)"
```

---

## Task 3: Replace LiteRT + mlx_lm with mlx_vlm in gemma_bridge.py

**Files:**

- Modify: `gemma_bridge.py`

This is the core migration. Work top-to-bottom through the file.

- [ ] **Step 1: Replace the import block at the top of gemma_bridge.py**

Remove these lines:

```python
import litert_lm
from litert_lm import Backend
```

Add at the top (after existing imports):

```python
from io import BytesIO
from PIL import Image
from mlx_vlm import load as mlx_vlm_load, generate as mlx_vlm_generate
```

- [ ] **Step 2: Replace the model cache globals**

Remove:

```python
# MLX-LM is loaded only when needed to save memory
mlx_lm_module = None
```

and:

```python
# Model cache
litert_engines = {}
mlx_models_cache = {}
```

Add:

```python
# Model cache: model_id -> (model, processor)
_vlm_cache: dict = {}

_MODEL_DIR_MAP = {
    "gemma4-e4b":     "gemma-3-4b-it-4bit",
    "gemma4-26b-mlx": "gemma-4-26b-it-4bit",
    "gemma4-31b-mlx": "gemma-4-31b-it-4bit",
}
```

Remove the `MODELS_BASE_DIR` line:

```python
MODELS_BASE_DIR = os.path.expanduser("~/.litert-lm/models")
```

- [ ] **Step 3: Delete get_litert_engine, get_mlx_model, process_multimodal_content, handle_litert_request, handle_mlx_request**

Remove all five of these functions entirely (lines ~55–440 in the current file). They are:

- `def get_litert_engine(model_id):`
- `def get_mlx_model(model_id):`
- `def process_multimodal_content(content, current_temp_files):`
- `def handle_litert_request(model_id, messages):`
- `def handle_mlx_request(model_id, messages):`

- [ ] **Step 4: Add get_mlx_vlm_model and handle_mlx_vlm_request**

Insert the following two functions after the `_MODEL_DIR_MAP` dict (before `get_user_memory`):

```python
def get_mlx_vlm_model(model_id: str):
    if model_id in _vlm_cache:
        return _vlm_cache[model_id]
    dir_name = _MODEL_DIR_MAP.get(model_id, model_id)
    model_path = os.path.join(MLX_MODELS_DIR, dir_name)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"mlx_vlm model directory not found: {model_path}")
    logger.info(f"Loading mlx_vlm model {model_id} from {model_path}...")
    model, processor = mlx_vlm_load(model_path)
    _vlm_cache[model_id] = (model, processor)
    return model, processor


def handle_mlx_vlm_request(model_id: str, messages: list) -> dict:
    model, processor = get_mlx_vlm_model(model_id)

    # Build clean message list; only the final message may carry an image
    clean_messages = []
    pil_image = None

    for i, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        is_last = i == len(messages) - 1

        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            text = " ".join(text_parts)
            if is_last:
                for c in content:
                    if c.get("type") == "image_url" and pil_image is None:
                        url = c.get("image_url", {}).get("url", "")
                        if url.startswith("data:image"):
                            try:
                                _, encoded = url.split(",", 1)
                                pil_image = Image.open(BytesIO(base64.b64decode(encoded)))
                                logger.info("Decoded base64 image for mlx_vlm")
                            except Exception as e:
                                logger.error(f"Failed to decode image, continuing text-only: {e}")
            clean_messages.append({"role": role, "content": text})
        else:
            clean_messages.append({"role": role, "content": content or ""})

    # Render the prompt string using the processor's chat template
    has_image = pil_image is not None
    try:
        prompt = processor.apply_chat_template(
            clean_messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        # Fallback: some processors expose tokenizer directly
        prompt = processor.tokenizer.apply_chat_template(
            clean_messages, tokenize=False, add_generation_prompt=True
        )

    logger.info(f"Starting mlx_vlm inference for {model_id} (image={'yes' if has_image else 'no'})...")
    generated = mlx_vlm_generate(
        model, processor, prompt,
        image=pil_image,
        max_tokens=2048,
        verbose=False,
    )
    # mlx_vlm.generate returns a string
    return format_openai_response(model_id, generated)
```

- [ ] **Step 5: Simplify run_inference**

Replace the existing `run_inference` function body with:

```python
async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Shared inference helper — runs blocking inference in a thread pool so the
    asyncio event loop stays responsive during agent loops and concurrent chat."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _inference_executor, handle_mlx_vlm_request, model_id, messages
    )
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"run_inference: unexpected response structure: {e}") from e
```

- [ ] **Step 6: Simplify list_models endpoint**

Replace the `list_models` function body with:

```python
@app.get("/v1/models")
async def list_models():
    available = []
    if os.path.exists(MLX_MODELS_DIR):
        for d in os.listdir(MLX_MODELS_DIR):
            if os.path.isdir(os.path.join(MLX_MODELS_DIR, d)):
                available.append({"id": d, "object": "model", "provider": "mlx_vlm"})
    return {"data": available}
```

- [ ] **Step 7: Verify the file has no remaining references to old symbols**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
grep -n "litert\|mlx_lm\|handle_litert\|handle_mlx_request\|get_litert\|get_mlx_model\|mlx_models_cache\|litert_engines\|MODELS_BASE_DIR\|process_multimodal" gemma_bridge.py
```

Expected: no output. If any lines appear, remove them.

- [ ] **Step 8: Commit**

```bash
git add gemma_bridge.py
git commit -m "feat: replace LiteRT+mlx_lm with unified mlx_vlm handler"
```

---

## Task 4: Make tests green

**Files:**

- Modify: `tests/test_agent.py` (stub section at top)

The test file stubs out heavy dependencies at import time. `litert_lm` is in the stub list but no longer imported. The stubs for `litert_lm` are harmless but we should add `mlx_vlm` to avoid import errors if it's not installed in the test environment.

- [ ] **Step 1: Update the stub list in tests/test_agent.py**

Find the `_make_stub(...)` call near the top and replace it with:

```python
_make_stub(
    "fastapi",
    "fastapi.responses",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "litert_lm",   # kept so old import paths don't error on reload
    "mlx_vlm",
    "PIL",
    "PIL.Image",
    "uvicorn",
    "pdf_pipeline",
)
```

- [ ] **Step 2: Run the full test suite**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
.venv/bin/pytest tests/test_agent.py -v
```

Expected: all 26 tests PASS (the 3 updated routing tests now pass; the other 23 are unchanged).

If any test fails due to `AttributeError` on a removed symbol, check whether the reload at line 32 (`importlib.reload(gemma_bridge)`) is picking up stale module state and update the stub list accordingly.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent.py
git commit -m "test: update stubs for mlx_vlm; all 26 tests green"
```

---

## Task 5: Smoke test end-to-end

**Files:** None (runtime verification only)

- [ ] **Step 1: Start the backend**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
.venv/bin/python gemma_bridge.py &
sleep 5
```

- [ ] **Step 2: Text-only inference via E4B**

```bash
curl -s -X POST http://localhost:9379/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemma4-e4b","messages":[{"role":"user","content":"Say hello in one word."}]}' \
  | python3 -m json.tool
```

Expected: JSON response with `choices[0].message.content` containing a single word greeting.

- [ ] **Step 3: Text-only inference via 26B**

```bash
curl -s -X POST http://localhost:9379/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemma4-26b-mlx","messages":[{"role":"user","content":"Say hello in one word."}]}' \
  | python3 -m json.tool
```

Expected: same structure as Step 2 (26B will be slower — allow 30–120s first call while model loads).

- [ ] **Step 4: Verify /v1/models lists mlx_vlm provider**

```bash
curl -s http://localhost:9379/v1/models | python3 -m json.tool
```

Expected: `provider` field is `"mlx_vlm"` for all listed models; no LiteRT entries.

- [ ] **Step 5: Stop the background server**

```bash
kill %1 2>/dev/null || pkill -f "gemma_bridge.py"
```

- [ ] **Step 6: Commit smoke test notes (optional)**

If you discovered any issues and fixed them during smoke testing, commit those fixes now:

```bash
git add -p
git commit -m "fix: smoke test corrections post mlx_vlm migration"
```

---

## Task 6: Restart the managed service

**Files:** None (launchd management)

The macOS launchd agent (`com.gemini.litert`) manages the production process. It needs to be restarted to pick up the updated `gemma_bridge.py`.

- [ ] **Step 1: Unload and reload the launchd agent**

```bash
launchctl unload ~/Library/LaunchAgents/com.gemini.litert.plist
launchctl load  ~/Library/LaunchAgents/com.gemini.litert.plist
```

- [ ] **Step 2: Confirm the process is running**

```bash
sleep 5
curl -s http://localhost:9379/v1/models | python3 -m json.tool
```

Expected: models list returns with `"provider": "mlx_vlm"`.

- [ ] **Step 3: Check logs for errors**

```bash
tail -30 /tmp/gemma-bridge.log 2>/dev/null || \
  log show --predicate 'process == "python3"' --last 2m | grep -i "gemma\|error\|mlx"
```

Expected: no `ImportError`, `ModuleNotFoundError`, or `FileNotFoundError` in the log.
