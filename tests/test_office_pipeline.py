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


def _make_word_bytes_with_comments() -> bytes:
    """Build a .docx that contains a comment using lxml directly."""
    from docx import Document
    from lxml import etree

    doc = Document()
    doc.add_paragraph("This text has a comment.")

    # Build comments XML part manually
    comments_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:comment w:id="1" w:author="Alice" w:date="2026-01-01T00:00:00Z">'
        '<w:p><w:r><w:t>Great point!</w:t></w:r></w:p>'
        '</w:comment>'
        '</w:comments>'
    )

    # Inject comments part into the docx package
    from docx.opc.part import Part
    from docx.opc.packuri import PackURI
    comments_part = Part(
        PackURI("/word/comments.xml"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
        comments_xml.encode(),
        doc.part.package,
    )
    rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
    doc.part.relate_to(comments_part, rel_type)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_word_bytes_with_tracked_changes() -> bytes:
    """Build a .docx with a tracked insertion."""
    from docx import Document
    from docx.oxml.ns import qn
    from lxml import etree

    doc = Document()
    para = doc.add_paragraph()

    # Add a normal run
    run = para.add_run("Original text. ")

    # Add a tracked insertion run
    ins_xml = (
        '<w:ins xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'w:id="1" w:author="Bob" w:date="2026-01-02T00:00:00Z">'
        '<w:r><w:t>Inserted text.</w:t></w:r>'
        '</w:ins>'
    )
    ins_el = etree.fromstring(ins_xml)
    para._element.append(ins_el)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_word_comments():
    from office_pipeline import extract_text_from_word
    _, metadata = extract_text_from_word(_make_word_bytes_with_comments())
    assert len(metadata["comments"]) == 1
    c = metadata["comments"][0]
    assert c["author"] == "Alice"
    assert "Great point" in c["text"]
    assert "date" in c
    assert "ref_text" in c


def test_extract_word_tracked_changes():
    from office_pipeline import extract_text_from_word
    _, metadata = extract_text_from_word(_make_word_bytes_with_tracked_changes())
    inserts = [tc for tc in metadata["tracked_changes"] if tc["type"] == "insert"]
    assert len(inserts) >= 1
    assert inserts[0]["author"] == "Bob"
    assert "Inserted text" in inserts[0]["text"]
