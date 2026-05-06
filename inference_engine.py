import threading
import queue
import logging
import asyncio
import os
import base64
import tempfile
import time
import uuid
from agent_utils import log_audit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Single dedicated inference thread
# ---------------------------------------------------------------------------
# mlx GPU streams are thread-local objects.  mlx_vlm creates its
# `generation_stream` at module-import time, so it must be imported — and all
# subsequent inference calls must run — on the same OS thread.  We achieve
# this with a single persistent worker thread backed by a job queue.

_inference_queue: queue.Queue = queue.Queue()
_inference_ready = threading.Event()
_mlx_vlm_load = None
_mlx_vlm_generate = None
_mlx_vlm_stream_generate = None
_mlx_lm_load = None
_mlx_lm_stream_generate = None

# Models that mlx_vlm doesn't support — routed through mlx_lm instead.
_TEXT_ONLY_MODELS = {"phi4-mini"}

# Watchdog state
_last_inference_activity = time.monotonic()
_stop_inference = threading.Event()
_is_job_running = False
_current_model_id = None

def _inference_worker():
    """Long-lived thread that owns all mlx GPU state."""
    global _mlx_vlm_load, _mlx_vlm_generate, _mlx_vlm_stream_generate, _mlx_lm_load, _mlx_lm_stream_generate, _is_job_running, _last_inference_activity, _current_model_id
    logger.info("Starting MLX inference worker thread...")
    try:
        from mlx_vlm import load as _load, generate as _gen, stream_generate as _stream_gen
        _mlx_vlm_load = _load
        _mlx_vlm_generate = _gen
        _mlx_vlm_stream_generate = _stream_gen
    except Exception as e:
        logger.error(f"Failed to import mlx_vlm: {e}", exc_info=True)

    try:
        from mlx_lm import load as _lm_load, stream_generate as _lm_stream_gen
        _mlx_lm_load = _lm_load
        _mlx_lm_stream_generate = _lm_stream_gen
    except Exception as e:
        logger.error(f"Failed to import mlx_lm: {e}", exc_info=True)

    _inference_ready.set()
    logger.info("MLX inference worker thread ready.")

    while True:
        fn, args, future = _inference_queue.get()
        _is_job_running = True
        _last_inference_activity = time.monotonic()
        _stop_inference.clear()
        if args and isinstance(args[0], str):
            _current_model_id = args[0]
        else:
            _current_model_id = "unknown"

        try:
            result = fn(*args)
            future.get_loop().call_soon_threadsafe(future.set_result, result)
        except Exception as exc:
            future.get_loop().call_soon_threadsafe(future.set_exception, exc)
        finally:
            _is_job_running = False
            _current_model_id = None
            _stop_inference.clear() # Reset stop event for next job

# Start the worker thread exactly once
_worker_thread = threading.Thread(target=_inference_worker, daemon=True, name="mlx-inference-worker")
_worker_thread.start()

def _watchdog_loop():
    """Monitors inference activity and kills hung jobs."""
    global _last_inference_activity, _stop_inference, _is_job_running, _current_model_id
    logger.info("Starting inference watchdog loop...")
    while True:
        time.sleep(10)
        if _is_job_running:
            idle_time = time.monotonic() - _last_inference_activity
            if idle_time > 180:
                model_id = _current_model_id or "unknown"
                logger.error(f"Inference watchdog: job hung for {int(idle_time)}s. Triggering stop.")
                log_audit(f"WATCHDOG: Interrupted stalled inference for {model_id}")
                _stop_inference.set()

# Start the watchdog thread
_watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True, name="inference-watchdog")
_watchdog_thread.start()

def is_model_loaded(model_id: str) -> bool:
    """Check whether a model is currently in cache. Safe to call from any thread."""
    if model_id in _TEXT_ONLY_MODELS:
        return model_id in _lm_cache
    return model_id in _vlm_cache


