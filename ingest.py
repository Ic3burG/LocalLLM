"""Parallel document ingestion.

Ingestion splits into two phases:

  * **parse**  — pure-Python text extraction + chunking (``pdfplumber`` /
    ``python-docx`` / ``openpyxl``). This is GIL-bound, CPU-bound work, so it
    is the part that genuinely benefits from process-level parallelism.
  * **embed**  — ``sentence-transformers`` encoding. This releases the GIL and
    is best run as a single batched call in the parent process; fanning it out
    would reload the model in every worker. It is intentionally NOT done here.

Only the parse phase is parallelised. Keep module-level imports light: under
the ``spawn`` start method (macOS default) every worker re-imports this module,
so the heavy ``pdfplumber`` / ``docx`` imports stay lazy inside ``parse_document``.
"""

from concurrent.futures import ProcessPoolExecutor


def parse_document(file_bytes: bytes, filename: str) -> dict | None:
    """Extract and chunk one document; perform NO embedding.

    Returns ``{"filename", "page_count", "chunks"}`` or ``None`` when the file
    type is unrecognised or yields no text. Defined at module level so it is
    picklable for ``ProcessPoolExecutor`` workers.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "docx":
        from office_pipeline import _format_word_metadata_text, extract_text_from_word

        sections, metadata = extract_text_from_word(file_bytes)
        pages = list(sections)
        if pages:
            extra = _format_word_metadata_text(metadata)
            if extra:
                pages.append((len(pages) + 1, extra))
    elif ext == "xlsx":
        from office_pipeline import _format_excel_metadata_text, extract_text_from_excel

        sheets, metadata = extract_text_from_excel(file_bytes)
        pages = [(i + 1, text) for i, (_, text) in enumerate(sheets)]
        extra = _format_excel_metadata_text(metadata)
        if extra:
            pages.append((len(pages) + 1, extra))
    elif ext == "pdf":
        from pdf_pipeline import extract_text_from_pdf

        pages = extract_text_from_pdf(file_bytes)
    else:
        return None

    if not pages:
        return None

    from pdf_pipeline import chunk_text

    chunks = chunk_text(pages)
    if not chunks:
        return None

    page_count = pages[-1][0] if pages else 0
    return {"filename": filename, "page_count": page_count, "chunks": chunks}


def parse_documents_parallel(
    files: list[tuple[bytes, str]],
    max_workers: int | None = None,
) -> list[dict | None]:
    """Parse many documents in parallel across a process pool.

    ``files`` is a list of ``(file_bytes, filename)`` pairs. Results are
    returned in the same order as the input; each element is the
    :func:`parse_document` result (or ``None``). Embedding is deliberately left
    to the caller so it can issue a single batched ``encode()`` over every
    chunk rather than reloading the model per worker.
    """
    if not files:
        return []

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        # ``map`` preserves input order; ``zip(*files)`` splits the pairs into a
        # bytes stream and a filename stream for the two positional args.
        return list(pool.map(parse_document, *zip(*files)))


def ingest_documents(
    files: list[tuple[bytes, str]],
    max_workers: int | None = None,
) -> list[dict | None]:
    """Fully ingest many documents: parallel parse + one batched embed.

    Parsing is fanned out across processes (CPU-bound, GIL-bound), then every
    chunk from every document is embedded in a *single* ``embed_texts`` call and
    the resulting vectors are sliced back to their source document. This loads
    the embedding model once, not once per worker.

    Returns a list aligned with ``files``; each element is a doc dict matching
    ``pdf_pipeline.ingest_pdf`` (``doc_id``, ``filename``, ``page_count``,
    ``chunks``, ``embeddings``, ``embedding_latency_ms``) or ``None`` when the
    file produced no text.
    """
    import uuid

    import pdf_pipeline

    parsed = parse_documents_parallel(files, max_workers=max_workers)
    results: list[dict | None] = [None] * len(parsed)

    # Flatten every chunk into one list, remembering each doc's [start, end)
    # span so the batched embeddings can be sliced back out in order.
    all_texts: list[str] = []
    spans: list[tuple[int, int, int]] = []  # (parsed_index, start, end)
    for idx, doc in enumerate(parsed):
        if doc is None:
            continue
        start = len(all_texts)
        all_texts.extend(c["text"] for c in doc["chunks"])
        spans.append((idx, start, len(all_texts)))

    if not all_texts:
        return results

    embeddings, emb_latency_ms = pdf_pipeline.embed_texts(all_texts)

    for idx, start, end in spans:
        doc = parsed[idx]
        results[idx] = {
            "doc_id": uuid.uuid4().hex[:8],
            "filename": doc["filename"],
            "page_count": doc["page_count"],
            "chunks": doc["chunks"],
            "embeddings": embeddings[start:end],
            "embedding_latency_ms": emb_latency_ms,
        }
    return results
