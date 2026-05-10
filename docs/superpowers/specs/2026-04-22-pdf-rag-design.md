# PDF RAG Feature Design

**Date:** 2026-04-22  
**Status:** Approved  
**Scope:** Add drag-and-drop PDF support to the Gemma 4 local chat interface via server-side semantic retrieval.

---

## Problem

Gemma cannot natively ingest PDF files. Users need to query product manuals (up to hundreds of pages) and receipts by asking questions about specific features or options. Sending full document text as context is not viable for large manuals due to context window limits.

## Solution

A server-side RAG (retrieval-augmented generation) pipeline:

1. PDF is uploaded to a new endpoint, text is extracted and embedded into a vector store.
2. At query time, the user's question is embedded and the most relevant chunks are retrieved and injected into the system prompt before Gemma generates a response.

---

## Architecture

```
PDF Drop
  └─► POST /v1/document
        ├─ pdfplumber extracts text per page
        ├─ text split into overlapping ~400-token chunks
        ├─ sentence-transformers embeds chunks in batch
        └─ stored in memory: doc_store[doc_id] = { chunks, embeddings, metadata }

User sends message with PDF attached
  └─► POST /v1/chat/completions  (modified)
        ├─ receives doc_ids: ["abc123"] alongside messages
        ├─ user query embedded with same model
        ├─ cosine similarity → top 5 chunks retrieved across all doc_ids
        ├─ chunks injected into system prompt as [DOCUMENT CONTEXT] block
        └─ Gemma generates a grounded response
```

Documents are stored in memory for the session. Restarting the bridge clears all documents. No disk writes, no external services.

---

## Backend Changes (`gemma_bridge.py`)

### New Dependencies

- `pdfplumber` — PDF text extraction, one page at a time
- `sentence-transformers` — local embedding model (`all-MiniLM-L6-v2`, ~80 MB)
- `numpy` — cosine similarity computation

### New: `POST /v1/document`

**Request:** `multipart/form-data` with a single `file` field (PDF binary).

**Processing:**

1. `pdfplumber` reads each page and extracts text.
2. Pages with no extractable text are skipped; if all pages are empty, a warning is returned.
3. Text is split into chunks of ~400 tokens with 50-token overlap. Each chunk is tagged with source page number(s).
4. All chunks are embedded in a single batch call to `all-MiniLM-L6-v2`.
5. `doc_store[doc_id] = { filename, chunks: [{ text, pages }], embeddings: np.ndarray, page_count }` stored in module-level dict.

**Response:**

```json
{
  "doc_id": "abc123",
  "filename": "ProX5000_Manual.pdf",
  "page_count": 312,
  "chunk_count": 847,
  "warnings": []
}
```

Possible warning values: `"no_text_found"` (scanned/image-only PDF).

### Modified: `POST /v1/chat/completions`

Request body gains an optional `doc_ids: string[]` field. Existing behaviour is unchanged when `doc_ids` is absent or empty.

When `doc_ids` is present:

1. The user's last message text is embedded with the same `all-MiniLM-L6-v2` model instance.
2. Cosine similarity is computed across all chunks from all referenced `doc_ids`.
3. Top 5 chunks are selected by score, preserving source filename and page labels.
4. A context block is prepended to the system prompt:

```
[DOCUMENT CONTEXT — "ProX5000_Manual.pdf"]
[p.34] Resetting to factory defaults: Press and hold the RESET button...
[p.35] The device will reboot and all user settings will be cleared...
...
[END DOCUMENT CONTEXT]
Answer the user's question using the context above where relevant.
```

If a `doc_id` no longer exists in memory (e.g., after bridge restart), it is silently skipped.

### Embedding Model Lifecycle

- Model is loaded on first PDF upload (`sentence-transformers` lazy import).
- Reused for all subsequent uploads and all query-time embeddings.
- No GPU required; runs on CPU.

---

## Frontend Changes (`gemma-web/index.html`)

### PDF Detection in `handleFiles()`

New branch for `file.type === 'application/pdf'` or `file.name.endsWith('.pdf')`:

1. Immediately render attachment chip in "Processing…" state.
2. Upload raw file to `POST http://localhost:3001/api/document` (proxied to bridge) via `FormData`.
3. On success: update chip to `filename.pdf · N pages indexed`, store `{ type: 'pdf', name, doc_id, page_count }` in `currentAttachments`.
4. On failure: update chip to `⚠ No text found (scanned)` or generic error; attachment is not added to `currentAttachments`.

### New Proxy Route in `server.js`

```
POST /api/document  →  multipart forward to  http://localhost:9379/v1/document
```

`multer` (or raw pipe) used to forward the binary without buffering into JSON.

### Message Send

When building the fetch body for `/api/chat`, collect `doc_ids` from any PDF entries in `currentAttachments` and include them in the request:

```json
{ "messages": [...], "model": "gemma4-e4b", "doc_ids": ["abc123"] }
```

The message content itself contains no injected text — retrieval happens server-side.

### Attachment Preview Chip States

```
Processing:  📄  filename.pdf          Processing…  ░░░░░
Ready:       📄  filename.pdf  ✕       312 pages · indexed
Error:       📄  filename.pdf  ✕       ⚠ No text found (scanned)
```

### Chat Bubble Display

PDF attachments render as a pill in the user's message bubble:

```
📄 ProX5000_Manual.pdf
```

No raw text shown in the UI — the document context is invisible to the user (it's in the system prompt).

---

## Chunking Strategy

- **Chunk size:** ~400 tokens (~300 words), chosen to fit comfortably within the context injected alongside a conversation.
- **Overlap:** 50 tokens between consecutive chunks to avoid cutting context at boundaries.
- **Unit:** Paragraph-aware where possible (split on double newlines first, then hard-split on token limit).
- **Small documents (receipts):** Typically 1–3 chunks; all chunks are always retrieved since top-5 covers everything.

---

## Error Handling

| Scenario                        | Behaviour                                                                                    |
| ------------------------------- | -------------------------------------------------------------------------------------------- |
| Scanned PDF (no text)           | Endpoint returns `warnings: ["no_text_found"]`; chip shows ⚠ state; no doc_id stored         |
| Bridge restart clears doc_store | Missing doc_ids silently skipped at query time; conversation continues without context       |
| Large manual (300+ pages)       | Embedding runs on CPU; frontend shows "Indexing… this may take a moment" if upload takes >3s |
| Multiple PDFs in one message    | doc_ids array accepted; top 5 retrieved across all documents, labelled by source filename    |
| Same PDF dropped twice          | New doc_id generated; re-indexed fresh                                                       |
| File > 50 MB                    | Rejected by existing Express body limit; frontend shows upload error                         |

---

## New Dependencies

| Package                 | Purpose                           | Size                               |
| ----------------------- | --------------------------------- | ---------------------------------- |
| `pdfplumber`            | PDF text extraction               | ~5 MB                              |
| `sentence-transformers` | Local embedding model             | ~80 MB model download on first use |
| `numpy`                 | Cosine similarity                 | already likely installed           |
| `multer` (Node)         | Multipart forwarding in server.js | ~100 KB                            |

All run fully offline after initial model download.

---

## Out of Scope

- OCR for scanned PDFs (would require `tesseract` integration)
- Persistent document storage across bridge restarts
- Per-conversation document isolation (all docs shared in memory for the session)
- PDF page image rendering or thumbnail previews
