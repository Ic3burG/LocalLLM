"""Benchmark: serial per-file ingest vs. parallel batched ingest.

Measures the real wall-clock difference between the old upload path (one
``pdf_pipeline.ingest_pdf`` call per file, sequential) and the new path
(``ingest.ingest_documents`` — parse fanned across CPU cores + one batched
embed). The embedding model is warmed up first so model-load time is charged to
neither path.

Not a pytest test (the name avoids collection). Run directly:

    .venv/bin/python scripts/benchmark_ingest.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fpdf import FPDF


def make_pdf(n_pages: int, words_per_page: int, seed: int) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    for p in range(n_pages):
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        words = [f"doc{seed}p{p}w{i}" for i in range(words_per_page)]
        pdf.multi_cell(0, 6, " ".join(words))
    return bytes(pdf.output())


def main() -> None:
    n_files = 8
    n_pages = 15
    words_per_page = 220

    files = [
        (make_pdf(n_pages, words_per_page, s), f"bench_{s}.pdf") for s in range(n_files)
    ]
    total_kib = sum(len(b) for b, _ in files) / 1024
    print(
        f"{n_files} PDFs, {n_pages} pages each, ~{words_per_page} words/page, "
        f"{total_kib:.0f} KiB total"
    )

    import ingest
    import pdf_pipeline

    # Warm up the embedding model so its one-time load skews neither path.
    pdf_pipeline.embed_texts(["warmup"])

    # --- Serial: the old path, one ingest_pdf per file ---
    t0 = time.monotonic()
    serial = [pdf_pipeline.ingest_pdf(b, name) for b, name in files]
    serial_s = time.monotonic() - t0
    serial_chunks = sum(len(d["chunks"]) for d in serial if d)

    # --- Parallel: parse fanned across processes + one batched embed ---
    t0 = time.monotonic()
    parallel = ingest.ingest_documents(files, max_workers=os.cpu_count())
    parallel_s = time.monotonic() - t0
    parallel_chunks = sum(len(d["chunks"]) for d in parallel if d)

    assert serial_chunks == parallel_chunks, (
        f"chunk mismatch: serial={serial_chunks} parallel={parallel_chunks}"
    )

    print(f"serial    : {serial_s:6.2f}s   ({serial_chunks} chunks)")
    print(f"parallel  : {parallel_s:6.2f}s   ({parallel_chunks} chunks)")
    print(f"speedup   : {serial_s / parallel_s:5.2f}x   on {os.cpu_count()} cores")


if __name__ == "__main__":
    main()
