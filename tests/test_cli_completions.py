from localllm.completions import slash_candidates


def test_slash_candidates_bare_returns_all():
    out = slash_candidates("/")
    names = [name for name, _ in out]
    assert "/help" in names
    assert len(names) >= 7


def test_slash_candidates_prefix_filters():
    out = slash_candidates("/mo")
    assert [name for name, _ in out] == ["/model"]


def test_slash_candidates_no_match():
    assert slash_candidates("/zzz") == []
