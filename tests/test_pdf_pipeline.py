import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from pdf_pipeline import chunk_text, retrieve_chunks, build_document_context


def test_chunk_text_single_short_page():
    pages = [(1, "Hello world. This is a short page.")]
    chunks = chunk_text(pages, chunk_size=50, overlap=10)
    assert len(chunks) >= 1
    assert chunks[0]["text"] == "Hello world. This is a short page."
    assert chunks[0]["pages"] == [1]


def test_chunk_text_splits_long_page():
    words = ["word"] * 320
    pages = [(1, " ".join(words))]
    chunks = chunk_text(pages, chunk_size=300, overlap=50)
    assert len(chunks) >= 2


def test_chunk_text_overlap_repeats_words():
    words = list(range(350))
    text = " ".join(str(w) for w in words)
    pages = [(1, text)]
    chunks = chunk_text(pages, chunk_size=300, overlap=50)
    last_word_chunk0 = chunks[0]["text"].split()[-1]
    assert last_word_chunk0 in chunks[1]["text"].split()[:60]


def test_chunk_text_empty_pages_skipped():
    pages = [(1, ""), (2, "   "), (3, "Real content here.")]
    chunks = chunk_text(pages)
    assert len(chunks) == 1
    assert chunks[0]["pages"] == [3]


def _make_doc_store():
    chunks = [
        {"text": "The reset button is on the back panel.", "pages": [34]},
        {"text": "Battery life is approximately 8 hours.", "pages": [12]},
        {"text": "Connect via USB-C to charge the device.", "pages": [15]},
    ]
    embeddings = np.random.rand(3, 384).astype(np.float32)
    return {
        "abc123": {
            "filename": "manual.pdf",
            "chunks": chunks,
            "embeddings": embeddings,
        }
    }


def test_retrieve_chunks_returns_top_k():
    doc_store = _make_doc_store()
    results = retrieve_chunks("how do I reset", ["abc123"], doc_store, top_k=2)
    assert len(results) == 2
    assert "filename" in results[0]
    assert "text" in results[0]
    assert "pages" in results[0]


def test_retrieve_chunks_skips_missing_doc():
    doc_store = _make_doc_store()
    results = retrieve_chunks("anything", ["doesnotexist"], doc_store, top_k=5)
    assert results == []


def test_retrieve_chunks_empty_doc_ids():
    doc_store = _make_doc_store()
    results = retrieve_chunks("anything", [], doc_store, top_k=5)
    assert results == []


def test_build_document_context_format():
    chunks = [
        {"filename": "manual.pdf", "pages": [34], "text": "Reset is on back panel.", "score": 0.9},
        {"filename": "manual.pdf", "pages": [35], "text": "Device reboots after reset.", "score": 0.8},
    ]
    ctx = build_document_context(chunks)
    assert '[DOCUMENT CONTEXT — "manual.pdf"]' in ctx
    assert "[p.34]" in ctx
    assert "[END DOCUMENT CONTEXT]" in ctx
    assert "Answer the user" in ctx


def test_build_document_context_empty():
    assert build_document_context([]) == ""
