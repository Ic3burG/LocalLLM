# Word & Excel Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add comprehensive Word (.docx) and Excel (.xlsx) read/write + RAG ingestion support to the Gemma4 agent.

**Architecture:** New `office_pipeline.py` mirrors `pdf_pipeline.py` — `extract_text_from_word` and `extract_text_from_excel` return `(list[tuple], metadata_dict)`, and `ingest_office` returns the same `{doc_id, filename, page_count, chunks, embeddings}` dict shape. Four new async tool functions in `agent_utils.py` follow the exact `_read_pdf`/`_write_pdf` pattern. The `/v1/document` endpoint in `gemma_bridge.py` gains extension-based routing to `ingest_office`.

**Tech Stack:** `python-docx` (Word), `openpyxl` (Excel), `oletools`/`olefile` (embedded OLE objects), `lxml` (tracked-changes XML), `zipfile` stdlib (threaded comments), `pdf_pipeline.chunk_text` + `embed_texts` (reused for chunking/embedding).

---

## Task 1: Install dependencies

**Files:**

- Modify: `requirements.txt`

- [ ] **Step 1: Add libraries to requirements.txt**

Open `requirements.txt` and append these three lines at the end:

```
python-docx
openpyxl
oletools
```

- [ ] **Step 2: Install them**

```bash
pip install python-docx openpyxl oletools
```

Expected: all three install without errors. Verify:

```bash
python3 -c "import docx, openpyxl, olefile; print('ok')"
```

Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add python-docx, openpyxl, oletools dependencies"
```

---

## Task 2: Word body extraction (TDD)

**Files:**

- Create: `office_pipeline.py`
- Create: `tests/test_office_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_office_pipeline.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'office_pipeline'`

- [ ] **Step 3: Create `office_pipeline.py` with Word body extraction**

Create `/Users/ojdavis/Claude Code/Gemma4/office_pipeline.py`:

```python
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
        "description": props.description or "",
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
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_extract_word_returns_sections tests/test_office_pipeline.py::test_extract_word_section_numbers_are_ints tests/test_office_pipeline.py::test_extract_word_metadata_has_required_keys tests/test_office_pipeline.py::test_extract_word_properties tests/test_office_pipeline.py::test_extract_word_empty_annotations_are_lists -v
```

Expected: all 5 PASS

- [ ] **Step 5: Commit**

```bash
git add office_pipeline.py tests/test_office_pipeline.py
git commit -m "feat: add Word body extraction to office_pipeline"
```

---

## Task 3: Word annotation extraction (TDD)

**Files:**

- Modify: `tests/test_office_pipeline.py` (append tests)
- Modify: `office_pipeline.py` (already implemented in Task 2 — verify with these tests)

- [ ] **Step 1: Add annotation tests to `tests/test_office_pipeline.py`**

Append to the end of `tests/test_office_pipeline.py`:

```python
def _make_word_bytes_with_comments() -> bytes:
    """Build a .docx that contains a comment using lxml directly."""
    from docx import Document
    from docx.oxml.ns import qn, nsmap
    from docx.oxml import OxmlElement
    from lxml import etree
    import copy

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
```

- [ ] **Step 2: Run the annotation tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_extract_word_comments tests/test_office_pipeline.py::test_extract_word_tracked_changes -v
```

Expected: both PASS (the extraction code was already written in Task 2)

- [ ] **Step 3: Commit**

```bash
git add tests/test_office_pipeline.py
git commit -m "test: add Word annotation extraction tests"
```

---

## Task 4: Excel cell extraction (TDD)

**Files:**

- Modify: `tests/test_office_pipeline.py` (append tests)
- Modify: `office_pipeline.py` (add Excel functions)

- [ ] **Step 1: Append Excel cell extraction tests to `tests/test_office_pipeline.py`**

