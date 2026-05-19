from citations import (
    assign_indices,
    dedupe_by_url,
    format_sources_for_model,
    trim_snippet,
)


def test_trim_snippet_caps_to_200_chars():
    long = "x" * 400
    out = trim_snippet(long)
    assert len(out) == 200
    assert out.endswith("…")


def test_trim_snippet_passes_short_strings_through():
    assert trim_snippet("hello") == "hello"


def test_trim_snippet_handles_none():
    assert trim_snippet(None) == ""


def test_assign_indices_starts_from_one_on_empty_run():
    new = [{"kind": "web", "title": "a", "url": "https://a.com"}]
    out = assign_indices(new, existing_count=0)
    assert out[0]["idx"] == 1


def test_assign_indices_continues_from_existing_count():
    new = [
        {"kind": "web", "title": "a", "url": "https://a.com"},
        {"kind": "web", "title": "b", "url": "https://b.com"},
    ]
    out = assign_indices(new, existing_count=3)
    assert [s["idx"] for s in out] == [4, 5]


def test_dedupe_by_url_keeps_lower_index():
    sources = [
        {"idx": 1, "kind": "web", "title": "a", "url": "https://x.com"},
        {"idx": 2, "kind": "web", "title": "a2", "url": "https://x.com"},
        {"idx": 3, "kind": "web", "title": "b", "url": "https://y.com"},
    ]
    out = dedupe_by_url(sources)
    urls = [s["url"] for s in out]
    assert urls == ["https://x.com", "https://y.com"]
    assert out[0]["idx"] == 1


def test_dedupe_by_url_leaves_file_and_rag_alone():
    sources = [
        {"idx": 1, "kind": "file", "title": "a.txt", "url": None},
        {"idx": 2, "kind": "file", "title": "a.txt", "url": None},
        {"idx": 3, "kind": "rag", "title": "doc.pdf", "url": None},
    ]
    out = dedupe_by_url(sources)
    assert len(out) == 3


def test_format_sources_for_model_renders_indexed_block():
    sources = [
        {
            "idx": 1,
            "kind": "web",
            "title": "ESPN — NBA Scores",
            "url": "https://espn.com/nba",
            "domain": "espn.com",
            "snippet": "Lakers 112, Celtics 108.",
        },
        {
            "idx": 2,
            "kind": "web",
            "title": "NBA.com Recap",
            "url": "https://nba.com/recap",
            "domain": "nba.com",
            "snippet": "LeBron scored 35.",
        },
    ]
    out = format_sources_for_model(sources)
    assert "[1] ESPN — NBA Scores (espn.com)" in out
    assert "Lakers 112, Celtics 108." in out
    assert "[2] NBA.com Recap (nba.com)" in out


def test_format_sources_for_model_handles_file_kind_without_domain():
    sources = [
        {
            "idx": 1,
            "kind": "file",
            "title": "src/app.py",
            "url": None,
            "domain": None,
            "snippet": "def main():",
        }
    ]
    out = format_sources_for_model(sources)
    assert "[1] src/app.py" in out
    assert "def main():" in out
