import pytest
from image_pipeline import _apply_style, _parse_size


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
