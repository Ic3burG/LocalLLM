import base64
import io
import logging
import random
import threading
import time

# Import mflux BEFORE inference_engine. inference_engine starts a daemon thread
# at module-load that imports mlx_vlm → transformers; doing it after would race
# with mflux's own `from transformers import PreTrainedTokenizer`, which
# transformers' lazy loader can't satisfy mid-load (the symbol comes up empty
# and mflux silently disables itself).
try:
    from mflux.models.flux.variants.txt2img.flux import Flux1 as _Flux1
except ImportError:
    _Flux1 = None  # type: ignore

from inference_engine import get_loaded_models

logger = logging.getLogger("image_pipeline")

STYLE_SUFFIXES: dict[str, str] = {
    "default": "",
    "photorealistic": ", photorealistic, 8k, highly detailed, sharp focus",
    "anime": ", anime style, cel shaded, vibrant colors",
    "sketch": ", pencil sketch, black and white, hand drawn",
}

_FAST_MODELS = {"phi-4-mini-4bit", "deepseek-v4-mini-7b-4bit"}

_sd_lock = threading.Lock()


def _apply_style(prompt: str, style: str) -> str:
    return prompt + STYLE_SUFFIXES.get(style, "")


_VALID_SIZES = {"512x512", "768x768", "512x768", "768x512", "1024x1024"}


def _parse_size(size: str) -> tuple[int, int]:
    normalized = size.lower().strip()
    if normalized not in _VALID_SIZES:
        raise ValueError(
            f"invalid size {size!r}; must be one of {sorted(_VALID_SIZES)}"
        )
    w, h = normalized.split("x")
    return int(w), int(h)


def _should_swap(loaded_models: list[str]) -> bool:
    """Return True if the active text model needs to be unloaded before image generation."""
    if not loaded_models:
        return False
    return not any(m in _FAST_MODELS for m in loaded_models)


def _unload_text_model() -> None:
    """Clear MLX metal cache to free unified memory for the image model."""
    try:
        import mlx.core as mx

        mx.metal.clear_cache()
        logger.info("text model cache cleared for image model swap")
    except Exception as e:
        logger.warning("metal cache clear failed: %s", e)


def generate_image(
    prompt: str,
    size: str = "512x512",
    steps: int = 4,
    style: str = "default",
) -> dict:
    """Generate an image using FLUX.1-schnell via mflux. Returns dict with image_b64 and metadata."""
    if _Flux1 is None:
        raise ImportError("mflux not installed. Run: pip install mflux")

    width, height = _parse_size(size)
    styled_prompt = _apply_style(prompt, style)

    with _sd_lock:
        loaded = get_loaded_models()
        if _should_swap(loaded):
            _unload_text_model()

        t0 = time.monotonic()
        flux = _Flux1.from_name("schnell", quantize=4)
        result = flux.generate_image(
            seed=random.randint(0, 2**31 - 1),
            prompt=styled_prompt,
            num_inference_steps=steps,
            height=height,
            width=width,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _unload_text_model()  # free Flux weights from Metal cache immediately

    buf = io.BytesIO()
    result.image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    return {
        "image_b64": base64.b64encode(png_bytes).decode("utf-8"),
        "width": width,
        "height": height,
        "steps": steps,
        "elapsed_ms": elapsed_ms,
    }


def get_downloaded_models() -> list[str]:
    """Return list of available model IDs. mflux downloads weights automatically on first use."""
    return ["flux-schnell"]
