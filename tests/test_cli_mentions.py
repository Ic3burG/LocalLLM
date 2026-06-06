from localllm.mentions import MAX_FILE_BYTES, expand_mentions, human_size


def test_expands_single_file(tmp_path):
    (tmp_path / "a.txt").write_text("ALPHA")
    exp = expand_mentions("read @a.txt", tmp_path)
    assert "read @a.txt" in exp.text  # original line preserved
    assert '<file path="a.txt">' in exp.text
    assert "ALPHA" in exp.text
    assert exp.attached == [("a.txt", 5)]
    assert exp.warnings == []


def test_no_mentions_unchanged(tmp_path):
    exp = expand_mentions("just text", tmp_path)
    assert exp.text == "just text"
    assert exp.attached == []
    assert exp.warnings == []


def test_missing_file_warns(tmp_path):
    exp = expand_mentions("see @nope.txt", tmp_path)
    assert exp.text == "see @nope.txt"
    assert exp.attached == []
    assert any("not found" in w for w in exp.warnings)


def test_outside_cwd_rejected(tmp_path):
    (tmp_path.parent / "secret.txt").write_text("S")
    exp = expand_mentions("grab @../secret.txt", tmp_path)
    assert exp.attached == []
    assert any("outside" in w for w in exp.warnings)


def test_binary_refused(tmp_path):
    (tmp_path / "b.bin").write_bytes(b"\x00\x01\x02")
    exp = expand_mentions("x @b.bin", tmp_path)
    assert exp.attached == []
    assert any("binary" in w for w in exp.warnings)


def test_truncates_large_file(tmp_path):
    (tmp_path / "big.txt").write_text("y" * (MAX_FILE_BYTES + 100))
    exp = expand_mentions("@big.txt", tmp_path)
    assert "[truncated 100 bytes]" in exp.text
    assert exp.attached == [("big.txt", MAX_FILE_BYTES)]
    assert any("truncated" in w for w in exp.warnings)


def test_email_is_not_a_mention(tmp_path):
    exp = expand_mentions("ping a@b.com please", tmp_path)
    assert exp.text == "ping a@b.com please"
    assert exp.attached == []


def test_dedupes_repeated_mention(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    exp = expand_mentions("@a.txt and @a.txt", tmp_path)
    assert exp.attached == [("a.txt", 1)]


def test_human_size():
    assert human_size(500) == "500 B"
    assert human_size(1536).endswith("KB")
