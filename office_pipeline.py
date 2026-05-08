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
                section_num += 1
                sections.append((section_num, "\n".join(current_lines)))
                current_lines = []
            section_num += 1
            if para.text.strip():
                current_lines.append(para.text)
        else:
            if para.text.strip():
                current_lines.append(para.text)

    if current_lines:
        section_num += 1
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
    # Note: python-docx exposes dc:description as .comments in some versions,
    # so we check .description first, then fall back to .comments if needed.
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


def extract_text_from_excel(file_bytes: bytes) -> tuple[list[tuple[str, str]], dict]:
    """Extract cell text and all annotations from a .xlsx file.

    Returns:
        (sheets, metadata) where sheets is list of (sheet_name, tsv_text)
        and metadata contains cell_notes, threaded_comments, formulas,
        embedded_objects, properties.
    """
    import openpyxl

    # Load twice: once for formulas, once for cached values
    wb_formula = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=False)
    wb_cached = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)

    sheets: list[tuple[str, str]] = []
    cell_notes: list[dict] = []
    formulas: list[dict] = []

    for sheet_name in wb_cached.sheetnames:
        ws_cached = wb_cached[sheet_name]
        ws_formula = wb_formula[sheet_name]

        rows = []
        for row in ws_cached.iter_rows():
            parts = []
            for cell in row:
                if cell.value is not None:
                    parts.append(f"{cell.coordinate}={cell.value}")
            if parts:
                rows.append("\t".join(parts))

        if rows:
            sheets.append((sheet_name, "\n".join(rows)))

        # Capture formulas (cells whose formula-mode value starts with "=")
        for row in ws_formula.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cached_cell = ws_cached[cell.coordinate]
                    formulas.append({
                        "sheet": sheet_name,
                        "cell": cell.coordinate,
                        "formula": cell.value,
                        "cached_value": str(cached_cell.value) if cached_cell.value is not None else "",
                    })

        # Legacy cell notes (comments) — iterate cells to find per-cell comments
        for row in ws_cached.iter_rows():
            for cell in row:
                comment = cell.comment
                if comment is not None:
                    cell_notes.append({
                        "sheet": sheet_name,
                        "cell": cell.coordinate,
                        "author": comment.author or "",
                        "text": str(comment.text) if comment.text else "",
                    })

    threaded_comments = _extract_excel_threaded_comments(file_bytes)
    embedded_objects = _extract_excel_embedded_objects(file_bytes)

    # VBA macro detection
    if wb_formula.vba_archive is not None:
        embedded_objects.append({"type": "vba_macro", "flagged": True, "extracted_text": ""})

    props = wb_cached.properties
    properties = {
        "title": props.title or "" if props else "",
        "author": props.creator or "" if props else "",
        "created": str(props.created) if props and props.created else "",
        "modified": str(props.modified) if props and props.modified else "",
        "keywords": props.keywords or "" if props else "",
    }

    metadata = {
        "cell_notes": cell_notes,
        "threaded_comments": threaded_comments,
        "formulas": formulas,
        "embedded_objects": embedded_objects,
        "properties": properties,
    }
    return sheets, metadata


def _extract_excel_threaded_comments(file_bytes: bytes) -> list[dict]:
    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            thread_files = [n for n in z.namelist() if "threadedComment" in n and n.endswith(".xml")]
            for tf in thread_files:
                ns = {"tc": "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"}
                root = ET.parse(z.open(tf)).getroot()
                threads: dict[str, dict] = {}
                for tc in root.findall(".//tc:threadedComment", ns):
                    tc_id = tc.get("id", "")
                    ref = tc.get("ref", "")
                    parent_id = tc.get("parentId", "")
                    author_id = tc.get("personId", "")
                    text_el = tc.find("tc:text", ns)
                    text = text_el.text if text_el is not None else ""
                    entry = {"author_id": author_id, "text": text or ""}
                    if not parent_id:
                        threads[tc_id] = {"cell": ref, "thread": [entry]}
                    elif parent_id in threads:
                        threads[parent_id]["thread"].append(entry)
                results.extend(threads.values())
    except Exception:
        pass
    return results


def _extract_excel_embedded_objects(file_bytes: bytes) -> list[dict]:
    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            embedding_files = [n for n in z.namelist() if "embeddings/" in n]
            for ef in embedding_files:
                ext = ef.rsplit(".", 1)[-1].lower() if "." in ef else ""
                data = z.read(ef)
                if ext in ("docx", "xlsx", "pptx"):
                    results.append({"type": f"embedded_{ext}", "extracted_text": f"[embedded {ext} — binary]"})
                elif ext in ("bin", "ole", ""):
                    try:
                        import olefile
                        if olefile.isOleFile(io.BytesIO(data)):
                            ole = olefile.OleFileIO(io.BytesIO(data))
                            if ole.exists("WordDocument"):
                                obj_type = "embedded_word_ole"
                            elif ole.exists("Workbook"):
                                obj_type = "embedded_excel_ole"
                            else:
                                obj_type = "embedded_ole"
                            results.append({"type": obj_type, "extracted_text": f"[OLE object: {ef}]"})
                    except Exception:
                        results.append({"type": "embedded_binary", "extracted_text": f"[binary object: {ef}]"})
    except Exception:
        pass
    return results