async def run_in_inference_thread(fn, *args):
    """Submit *fn(*args)* to the inference thread and await the result."""
    if not _inference_ready.is_set():
        loop = asyncio.get_running_loop()
        is_ready = await loop.run_in_executor(None, lambda: _inference_ready.wait(timeout=60))
        if not is_ready:
            raise RuntimeError("Inference worker failed to start within 60 seconds")

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _inference_queue.put((fn, args, future))
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=900)
    except asyncio.TimeoutError:
        raise RuntimeError("Inference timed out after 900 seconds")

# ---------------------------------------------------------------------------
# MLX VLM Inference Logic
# ---------------------------------------------------------------------------

MLX_MODELS_DIR = os.path.join(os.getcwd(), "mlx_models")

# Model caches — only accessed from the single inference thread, no lock needed.
_vlm_cache: dict = {}   # model_id -> (model, processor)  for mlx_vlm
_lm_cache: dict = {}    # model_id -> (model, tokenizer)  for mlx_lm

_MODEL_DIR_MAP = {
    "gemma4-e4b":     "gemma-4-e4b-it-4bit",
    "gemma4-26b-mlx": "gemma-4-26b-a4b-it-4bit",
    "gemma4-31b-mlx": "gemma-4-31b-it-4bit",
    "phi4-mini":      "phi-4-mini-4bit",
}

def get_mlx_vlm_model(model_id: str):
    """Must only be called from the inference thread."""
    if not _inference_ready.wait(timeout=30):
        raise RuntimeError("Inference worker failed to start within 30 seconds")
    
    if model_id in _vlm_cache:
        # Move to end to track LRU (Python 3.7+ dicts preserve insertion order)
        val = _vlm_cache.pop(model_id)
        _vlm_cache[model_id] = val
        return val
    
    if len(_vlm_cache) >= 2:
        # Remove the oldest entry (first item in the dict)
        lru_model_id = next(iter(_vlm_cache))
        logger.info(f"Evicting model {lru_model_id} from VRAM...")
        del _vlm_cache[lru_model_id]
        import gc; gc.collect()

    dir_name = _MODEL_DIR_MAP.get(model_id, model_id)
    model_path = os.path.join(MLX_MODELS_DIR, dir_name)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"mlx_vlm model directory not found: {model_path}")
    
    logger.info(f"Loading mlx_vlm model {model_id} from {model_path}...")
    model, processor = _mlx_vlm_load(model_path)
    _vlm_cache[model_id] = (model, processor)
    return model, processor

def get_mlx_lm_model(model_id: str):
    """Must only be called from the inference thread."""
    if model_id in _lm_cache:
        val = _lm_cache.pop(model_id)
        _lm_cache[model_id] = val
        return val

    if len(_lm_cache) >= 2:
        lru_id = next(iter(_lm_cache))
        logger.info(f"Evicting mlx_lm model {lru_id} from cache...")
        del _lm_cache[lru_id]
        import gc; gc.collect()

    dir_name = _MODEL_DIR_MAP.get(model_id, model_id)
    model_path = os.path.join(MLX_MODELS_DIR, dir_name)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"mlx_lm model directory not found: {model_path}")

    logger.info(f"Loading mlx_lm model {model_id} from {model_path}...")
    model, tokenizer = _mlx_lm_load(model_path)
    _lm_cache[model_id] = (model, tokenizer)
    return model, tokenizer


def handle_mlx_lm_request(model_id: str, messages: list) -> dict:
    """Text-only inference via mlx_lm (for architectures mlx_vlm doesn't support)."""
    model, tokenizer = get_mlx_lm_model(model_id)

    clean_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
            clean_messages.append({"role": role, "content": text})
        else:
            clean_messages.append({"role": role, "content": content or ""})

    prompt = tokenizer.apply_chat_template(
        clean_messages, tokenize=False, add_generation_prompt=True
    )

    logger.info(f"Starting mlx_lm inference for {model_id}...")
    global _last_inference_activity
    _last_inference_activity = time.monotonic()
    tokens = []
    for token in _mlx_lm_stream_generate(model, tokenizer, prompt, max_tokens=8192):
        if _stop_inference.is_set():
            logger.warning(f"Inference watchdog triggered: stopping generation for {model_id}")
            break
        tokens.append(token.text if hasattr(token, 'text') else token)
        _last_inference_activity = time.monotonic()

    return format_openai_response(model_id, "".join(tokens))


