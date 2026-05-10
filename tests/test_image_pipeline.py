import pytest
from image_pipeline import _apply_style, _parse_size, _should_swap


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


def test_fast_mode_skips_swap():
    assert _should_swap(["phi-4-mini-4bit"]) is False


def test_deepseek_mini_skips_swap():
    assert _should_swap(["deepseek-v4-mini-7b-4bit"]) is False


def test_large_model_requires_swap():
    assert _should_swap(["gemma-4-26b-a4b-it-4bit"]) is True


def test_empty_loaded_models_skips_swap():
    assert _should_swap([]) is False
