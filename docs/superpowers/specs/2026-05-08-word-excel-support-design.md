# Word & Excel Support Design

**Date:** 2026-05-08  
**Status:** Approved

## Overview

Add comprehensive Word (`.docx`) and Excel (`.xlsx`) support to the Gemma4 local LLM agent. This includes:

- Agent tools for reading and writing both formats (with full annotation extraction and rich authoring)
- RAG ingestion pipeline for both formats (same chunking + embedding flow as PDF)
- Upload UI extended to accept both formats
- Path-based ingestion tools for the agent to ingest local files

## Architecture

### New module: `office_pipeline.py`

Mirrors `pdf_pipeline.py` in structure and return shape. `chunk_text()` and `embed_texts()` are imported from `pdf_pipeline.py` — no duplication.

```
office_pipeline.py
  extract_text_from_word(file_bytes)  → (list[(section_num, text)], metadata_dict)
  extract_text_from_excel(file_bytes) → (list[(sheet_name, text)], metadata_dict)
  ingest_office(file_bytes, filename) → {doc_id, filename, page_count, chunks, embeddings}
```

`ingest_office` returns the same dict shape as `ingest_pdf` so the rest of the codebase treats it identically.

### `agent_utils.py` additions

Four new async tool functions following the existing `_read_pdf` / `_write_pdf` pattern:

| Function | Risk | Description |
|---|---|---|
| `_read_word(path)` | safe | Extract full text + all annotations from a Word file |
| `_write_word(path, spec)` | risky | Create a Word file from a structured spec dict |
| `_read_excel(path)` | safe | Extract full text + all annotations from an Excel file |
| `_write_excel(path, spec)` | risky | Create an Excel file from a structured spec dict |

Registered via `register_tool()` at the bottom of `agent_utils.py`.

### Upload endpoint

The existing multipart upload endpoint in `gemma-web/` gains a MIME-type / file extension check:
- `.docx` / `application/vnd.openxmlformats-officedocument.wordprocessingml.document` → `ingest_office()`
- `.xlsx` / `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` → `ingest_office()`
- `.pdf` → `ingest_pdf()` (unchanged)

No UI changes needed — the existing upload widget accepts any file.

### Libraries added to `requirements.txt`

- `python-docx` — Word read/write
- `openpyxl` — Excel read/write
- `oletools` — embedded OLE object text extraction inside Excel files

## Reading & Extraction

### Word (`extract_text_from_word`)

Returns `(list[(section_num, text)], metadata_dict)`. Section numbers follow heading boundaries.

`metadata_dict` keys:

| Key | Content |
|---|---|
| `comments` | `[{author, date, text, ref_text}]` — comment body plus the text it references |
| `tracked_changes` | `[{author, date, type: "insert"\|"delete", text}]` — parsed from `<w:ins>`/`<w:del>` lxml nodes |
| `footnotes` | `[{ref_num, text}]` |
| `endnotes` | `[{ref_num, text}]` |
| `properties` | `{title, author, created, modified, subject, keywords, description}` from `core_properties` |

### Excel (`extract_text_from_excel`)

Returns `(list[(sheet_name, text)], metadata_dict)`. Each sheet's text is a TSV-style dump of cell coordinates + values.

`metadata_dict` keys:

| Key | Content |
|---|---|
| `cell_notes` | `[{sheet, cell, author, text}]` — legacy yellow-sticky notes |
| `threaded_comments` | `[{sheet, cell, thread: [{author, date, text}]}]` — modern comment threads with replies |
| `formulas` | `[{sheet, cell, formula, cached_value}]` |
| `embedded_objects` | `[{type, extracted_text}]` — text from OLE objects via oletools; macros flagged as `{type: "vba_macro", flagged: true}`, never executed |
| `properties` | `{title, author, created, modified, keywords}` |

### `_read_word` / `_read_excel` tool output format

Both tools format extraction results into a single readable text block: body text first, followed by clearly labelled annotation sections (## Comments, ## Tracked Changes, etc.). This is what the agent receives.

## Writing (Rich Authoring)

Both write tools accept a JSON-serializable `spec` dict.

### `_write_word(path, spec)`

| Spec key | Type | Behavior |
|---|---|---|
| `properties` | dict | `{title, author, subject, keywords}` — document metadata |
| `sections` | list | Ordered list of content blocks |

Content block types:

| `type` | Fields |
|---|---|
| `"heading"` | `level` (1–6), `text` |
| `"paragraph"` | `text`, `bold`, `italic`, `underline` |
| `"table"` | `rows` (list of lists), `header_row` (bool), `merge` (list of `{row, col, rowspan, colspan}`) |
| `"footnote"` | `ref_paragraph` (int index), `text` |
| `"endnote"` | `ref_paragraph` (int index), `text` |

### `_write_excel(path, spec)`

| Spec key | Type | Behavior |
|---|---|---|
| `properties` | dict | `{title, author, subject, keywords}` — document metadata |
| `sheets` | list | List of sheet definitions |

Sheet definition:

| Field | Type | Content |
|---|---|---|
| `name` | str | Sheet tab name |
| `rows` | list of lists | Each cell: `{value, formula, bold, italic, bg_color, border, number_format, alignment}` |
| `merges` | list | `[{range}]` e.g. `"A1:C3"` |
| `charts` | list | `[{type: "bar"\|"line"\|"pie", title, data_range}]` |

Both write tools return the written file path on success, or an `"ERROR: ..."` string on failure.

## Error Handling

Follows the existing `agent_utils.py` pattern throughout:

- All tool functions wrap logic in `try/except`, log via `logger.error()` with structured `extra={}` kwargs
- Return `"ERROR: ..."` string to the agent — never raise
- Corrupt / password-protected files return a descriptive error; processing does not crash
- Missing annotations (e.g. a Word file with no comments) return empty lists — not an error
- Macros detected in Excel: flagged in `embedded_objects`, processing continues normally

## Testing

New file: `tests/test_office_pipeline.py`, mirroring `tests/test_pdf_pipeline.py`.

| Test | Coverage |
|---|---|
| `test_read_word_body` | Paragraph and heading extraction |
| `test_read_word_annotations` | Comments, tracked changes, footnotes, endnotes, metadata |
| `test_read_excel_cells` | Cell values, formulas, cached values |
| `test_read_excel_annotations` | Cell notes, threaded comments, embedded objects, macro flagging |
| `test_write_word_roundtrip` | Write then re-read, verify body + table structure |
| `test_write_excel_roundtrip` | Write then re-read, verify cells + chart presence |
| `test_ingest_office_word` | Returns same shape dict as `ingest_pdf` |
| `test_ingest_office_excel` | Returns same shape dict as `ingest_pdf` |

## Files to Create / Modify

| File | Action |
|---|---|
| `office_pipeline.py` | Create |
| `agent_utils.py` | Modify — add 4 tool functions + registrations |
| `gemma-web/server.js` (or equivalent) | Modify — extend upload endpoint MIME check |
| `requirements.txt` | Modify — add python-docx, openpyxl, oletools |
| `tests/test_office_pipeline.py` | Create |