```python
def _make_excel_bytes_simple() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws["A1"] = "Name"
    ws["B1"] = "Score"
    ws["A2"] = "Alice"
    ws["B2"] = 95
    ws["A3"] = "Bob"
    ws["B3"] = 87
    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "Total"
    ws2["B1"] = 2
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_excel_returns_sheets():
    from office_pipeline import extract_text_from_excel
    sheets, metadata = extract_text_from_excel(_make_excel_bytes_simple())
    assert len(sheets) == 2
    names = [name for name, _ in sheets]
    assert "Results" in names
    assert "Summary" in names


def test_extract_excel_cell_values_in_text():
    from office_pipeline import extract_text_from_excel
    sheets, _ = extract_text_from_excel(_make_excel_bytes_simple())
    results_text = next(text for name, text in sheets if name == "Results")
    assert "Alice" in results_text
    assert "95" in results_text
    assert "Bob" in results_text


def test_extract_excel_metadata_has_required_keys():
    from office_pipeline import extract_text_from_excel
    _, metadata = extract_text_from_excel(_make_excel_bytes_simple())
    for key in ("cell_notes", "threaded_comments", "formulas", "embedded_objects", "properties"):
        assert key in metadata, f"Missing key: {key}"


def test_extract_excel_empty_annotations_are_lists():
    from office_pipeline import extract_text_from_excel
    _, metadata = extract_text_from_excel(_make_excel_bytes_simple())
    assert metadata["cell_notes"] == []
    assert metadata["threaded_comments"] == []
    assert metadata["embedded_objects"] == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_extract_excel_returns_sheets -v 2>&1 | head -15
```

Expected: `ImportError` or `AttributeError` — `extract_text_from_excel` not yet defined.

- [ ] **Step 3: Add Excel extraction to `office_pipeline.py`**

Append to the end of `office_pipeline.py`:

```python
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

        # Legacy cell notes (comments)
        for coord, comment in (ws_cached.comments or {}).items():
            cell_notes.append({
                "sheet": sheet_name,
                "cell": str(coord),
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
```

- [ ] **Step 4: Run Excel cell tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_extract_excel_returns_sheets tests/test_office_pipeline.py::test_extract_excel_cell_values_in_text tests/test_office_pipeline.py::test_extract_excel_metadata_has_required_keys tests/test_office_pipeline.py::test_extract_excel_empty_annotations_are_lists -v
```

Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
git add office_pipeline.py tests/test_office_pipeline.py
git commit -m "feat: add Excel cell and annotation extraction to office_pipeline"
```

---

## Task 5: Excel formula and cell-note tests (TDD)

**Files:**

- Modify: `tests/test_office_pipeline.py` (append tests)

- [ ] **Step 1: Append formula and cell-note tests**

```python
def _make_excel_bytes_with_formulas() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws["A1"] = 10
    ws["A2"] = 20
    ws["A3"] = "=A1+A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_excel_bytes_with_cell_note() -> bytes:
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    wb = Workbook()
    ws = wb.active
    ws.title = "Notes"
    ws["A1"] = "Value"
    comment = Comment("Remember to update this quarterly.", "Finance Team")
    ws["A1"].comment = comment
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_excel_formulas():
    from office_pipeline import extract_text_from_excel
    _, metadata = extract_text_from_excel(_make_excel_bytes_with_formulas())
    formulas = metadata["formulas"]
    assert len(formulas) >= 1
    f = next(x for x in formulas if x["formula"] == "=A1+A2")
    assert f["sheet"] == "Calc"
    assert f["cell"] == "A3"
    assert "formula" in f
    assert "cached_value" in f


def test_extract_excel_cell_notes():
    from office_pipeline import extract_text_from_excel
    _, metadata = extract_text_from_excel(_make_excel_bytes_with_cell_note())
    notes = metadata["cell_notes"]
    assert len(notes) >= 1
    n = notes[0]
    assert n["sheet"] == "Notes"
    assert "A1" in n["cell"]
    assert "Finance Team" in n["author"]
    assert "quarterly" in n["text"]
```

- [ ] **Step 2: Run formula and note tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_extract_excel_formulas tests/test_office_pipeline.py::test_extract_excel_cell_notes -v
```

Expected: both PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_office_pipeline.py
git commit -m "test: add Excel formula and cell-note tests"
```

---

## Task 6: `ingest_office` function (TDD)

**Files:**

- Modify: `tests/test_office_pipeline.py` (append tests)
- Modify: `office_pipeline.py` (append function)

- [ ] **Step 1: Append ingest tests**

