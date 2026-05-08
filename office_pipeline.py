import io
import uuid
import zipfile
import xml.etree.ElementTree as ET

from docx import Document
from docx.oxml.ns import qn


def extract_text_from_word(file_bytes: bytes) -> tuple[list[tuple[int, str]], dict]:
    """Extract body text and all annotations from a .docx file.

    Returns:
        (sections, metadata) where sections is list of (section_num, text)
        and metadata contains comments, tracked_changes, footnotes, endnotes, properties.
    """
    doc = Document(io.BytesIO(file_bytes))

    # --- Body text, split at heading boundaries ---
    sections: list[tuple[int, str]] = []
    section_num = 0
    current_lines: list[str] = []

    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            if current_lines:
                sections.append((section_num, "\n".join(current_lines)))
                current_lines = []
            section_num += 1
            if para.text.strip():
                current_lines.append(para.text)
        else:
            if para.text.strip():
                current_lines.append(para.text)

    if current_lines:
        sections.append((section_num, "\n".join(current_lines)))

    # If no headings produced sections, return body as single section
    if not sections:
        body_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if body_text:
            sections = [(1, body_text)]

    # --- Comments ---
    comments = _extract_word_comments(doc)

    # --- Tracked changes ---
    tracked_changes = _extract_tracked_changes(doc)

    # --- Footnotes ---
    footnotes = _extract_word_notes(doc, "footnotes")

    # --- Endnotes ---
    endnotes = _extract_word_notes(doc, "endnotes")

    # --- Document properties ---
    props = doc.core_properties
    properties = {
        "title": props.title or "",
        "author": props.author or "",
        "created": str(props.created) if props.created else "",
        "modified": str(props.modified) if props.modified else "",
        "subject": props.subject or "",
        "keywords": props.keywords or "",
        "description": getattr(props, "description", None) or getattr(props, "comments", None) or "",
    }

    metadata = {
        "comments": comments,
        "tracked_changes": tracked_changes,
        "footnotes": footnotes,
        "endnotes": endnotes,
        "properties": properties,
    }
    return sections, metadata


def _extract_word_comments(doc) -> list[dict]:
    comments = []
    _COMMENTS_REL = (
        "http://schemas.openxmlformats.org/officeDocument/2006/"
        "relationships/comments"
    )
    try:
        part = doc.part.part_related_by(_COMMENTS_REL)
        for c in part._element.findall(qn("w:comment")):
            author = c.get(qn("w:author"), "")
            date = c.get(qn("w:date"), "")
            text = "".join(t.text for t in c.iter(qn("w:t")) if t.text)
            comments.append({"author": author, "date": date, "text": text, "ref_text": ""})
    except KeyError:
        pass
    return comments


def _extract_tracked_changes(doc) -> list[dict]:
    changes = []
    body = doc.element.body
    for ins in body.iter(qn("w:ins")):
        author = ins.get(qn("w:author"), "")
        date = ins.get(qn("w:date"), "")
        text = "".join(t.text for t in ins.iter(qn("w:t")) if t.text)
        if text:
            changes.append({"author": author, "date": date, "type": "insert", "text": text})
    for del_ in body.iter(qn("w:del")):
        author = del_.get(qn("w:author"), "")
        date = del_.get(qn("w:date"), "")
        text = "".join(t.text for t in del_.iter(qn("w:delText")) if t.text)
        if text:
            changes.append({"author": author, "date": date, "type": "delete", "text": text})
    return changes


def _extract_word_notes(doc, note_type: str) -> list[dict]:
    """note_type is 'footnotes' or 'endnotes'."""
    notes = []
    rel = (
        f"http://schemas.openxmlformats.org/officeDocument/2006/"
        f"relationships/{note_type}"
    )
    tag = qn("w:footnote") if note_type == "footnotes" else qn("w:endnote")
    skip_types = {"separator", "continuationSeparator", "continuationNotice"}
    try:
        part = doc.part.part_related_by(rel)
        for el in part._element.findall(tag):
            if el.get(qn("w:type"), "") in skip_types:
                continue
            note_id = el.get(qn("w:id"), "")
            text = "".join(t.text for t in el.iter(qn("w:t")) if t.text)
            if text:
                notes.append({"ref_num": note_id, "text": text})
    except KeyError:
        pass
    return notes