def handle_mlx_vlm_request(model_id: str, messages: list) -> dict:
    if model_id in _TEXT_ONLY_MODELS:
        return handle_mlx_lm_request(model_id, messages)
    model, processor = get_mlx_vlm_model(model_id)

    # Build clean message list; only the final message may carry an image
    clean_messages = []
    temp_image_path = None

    for i, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        is_last = i == len(messages) - 1

        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            text = " ".join(text_parts)
            if is_last and temp_image_path is None:
                for c in content:
                    if c.get("type") == "image_url":
                        url = c.get("image_url", {}).get("url", "")
                        if url.startswith("data:image"):
                            try:
                                header, encoded = url.split(",", 1)
                                ext = header.split(";")[0].split("/")[1]
                                data = base64.b64decode(encoded)
                                with tempfile.NamedTemporaryFile(
                                    delete=False, suffix=f".{ext}"
                                ) as tmp:
                                    tmp.write(data)
                                    temp_image_path = tmp.name
                                logger.info(f"Saved temp image for mlx_vlm: {temp_image_path}")
                            except Exception as e:
                                logger.error(f"Failed to decode image, continuing text-only: {e}")
                            break
            clean_messages.append({"role": role, "content": text})
        else:
            clean_messages.append({"role": role, "content": content or ""})

    # Render the prompt string using the processor's chat template
    try:
        prompt = processor.apply_chat_template(
            clean_messages, tokenize=False, add_generation_prompt=True
        )
    except Exception as e:
        logger.warning(f"processor.apply_chat_template failed ({e}), trying tokenizer fallback")
        prompt = processor.tokenizer.apply_chat_template(
            clean_messages, tokenize=False, add_generation_prompt=True
        )

    has_image = temp_image_path is not None
    logger.info(f"Starting mlx_vlm inference for {model_id} (image={'yes' if has_image else 'no'})...")
    try:
        tokens = []
        global _last_inference_activity
        _last_inference_activity = time.monotonic()

        for token in _mlx_vlm_stream_generate(
            model, processor, prompt,
            image=temp_image_path,
            max_tokens=8192,
        ):
            if _stop_inference.is_set():
                logger.warning(f"Inference watchdog triggered: stopping generation for {model_id}")
                break
            tokens.append(token.text if hasattr(token, 'text') else token)
            _last_inference_activity = time.monotonic()

        generated_text = "".join(tokens)
    finally:
        if temp_image_path and os.path.exists(temp_image_path):
            try:
                os.remove(temp_image_path)
            except Exception:
                pass

    return format_openai_response(model_id, generated_text)

def format_openai_response(model_id, content):
    completion_id = f"chatcmpl-{uuid.uuid4()}"
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }

async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Shared inference helper — runs blocking inference in the dedicated mlx
    thread so the asyncio event loop stays responsive and mlx GPU streams remain
    valid (streams are thread-local in mlx)."""
    t0 = time.monotonic()
    logger.info("inference start", extra={"model_id": model_id, "msg_count": len(messages)})
    result = await run_in_inference_thread(handle_mlx_vlm_request, model_id, messages)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("inference complete", extra={"model_id": model_id, "elapsed_ms": elapsed_ms})
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        logger.error(
            "unexpected inference response structure",
            extra={"model_id": model_id, "result_preview": str(result)[:200]},
        )
        raise RuntimeError(f"run_inference: unexpected response structure: {e}") from e
