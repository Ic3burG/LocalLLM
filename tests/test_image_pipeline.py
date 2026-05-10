import base64
import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from image_pipeline import _apply_style, _parse_size, _should_swap, generate_image


def test_apply_style_default():
    assert _apply_style("a sunset", "default") == "a sunset"


def test_apply_style_photorealistic():
    result = _apply_style("a sunset", "photorealistic")
    assert result.startswith("a sunset")
    assert "photorealistic" in result


def test_apply_style_anime():
    assert "anime" in _apply_style("a cat", "anime")


def test_apply_style_unknown_falls_back():
    assert _apply_style("a cat", "nonexistent") == "a cat"


def test_parse_size_square():
    w, h = _parse_size("512x512")
    assert w == 512 and h == 512


def test_parse_size_portrait():
    w, h = _parse_size("512x768")
    assert w == 512 and h == 768


def test_parse_size_invalid_raises():
    with pytest.raises(ValueError):
        _parse_size("999x999")


def test_parse_size_malformed_raises():
    with pytest.raises(ValueError):
        _parse_size("abc")


def test_fast_mode_skips_swap():
    assert _should_swap(["phi-4-mini-4bit"]) is False


def test_deepseek_mini_skips_swap():
    assert _should_swap(["deepseek-v4-mini-7b-4bit"]) is False


def test_large_model_requires_swap():
    assert _should_swap(["gemma-4-26b-a4b-it-4bit"]) is True


def test_empty_loaded_models_skips_swap():
    assert _should_swap([]) is False


def _fake_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _make_mock_flux(fake_png: bytes):
    pil_img = Image.open(io.BytesIO(fake_png))
    mock_result = MagicMock()
    mock_result.image = pil_img
    mock_flux = MagicMock()
    mock_flux.generate_image.return_value = mock_result
    return mock_flux


def test_generate_image_returns_expected_shape():
    fake_png = _fake_png_bytes()
    mock_flux = _make_mock_flux(fake_png)
    with patch("image_pipeline.get_loaded_models", return_value=[]), \
         patch("image_pipeline._Flux1") as MockFlux1:
        MockFlux1.from_name.return_value = mock_flux
        result = generate_image("a sunset", size="512x512", steps=4)
    assert "image_b64" in result
    assert result["width"] == 512
    assert result["height"] == 512
    assert result["steps"] == 4
    assert "elapsed_ms" in result
    assert base64.b64decode(result["image_b64"])  # valid base64


def test_generate_image_applies_style():
    fake_png = _fake_png_bytes()
    mock_flux = _make_mock_flux(fake_png)
    with patch("image_pipeline.get_loaded_models", return_value=[]), \
         patch("image_pipeline._Flux1") as MockFlux1:
        MockFlux1.from_name.return_value = mock_flux
        generate_image("a cat", style="photorealistic")
    call_kwargs = mock_flux.generate_image.call_args
    prompt_used = call_kwargs.kwargs["prompt"]
    assert "photorealistic" in prompt_used


def test_generate_image_triggers_swap_for_large_model():
    fake_png = _fake_png_bytes()
    mock_flux = _make_mock_flux(fake_png)
    with patch("image_pipeline.get_loaded_models", return_value=["gemma-4-26b-a4b-it-4bit"]), \
         patch("image_pipeline._unload_text_model") as mock_unload, \
         patch("image_pipeline._Flux1") as MockFlux1:
        MockFlux1.from_name.return_value = mock_flux
        generate_image("a cat")
    # called twice: once to swap out text model before loading Flux, once after to free Flux weights
    assert mock_unload.call_count == 2
