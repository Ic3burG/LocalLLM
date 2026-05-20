import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from pdf_pipeline import (
    build_document_context,
    build_numbered_document_context,
    chunk_text,
    chunks_to_sources,
    retrieve_chunks,
)


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
    results, _ = retrieve_chunks("how do I reset", ["abc123"], doc_store, top_k=2)
    assert len(results) == 2
    assert "filename" in results[0]
    assert "text" in results[0]
    assert "pages" in results[0]


def test_retrieve_chunks_skips_missing_doc():
    doc_store = _make_doc_store()
    results, _ = retrieve_chunks("anything", ["doesnotexist"], doc_store, top_k=5)
    assert results == []


def test_retrieve_chunks_empty_doc_ids():
    doc_store = _make_doc_store()
    results, _ = retrieve_chunks("anything", [], doc_store, top_k=5)
    assert results == []


def test_build_document_context_format():
    chunks = [
        {
            "filename": "manual.pdf",
            "pages": [34],
            "text": "Reset is on back panel.",
            "score": 0.9,
        },
        {
            "filename": "manual.pdf",
            "pages": [35],
            "text": "Device reboots after reset.",
            "score": 0.8,
        },
    ]
    ctx = build_document_context(chunks)
    assert '[DOCUMENT CONTEXT — "manual.pdf"]' in ctx
    assert "[p.34]" in ctx
    assert "[END DOCUMENT CONTEXT]" in ctx
    assert "Answer the user" in ctx


def test_build_document_context_empty():
    assert build_document_context([]) == ""


def _fake_chunks():
    return [
        {
            "filename": "annual_report.pdf",
            "pages": [4],
            "text": "Q3 revenue grew 18% year-over-year.",
            "score": 0.91,
        },
        {
            "filename": "annual_report.pdf",
            "pages": [7, 8],
            "text": "Operating margin expanded to 22.3%.",
            "score": 0.83,
        },
    ]


def test_build_numbered_document_context_format():
    ctx = build_numbered_document_context(_fake_chunks())
    assert "[1] (annual_report.pdf, p.4):" in ctx
    assert "Q3 revenue grew 18% year-over-year." in ctx
    assert "[2] (annual_report.pdf, p.7, p.8):" in ctx
    assert "RELEVANT EXCERPTS" in ctx


def test_chunks_to_sources_yields_rag_records():
    sources = chunks_to_sources(_fake_chunks())
    assert len(sources) == 2
    s0 = sources[0]
    assert s0["kind"] == "rag"
    assert s0["title"] == "annual_report.pdf"
    assert s0["meta"]["page"] == 4
    assert "Q3 revenue" in s0["snippet"]
    assert s0["url"] is None


def test_build_numbered_document_context_empty():
    assert build_numbered_document_context([]) == ""
