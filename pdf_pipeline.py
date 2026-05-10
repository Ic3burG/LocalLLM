import io
import uuid
import time
import numpy as np

_embedding_model = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def extract_text_from_pdf(file_bytes: bytes) -> list[tuple[int, str]]:
    import pdfplumber
    pages = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((i, text))
    return pages


def chunk_text(
    pages: list[tuple[int, str]],
    chunk_size: int = 300,
    overlap: int = 50,
) -> list[dict]:
    chunks = []
    for page_num, text in pages:
        if not text.strip():
            continue
        words = text.split()
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_words = words[start:end]
            chunks.append({"text": " ".join(chunk_words), "pages": [page_num]})
            if end == len(words):
                break
            start += chunk_size - overlap
    return chunks


def embed_texts(texts: list[str]) -> tuple[np.ndarray, float]:
    """Returns (embeddings, latency_ms)"""
    t0 = time.monotonic()
    model = get_embedding_model()
    embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    latency_ms = (time.monotonic() - t0) * 1000
    return embeddings, latency_ms


def ingest_pdf(file_bytes: bytes, filename: str) -> dict | None:
    pages = extract_text_from_pdf(file_bytes)
    if not pages:
        return None

    chunks = chunk_text(pages)
    texts = [c["text"] for c in chunks]
    embeddings, emb_latency_ms = embed_texts(texts)

    doc_id = uuid.uuid4().hex[:8]
    page_count = pages[-1][0] if pages else 0
    return {
        "doc_id": doc_id,
        "filename": filename,
        "page_count": page_count,
        "chunks": chunks,
        "embeddings": embeddings,
        "embedding_latency_ms": emb_latency_ms
    }


def retrieve_chunks(
    query: str,
    doc_ids: list[str],
    doc_store: dict,
    top_k: int = 5,
) -> tuple[list[dict], float]:
    """Returns (chunks, query_embedding_latency_ms)"""
    if not doc_ids:
        return [], 0

    embs_data, emb_latency_ms = embed_texts([query])
    query_vec = embs_data[0]
    scored = []
    for doc_id in doc_ids:
        doc = doc_store.get(doc_id)
        if not doc:
            continue
        embs = doc["embeddings"]
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        safe_norms = np.where(norms == 0, 1, norms)
        normed = embs / safe_norms
        q_norm = query_vec / (np.linalg.norm(query_vec) or 1)
        sims = normed @ q_norm
        for i, score in enumerate(sims):
            scored.append((float(score), doc["filename"], doc["chunks"][i]))

    scored.sort(key=lambda x: x[0], reverse=True)
    chunks = [{"score": s, "filename": fn, **ch} for s, fn, ch in scored[:top_k]]
    return chunks, emb_latency_ms


def build_document_context(chunks: list[dict]) -> str:
    if not chunks:
        return ""
    by_file: dict[str, list] = {}
    for ch in chunks:
        by_file.setdefault(ch["filename"], []).append(ch)

    parts = []
    for filename, file_chunks in by_file.items():
        parts.append(f'[DOCUMENT CONTEXT — "{filename}"]')
        for ch in file_chunks:
            pages_label = ", ".join(f"p.{p}" for p in ch["pages"])
            parts.append(f"[{pages_label}] {ch['text']}")
        parts.append("[END DOCUMENT CONTEXT]")
    parts.append("Answer the user's question using the context above where relevant.")
    return "\n".join(parts)
