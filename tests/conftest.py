"""Shared pytest fixtures.

The most important one stubs the sentence-transformers embedding model. The
real ``embed_texts`` loads ``all-MiniLM-L6-v2``, which the test runner would
otherwise download from HuggingFace at runtime — making CI network-dependent
and flaky (it failed with HTTP 429 rate-limits). No unit test asserts on
embedding *values* (only shapes and counts), so a deterministic offline stub is
safe and keeps the suite fast and hermetic.
"""

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def stub_embedding_model(monkeypatch):
    """Replace ``pdf_pipeline.embed_texts`` with a deterministic, offline stub.

    This covers every ingestion/retrieval path, since they all route embedding
    through ``pdf_pipeline.embed_texts`` (``ingest_pdf``, ``ingest_office``,
    ``ingest_documents``, ``retrieve_chunks``). Tests needing specific embedding
    behaviour monkeypatch ``embed_texts`` themselves, which overrides this.
    """
    import pdf_pipeline

    def _fake_embed_texts(texts):
        # 384 columns matches all-MiniLM-L6-v2's real output width.
        return np.zeros((len(texts), 384), dtype=np.float32), 0.0

    monkeypatch.setattr(pdf_pipeline, "embed_texts", _fake_embed_texts)
