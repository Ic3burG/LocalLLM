import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pytest


def _make_word_bytes_simple() -> bytes:
    """Build a minimal .docx with headings and paragraphs."""
    from docx import Document
    doc = Document()
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph("Hello world paragraph.")
    doc.add_paragraph("Second paragraph.")
    doc.add_heading("Section Two", level=2)
    doc.add_paragraph("Content in section two.")
    doc.core_properties.title = "Test Doc"
    doc.core_properties.author = "Test Author"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_word_returns_sections():
    from office_pipeline import extract_text_from_word
    sections, metadata = extract_text_from_word(_make_word_bytes_simple())
    assert len(sections) >= 1
    all_text = " ".join(text for _, text in sections)
    assert "Hello world paragraph" in all_text
    assert "Content in section two" in all_text


def test_extract_word_section_numbers_are_ints():
    from office_pipeline import extract_text_from_word
    sections, _ = extract_text_from_word(_make_word_bytes_simple())
    for num, _ in sections:
        assert isinstance(num, int)


def test_extract_word_metadata_has_required_keys():
    from office_pipeline import extract_text_from_word
    _, metadata = extract_text_from_word(_make_word_bytes_simple())
    for key in ("comments", "tracked_changes", "footnotes", "endnotes", "properties"):
        assert key in metadata, f"Missing key: {key}"


def test_extract_word_properties():
    from office_pipeline import extract_text_from_word
    _, metadata = extract_text_from_word(_make_word_bytes_simple())
    props = metadata["properties"]
    assert props["title"] == "Test Doc"
    assert props["author"] == "Test Author"
    for key in ("created", "modified", "subject", "keywords", "description"):
        assert key in props


def test_extract_word_empty_annotations_are_lists():
    from office_pipeline import extract_text_from_word
    _, metadata = extract_text_from_word(_make_word_bytes_simple())
    assert metadata["comments"] == []
    assert metadata["tracked_changes"] == []
    assert metadata["footnotes"] == []
    assert metadata["endnotes"] == []