```python
def test_ingest_office_word_shape():
    from office_pipeline import ingest_office
    doc = ingest_office(_make_word_bytes_simple(), "test.docx")
    assert doc is not None
    assert "doc_id" in doc
    assert "filename" in doc
    assert "page_count" in doc
    assert "chunks" in doc
    assert "embeddings" in doc
    assert doc["filename"] == "test.docx"
    assert len(doc["chunks"]) >= 1
    assert doc["embeddings"].shape[0] == len(doc["chunks"])


def test_ingest_office_excel_shape():
    from office_pipeline import ingest_office
    doc = ingest_office(_make_excel_bytes_simple(), "data.xlsx")
    assert doc is not None
    assert doc["filename"] == "data.xlsx"
    assert len(doc["chunks"]) >= 1
    assert doc["embeddings"].shape[0] == len(doc["chunks"])


def test_ingest_office_unknown_extension_returns_none():
    from office_pipeline import ingest_office
    result = ingest_office(b"garbage", "file.txt")
    assert result is None


def test_ingest_office_empty_word_returns_none():
    from office_pipeline import ingest_office
    from docx import Document
    doc = Document()
    buf = io.BytesIO()
    doc.save(buf)
    result = ingest_office(buf.getvalue(), "empty.docx")
    assert result is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_ingest_office_word_shape -v 2>&1 | head -15
```

Expected: `ImportError` — `ingest_office` not yet defined.

- [ ] **Step 3: Append `ingest_office` and helpers to `office_pipeline.py`**

```python
def ingest_office(file_bytes: bytes, filename: str) -> dict | None:
    """Ingest a Word or Excel file into the RAG document store.

    Returns the same dict shape as pdf_pipeline.ingest_pdf, or None if
    the file type is unrecognised or produces no text.
    """
    from pdf_pipeline import chunk_text, embed_texts
    import numpy as np

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "docx":
        sections, metadata = extract_text_from_word(file_bytes)
        pages = list(sections)
        extra = _format_word_metadata_text(metadata)
        if extra:
            pages.append((len(pages) + 1, extra))
    elif ext == "xlsx":
        sheets, metadata = extract_text_from_excel(file_bytes)
        pages = [(i + 1, text) for i, (_, text) in enumerate(sheets)]
        extra = _format_excel_metadata_text(metadata)
        if extra:
            pages.append((len(pages) + 1, extra))
    else:
        return None

    if not pages:
        return None

    chunks = chunk_text(pages)
    if not chunks:
        return None

    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    doc_id = uuid.uuid4().hex[:8]
    page_count = pages[-1][0] if pages else 0
    return {
        "doc_id": doc_id,
        "filename": filename,
        "page_count": page_count,
        "chunks": chunks,
        "embeddings": embeddings,
    }


def _format_word_metadata_text(metadata: dict) -> str:
    parts = []
    if metadata.get("comments"):
        parts.append("## Comments")
        for c in metadata["comments"]:
            parts.append(f"[{c['author']}, {c['date']}]: {c['text']}")
    if metadata.get("tracked_changes"):
        parts.append("## Tracked Changes")
        for tc in metadata["tracked_changes"]:
            parts.append(f"[{tc['type'].upper()} by {tc['author']} on {tc['date']}]: {tc['text']}")
    if metadata.get("footnotes"):
        parts.append("## Footnotes")
        for fn in metadata["footnotes"]:
            parts.append(f"[{fn['ref_num']}]: {fn['text']}")
    if metadata.get("endnotes"):
        parts.append("## Endnotes")
        for en in metadata["endnotes"]:
            parts.append(f"[{en['ref_num']}]: {en['text']}")
    if metadata.get("properties"):
        p = metadata["properties"]
        kv = ", ".join(f"{k}: {v}" for k, v in p.items() if v)
        if kv:
            parts.append(f"## Document Properties\n{kv}")
    return "\n".join(parts)


def _format_excel_metadata_text(metadata: dict) -> str:
    parts = []
    if metadata.get("cell_notes"):
        parts.append("## Cell Notes")
        for n in metadata["cell_notes"]:
            parts.append(f"[{n['sheet']}!{n['cell']}, {n['author']}]: {n['text']}")
    if metadata.get("threaded_comments"):
        parts.append("## Threaded Comments")
        for tc in metadata["threaded_comments"]:
            for reply in tc.get("thread", []):
                parts.append(f"[{tc['cell']}]: {reply['text']}")
    if metadata.get("formulas"):
        parts.append("## Formulas")
        for f in metadata["formulas"]:
            parts.append(f"[{f['sheet']}!{f['cell']}] {f['formula']} = {f['cached_value']}")
    if metadata.get("embedded_objects"):
        parts.append("## Embedded Objects")
        for obj in metadata["embedded_objects"]:
            if obj.get("flagged"):
                parts.append(f"WARNING: VBA macro detected (not executed)")
            else:
                parts.append(f"[{obj['type']}]: {obj['extracted_text']}")
    if metadata.get("properties"):
        p = metadata["properties"]
        kv = ", ".join(f"{k}: {v}" for k, v in p.items() if v)
        if kv:
            parts.append(f"## Document Properties\n{kv}")
    return "\n".join(parts)


def format_office_read_output(sections_or_sheets: list[tuple], metadata: dict, filetype: str) -> str:
    """Format extraction results into a single readable string for the agent."""
    parts = []
    label = "Section" if filetype == "word" else "Sheet"
    for key, text in sections_or_sheets:
        parts.append(f"[{label} {key}]\n{text}")
    annotation_text = (
        _format_word_metadata_text(metadata)
        if filetype == "word"
        else _format_excel_metadata_text(metadata)
    )
    if annotation_text:
        parts.append(annotation_text)
    result = "\n\n".join(parts)
    return result[:15000] if len(result) > 15000 else result
```

