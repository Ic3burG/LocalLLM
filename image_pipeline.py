import io
import base64
import logging
import threading
import time
from pathlib import Path

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


def _parse_size(size: str) -> tuple[int, int]:
    w, h = size.lower().split("x")
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
    """Generate an image. Returns dict with image_b64 and metadata."""
    raise NotImplementedError("implement in Task 4")


def get_downloaded_models() -> list[str]:
    """Return list of available model IDs. mflux downloads weights automatically on first use."""
    return ["flux-schnell"]
