import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from fastapi.testclient import TestClient


def _make_docx_bytes(text: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _fake_embed(texts):
    # Stand in for the sentence-transformers model so the endpoint test does
    # not load it. Shape mirrors the real (n, dim) embedding matrix.
    return np.zeros((len(texts), 8), dtype=np.float32), 1.0


def _isolate_bridge_globals(monkeypatch, gemma_bridge):
    # The endpoint legitimately mutates module-global telemetry buffers and the
    # doc store. Swap in fresh ones (auto-restored by monkeypatch) so this
    # test's side effects don't leak into order-dependent tests like
    # test_bridge_stats::test_pipeline_telemetry_tracking.
    monkeypatch.setattr(gemma_bridge, "_ingestion_times", [])
    monkeypatch.setattr(gemma_bridge, "_embedding_latencies_ms", [])
    monkeypatch.setattr(gemma_bridge, "doc_store", {})


def test_upload_documents_batch_indexes_all_files(monkeypatch):
    import gemma_bridge
    import pdf_pipeline

    monkeypatch.setattr(pdf_pipeline, "embed_texts", _fake_embed)
    _isolate_bridge_globals(monkeypatch, gemma_bridge)
    client = TestClient(gemma_bridge.app)

    files = [
        (
            "files",
            ("a.docx", _make_docx_bytes("alpha body text"), "application/octet-stream"),
        ),
        (
            "files",
            ("b.docx", _make_docx_bytes("bravo body text"), "application/octet-stream"),
        ),
    ]
    resp = client.post("/v1/documents", files=files)

    assert resp.status_code == 200
    docs = resp.json()["documents"]
    # Results come back in upload order, each fully indexed.
    assert [d["filename"] for d in docs] == ["a.docx", "b.docx"]
    assert all(d["doc_id"] for d in docs)
    assert all(d["chunk_count"] >= 1 for d in docs)
    # And each landed in the shared doc store, retrievable for RAG.
    for d in docs:
        assert d["doc_id"] in gemma_bridge.doc_store


def test_upload_documents_reports_empty_file_without_failing_batch(monkeypatch):
    import gemma_bridge
    import pdf_pipeline

    monkeypatch.setattr(pdf_pipeline, "embed_texts", _fake_embed)
    _isolate_bridge_globals(monkeypatch, gemma_bridge)
    client = TestClient(gemma_bridge.app)

    files = [
        (
            "files",
            (
                "good.docx",
                _make_docx_bytes("real content here"),
                "application/octet-stream",
            ),
        ),
        ("files", ("junk.txt", b"not a document", "text/plain")),
    ]
    resp = client.post("/v1/documents", files=files)

    assert resp.status_code == 200
    docs = resp.json()["documents"]
    assert docs[0]["filename"] == "good.docx"
    assert docs[0]["doc_id"]
    # The unparseable file is reported, not crashed on.
    assert docs[1]["filename"] == "junk.txt"
    assert docs[1]["doc_id"] is None
    assert "no_text_found" in docs[1]["warnings"]