- [ ] **Step 4: Run ingest tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_ingest_office_word_shape tests/test_office_pipeline.py::test_ingest_office_excel_shape tests/test_office_pipeline.py::test_ingest_office_unknown_extension_returns_none tests/test_office_pipeline.py::test_ingest_office_empty_word_returns_none -v
```

Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
git add office_pipeline.py tests/test_office_pipeline.py
git commit -m "feat: add ingest_office and metadata formatting to office_pipeline"
```

---

## Task 7: `_read_word` and `_read_excel` agent tools (TDD)

**Files:**

- Modify: `tests/test_office_pipeline.py` (append tool tests)
- Modify: `agent_utils.py`

- [ ] **Step 1: Append read-tool tests**

```python
def _write_tmp_word(tmp_path_factory) -> str:
    import tempfile, os
    data = _make_word_bytes_simple()
    f = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    f.write(data)
    f.close()
    return f.name


def _write_tmp_excel(tmp_path_factory) -> str:
    import tempfile
    data = _make_excel_bytes_simple()
    f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    f.write(data)
    f.close()
    return f.name


@pytest.mark.asyncio
async def test_read_word_tool_returns_text():
    import tempfile, asyncio
    from agent_utils import _read_word
    data = _make_word_bytes_simple()
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(data)
        path = f.name
    result = await _read_word(path)
    assert "ERROR" not in result
    assert "Hello world paragraph" in result


@pytest.mark.asyncio
async def test_read_excel_tool_returns_text():
    import tempfile, asyncio
    from agent_utils import _read_excel
    data = _make_excel_bytes_simple()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(data)
        path = f.name
    result = await _read_excel(path)
    assert "ERROR" not in result
    assert "Alice" in result


@pytest.mark.asyncio
async def test_read_word_tool_missing_file():
    from agent_utils import _read_word
    result = await _read_word("/tmp/does_not_exist_abc123.docx")
    assert result.startswith("ERROR")


@pytest.mark.asyncio
async def test_read_excel_tool_missing_file():
    from agent_utils import _read_excel
    result = await _read_excel("/tmp/does_not_exist_abc123.xlsx")
    assert result.startswith("ERROR")
```

- [ ] **Step 2: Install pytest-asyncio if not present**

```bash
pip install pytest-asyncio -q && python -m pytest tests/test_office_pipeline.py::test_read_word_tool_missing_file -v 2>&1 | head -20
```

Expected: `ImportError` or `AttributeError` — `_read_word` not yet in `agent_utils`.

- [ ] **Step 3: Add `_read_word` and `_read_excel` to `agent_utils.py`**

Add these two functions immediately after `_write_pdf` (around line 444). Insert before the `_http_request` function:

