from localllm.completions import (
    Trigger,
    apply_completion,
    fuzzy_find_files,
    parse_trigger,
    slash_candidates,
)


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


def test_parse_command_trigger():
    t = parse_trigger("/mo", 3)
    assert t == Trigger(kind="command", query="/mo", start=0, end=3)


def test_parse_command_stops_after_space():
    # caret is in the argument, not the command token
    assert parse_trigger("/model gem", 10) is None


def test_parse_file_trigger():
    t = parse_trigger("read @ser", 9)
    assert t == Trigger(kind="file", query="ser", start=5, end=9)


def test_parse_email_is_not_a_file_trigger():
    assert parse_trigger("mail a@b.com", 12) is None


def test_parse_plain_text_is_none():
    assert parse_trigger("hello", 5) is None


def test_apply_command_completion():
    t = parse_trigger("/mo", 3)
    text, cursor = apply_completion("/mo", t, "/model")
    assert text == "/model "
    assert cursor == 7


def test_apply_file_completion():
    t = parse_trigger("read @ser", 9)
    text, cursor = apply_completion("read @ser", t, "@src/server.js")
    assert text == "read @src/server.js "
    assert cursor == len("read @src/server.js ")


def test_fuzzy_finds_by_fragment(tmp_path):
    (tmp_path / "gemma-web").mkdir()
    (tmp_path / "gemma-web" / "server.js").write_text("x")
    (tmp_path / "localllm").mkdir()
    (tmp_path / "localllm" / "control_server.py").write_text("x")
    (tmp_path / "readme.md").write_text("x")
    out = fuzzy_find_files(tmp_path, "server")
    assert "gemma-web/server.js" in out
    assert "localllm/control_server.py" in out
    assert "readme.md" not in out


def test_fuzzy_prunes_ignore_dirs(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "y.js").write_text("x")
    (tmp_path / "keep.py").write_text("x")
    assert fuzzy_find_files(tmp_path, "") == ["keep.py"]


def test_fuzzy_basename_match_ranks_first(tmp_path):
    (tmp_path / "server.py").write_text("x")
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "server_helpers.py").write_text("x")
    out = fuzzy_find_files(tmp_path, "server")
    assert out[0] == "server.py"


def test_fuzzy_respects_limit(tmp_path):
    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("x")
    assert len(fuzzy_find_files(tmp_path, "", limit=5)) == 5