```python
async def _read_word(path: str) -> str:
    try:
        p = validate_path(path)
        from office_pipeline import extract_text_from_word, format_office_read_output
        loop = asyncio.get_running_loop()
        file_bytes = p.read_bytes()
        sections, metadata = await loop.run_in_executor(
            None, extract_text_from_word, file_bytes
        )
        return format_office_read_output(sections, metadata, "word")
    except Exception as e:
        logger.error("read_word failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _read_excel(path: str) -> str:
    try:
        p = validate_path(path)
        from office_pipeline import extract_text_from_excel, format_office_read_output
        loop = asyncio.get_running_loop()
        file_bytes = p.read_bytes()
        sheets, metadata = await loop.run_in_executor(
            None, extract_text_from_excel, file_bytes
        )
        return format_office_read_output(sheets, metadata, "excel")
    except Exception as e:
        logger.error("read_excel failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"
```

- [ ] **Step 4: Register the tools in `agent_utils.py`**

Find the line `register_tool("read_pdf", ...)` (line ~650) and add after `register_tool("write_pdf", ...)`:

```python
register_tool("read_word", "safe", "Extract text and annotations from a Word (.docx) file", _read_word)
register_tool("read_excel", "safe", "Extract text and annotations from an Excel (.xlsx) file", _read_excel)
```

- [ ] **Step 5: Add tool descriptions to `AGENT_SYSTEM_PROMPT`**

Find the line `  read_pdf(path)` in `AGENT_SYSTEM_PROMPT` and add after `write_pdf`:

```
  read_word(path)                               — extract text, comments, tracked changes, footnotes, and metadata from a Word (.docx) file
  write_word(path, spec)                        — create a Word file from a JSON spec dict (sections with headings, paragraphs, tables, footnotes)
  read_excel(path)                              — extract cell values, formulas, notes, and threaded comments from an Excel (.xlsx) file
  write_excel(path, spec)                       — create an Excel file from a JSON spec dict (sheets, cells, merges, charts)
```

- [ ] **Step 6: Run read-tool tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_read_word_tool_returns_text tests/test_office_pipeline.py::test_read_excel_tool_returns_text tests/test_office_pipeline.py::test_read_word_tool_missing_file tests/test_office_pipeline.py::test_read_excel_tool_missing_file -v
```

Expected: all 4 PASS

- [ ] **Step 7: Commit**

```bash
git add agent_utils.py tests/test_office_pipeline.py
git commit -m "feat: add read_word and read_excel agent tools"
```

---

## Task 8: `write_word_document` + `_write_word` tool (TDD)

**Files:**

- Modify: `tests/test_office_pipeline.py` (append tests)
- Modify: `office_pipeline.py` (append write function)
- Modify: `agent_utils.py` (add `_write_word`)

- [ ] **Step 1: Append write-word tests**

```python
@pytest.mark.asyncio
async def test_write_word_roundtrip_body():
    import tempfile, json
    from agent_utils import _write_word
    from office_pipeline import extract_text_from_word

    spec = {
        "properties": {"title": "My Report", "author": "Omar"},
        "sections": [
            {"type": "heading", "level": 1, "text": "Executive Summary"},
            {"type": "paragraph", "text": "Revenue grew 15% this quarter.", "bold": False},
            {"type": "paragraph", "text": "Key finding.", "bold": True},
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        path = f.name

    result = await _write_word(path, json.dumps(spec))
    assert "ERROR" not in result

    file_bytes = open(path, "rb").read()
    sections, metadata = extract_text_from_word(file_bytes)
    all_text = " ".join(t for _, t in sections)
    assert "Executive Summary" in all_text
    assert "Revenue grew" in all_text
    assert metadata["properties"]["title"] == "My Report"


@pytest.mark.asyncio
async def test_write_word_roundtrip_table():
    import tempfile, json
    from agent_utils import _write_word
    from office_pipeline import extract_text_from_word

    spec = {
        "sections": [
            {
                "type": "table",
                "rows": [["Name", "Score"], ["Alice", "95"], ["Bob", "87"]],
                "header_row": True,
                "merge": []
            }
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        path = f.name

    result = await _write_word(path, json.dumps(spec))
    assert "ERROR" not in result

    from docx import Document
    doc = Document(path)
    tables = doc.tables
    assert len(tables) == 1
    assert tables[0].cell(0, 0).text == "Name"
    assert tables[0].cell(1, 0).text == "Alice"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_write_word_roundtrip_body -v 2>&1 | head -15
```

Expected: `ImportError` or `AttributeError` — `_write_word` not yet defined.

- [ ] **Step 3: Append `write_word_document` to `office_pipeline.py`**

```python
def write_word_document(path, spec: dict) -> None:
    """Create a .docx file from a structured spec dict."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()

    props = spec.get("properties", {})
    core = doc.core_properties
    if props.get("title"):
        core.title = props["title"]
    if props.get("author"):
        core.author = props["author"]
    if props.get("subject"):
        core.subject = props["subject"]
    if props.get("keywords"):
        core.keywords = props["keywords"]

    for section in spec.get("sections", []):
        stype = section.get("type", "paragraph")

        if stype == "heading":
            level = min(max(int(section.get("level", 1)), 1), 6)
            doc.add_heading(section.get("text", ""), level=level)

        elif stype == "paragraph":
            p = doc.add_paragraph()
            run = p.add_run(section.get("text", ""))
            if section.get("bold"):
                run.bold = True
            if section.get("italic"):
                run.italic = True
            if section.get("underline"):
                run.underline = True

        elif stype == "table":
            rows_data = section.get("rows", [])
            if rows_data:
                n_cols = max((len(r) for r in rows_data), default=1)
                table = doc.add_table(rows=len(rows_data), cols=n_cols)
                for i, row in enumerate(rows_data):
                    for j, cell_val in enumerate(row):
                        if j < n_cols:
                            table.cell(i, j).text = str(cell_val) if cell_val is not None else ""
                for merge in section.get("merge", []):
                    r, c = merge["row"], merge["col"]
                    rs, cs = merge["rowspan"], merge["colspan"]
                    table.cell(r, c).merge(table.cell(r + rs - 1, c + cs - 1))

        elif stype in ("footnote", "endnote"):
            # python-docx has no public footnote API; append as labelled paragraph
            label = "Footnote" if stype == "footnote" else "Endnote"
            p = doc.add_paragraph()
            run = p.add_run(f"[{label} {section.get('ref_paragraph', '')}]: {section.get('text', '')}")
            run.font.size = Pt(9)

    doc.save(str(path))
```

- [ ] **Step 4: Add `_write_word` to `agent_utils.py`**

Add immediately after `_read_excel` (after Task 7's additions):

```python
async def _write_word(path: str, spec: str) -> str:
    log_audit(f"WRITE_WORD: {path}")
    try:
        p = validate_path(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        spec_dict = _json.loads(spec) if isinstance(spec, str) else spec
        loop = asyncio.get_running_loop()
        from office_pipeline import write_word_document

        def _sync():
            write_word_document(p, spec_dict)
            return f"OK: wrote Word document to {path}"

        return await loop.run_in_executor(None, _sync)
    except Exception as e:
        logger.error("write_word failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"
```

- [ ] **Step 5: Register `write_word` in `agent_utils.py`**

Add after `register_tool("read_excel", ...)`:

```python
register_tool("write_word", "risky", "Create a Word (.docx) file from a JSON spec", _write_word)
```

- [ ] **Step 6: Run write-word tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_write_word_roundtrip_body tests/test_office_pipeline.py::test_write_word_roundtrip_table -v
```

Expected: both PASS

- [ ] **Step 7: Commit**

```bash
git add office_pipeline.py agent_utils.py tests/test_office_pipeline.py
git commit -m "feat: add write_word_document and write_word agent tool"
```

---

## Task 9: `write_excel_document` + `_write_excel` tool (TDD)

**Files:**

- Modify: `tests/test_office_pipeline.py` (append tests)
- Modify: `office_pipeline.py` (append write function)
- Modify: `agent_utils.py` (add `_write_excel`)

- [ ] **Step 1: Append write-excel tests**

```python
@pytest.mark.asyncio
async def test_write_excel_roundtrip_cells():
    import tempfile, json
    from agent_utils import _write_excel
    from openpyxl import load_workbook

    spec = {
        "properties": {"title": "Q1 Results"},
        "sheets": [
            {
                "name": "Data",
                "rows": [
                    [{"value": "Name"}, {"value": "Revenue", "bold": True}],
                    [{"value": "Alice"}, {"value": 50000}],
                    [{"value": "Bob"}, {"value": 35000}],
                ],
                "merges": [],
                "charts": []
            }
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name

    result = await _write_excel(path, json.dumps(spec))
    assert "ERROR" not in result

    wb = load_workbook(path)
    assert "Data" in wb.sheetnames
    ws = wb["Data"]
    assert ws["A1"].value == "Name"
    assert ws["A2"].value == "Alice"
    assert ws["B3"].value == 35000


@pytest.mark.asyncio
async def test_write_excel_roundtrip_formula():
    import tempfile, json
    from agent_utils import _write_excel
    from openpyxl import load_workbook

    spec = {
        "sheets": [
            {
                "name": "Calc",
                "rows": [
                    [{"value": 10}],
                    [{"value": 20}],
                    [{"formula": "=A1+A2"}],
                ],
                "merges": [],
                "charts": []
            }
        ]
    }
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name

    result = await _write_excel(path, json.dumps(spec))
    assert "ERROR" not in result

    wb = load_workbook(path, data_only=False)
    ws = wb["Calc"]
    assert ws["A3"].value == "=A1+A2"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_write_excel_roundtrip_cells -v 2>&1 | head -15
```

Expected: `ImportError` or `AttributeError` — `_write_excel` not yet defined.

- [ ] **Step 3: Append `write_excel_document` to `office_pipeline.py`**

```python
def write_excel_document(path, spec: dict) -> None:
    """Create a .xlsx file from a structured spec dict."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.utils.cell import range_boundaries

    wb = Workbook()
    wb.remove(wb.active)

    props = spec.get("properties", {})
    if props.get("title"):
        wb.properties.title = props["title"]
    if props.get("author"):
        wb.properties.creator = props["author"]
    if props.get("keywords"):
        wb.properties.keywords = props["keywords"]

    for sheet_spec in spec.get("sheets", []):
        ws = wb.create_sheet(title=sheet_spec.get("name", "Sheet"))
        rows_data = sheet_spec.get("rows", [])

        for r_idx, row in enumerate(rows_data, start=1):
            for c_idx, cell_spec in enumerate(row, start=1):
                if cell_spec is None:
                    continue
                cell = ws.cell(row=r_idx, column=c_idx)
                if isinstance(cell_spec, dict):
                    val = cell_spec.get("formula") or cell_spec.get("value")
                    cell.value = val
                    font_kw: dict = {}
                    if cell_spec.get("bold"):
                        font_kw["bold"] = True
                    if cell_spec.get("italic"):
                        font_kw["italic"] = True
                    if font_kw:
                        cell.font = Font(**font_kw)
                    if cell_spec.get("bg_color"):
                        cell.fill = PatternFill(fill_type="solid", fgColor=cell_spec["bg_color"])
                    if cell_spec.get("number_format"):
                        cell.number_format = cell_spec["number_format"]
                    if cell_spec.get("alignment"):
                        cell.alignment = Alignment(horizontal=cell_spec["alignment"])
                else:
                    cell.value = cell_spec

        for merge_range in sheet_spec.get("merges", []):
            ws.merge_cells(merge_range)

        for chart_spec in sheet_spec.get("charts", []):
            ctype = chart_spec.get("type", "bar")
            if ctype == "bar":
                chart = BarChart()
            elif ctype == "line":
                chart = LineChart()
            elif ctype == "pie":
                chart = PieChart()
            else:
                continue
            chart.title = chart_spec.get("title", "")
            data_range = chart_spec.get("data_range", "")
            if data_range:
                min_col, min_row, max_col, max_row = range_boundaries(data_range)
                data = Reference(ws, min_col=min_col, min_row=min_row, max_col=max_col, max_row=max_row)
                chart.add_data(data, titles_from_data=True)
            ws.add_chart(chart, chart_spec.get("anchor", "E1"))

    wb.save(str(path))
```

- [ ] **Step 4: Add `_write_excel` to `agent_utils.py`**

Add immediately after `_write_word`:

```python
async def _write_excel(path: str, spec: str) -> str:
    log_audit(f"WRITE_EXCEL: {path}")
    try:
        p = validate_path(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        spec_dict = _json.loads(spec) if isinstance(spec, str) else spec
        loop = asyncio.get_running_loop()
        from office_pipeline import write_excel_document

        def _sync():
            write_excel_document(p, spec_dict)
            return f"OK: wrote Excel file to {path}"

        return await loop.run_in_executor(None, _sync)
    except Exception as e:
        logger.error("write_excel failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"
```

- [ ] **Step 5: Register `write_excel` in `agent_utils.py`**

Add after `register_tool("write_word", ...)`:

```python
register_tool("write_excel", "risky", "Create an Excel (.xlsx) file from a JSON spec", _write_excel)
```

- [ ] **Step 6: Run write-excel tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/test_office_pipeline.py::test_write_excel_roundtrip_cells tests/test_office_pipeline.py::test_write_excel_roundtrip_formula -v
```

Expected: both PASS

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests PASS, no regressions in existing tests.

- [ ] **Step 8: Commit**

```bash
git add office_pipeline.py agent_utils.py tests/test_office_pipeline.py
git commit -m "feat: add write_excel_document and write_excel agent tool"
```

---

## Task 10: Extend `/v1/document` endpoint in `gemma_bridge.py`

**Files:**

- Modify: `gemma_bridge.py` (lines 283–310)

- [ ] **Step 1: Read the current `upload_document` handler**

Open `gemma_bridge.py` and locate the `upload_document` function (around line 283). It currently calls `pdf_pipeline.ingest_pdf` unconditionally.

- [ ] **Step 2: Replace the routing logic in `upload_document`**

Find this block (lines ~284–309):

```python
@app.post("/v1/document")
async def upload_document(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        filename = file.filename or "document.pdf"

        doc = pdf_pipeline.ingest_pdf(file_bytes, filename)
```

Replace only the `doc = pdf_pipeline.ingest_pdf(...)` call and add the routing. The full updated function body becomes:

```python
@app.post("/v1/document")
async def upload_document(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        filename = file.filename or "document.pdf"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext in ("docx", "xlsx"):
            import office_pipeline
            doc = office_pipeline.ingest_office(file_bytes, filename)
        else:
            doc = pdf_pipeline.ingest_pdf(file_bytes, filename)
```

Leave the rest of the function (`if doc is None:` block onwards) unchanged.

- [ ] **Step 3: Smoke test the upload endpoint manually**

Ensure the bridge is running (kill existing processes and restart per your server restart procedure), then:

```bash
# Create a tiny test docx
python3 -c "
from docx import Document
import io
doc = Document()
doc.add_paragraph('Smoke test paragraph.')
doc.save('/tmp/smoke_test.docx')
"

# Upload it
curl -s -X POST http://localhost:9379/v1/document \
  -F "file=@/tmp/smoke_test.docx" | python3 -m json.tool
```

Expected: JSON response with `doc_id`, `filename: "smoke_test.docx"`, `chunk_count >= 1`.

- [ ] **Step 4: Smoke test Excel upload**

```bash
python3 -c "
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws['A1'] = 'Product'
ws['B1'] = 'Sales'
ws['A2'] = 'Widget'
ws['B2'] = 1500
wb.save('/tmp/smoke_test.xlsx')
"

curl -s -X POST http://localhost:9379/v1/document \
  -F "file=@/tmp/smoke_test.xlsx" | python3 -m json.tool
```

Expected: JSON response with `doc_id`, `filename: "smoke_test.xlsx"`, `chunk_count >= 1`.

- [ ] **Step 5: Commit**

```bash
git add gemma_bridge.py
git commit -m "feat: route .docx and .xlsx uploads through ingest_office in gemma_bridge"
```

---

## Task 11: Full test suite pass + final commit

- [ ] **Step 1: Run the full test suite**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run the smoke test script**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && python scripts/smoke_test.py
```

Expected: no failures.

- [ ] **Step 3: Final commit if any loose changes remain**

```bash
git status
# If anything is unstaged:
git add -p
git commit -m "chore: finalize Word and Excel support"
```
