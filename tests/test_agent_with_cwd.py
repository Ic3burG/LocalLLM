from pathlib import Path

import pytest

from agent_utils import validate_path
from logging_config import current_cwd_var


def test_validate_path_allows_paths_under_current_cwd_var(tmp_path: Path):
    (tmp_path / "hello.txt").write_text("hi")
    token = current_cwd_var.set(str(tmp_path))
    try:
        resolved = validate_path("hello.txt")
        assert resolved == tmp_path / "hello.txt"
    finally:
        current_cwd_var.reset(token)


def test_validate_path_still_rejects_outside_both(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    token = current_cwd_var.set(str(tmp_path))
    outside = "/etc/passwd"
    try:
        with pytest.raises(PermissionError):
            validate_path(outside)
    finally:
        current_cwd_var.reset(token)


def test_validate_path_falls_back_to_cwd_when_var_unset(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.txt").write_text("hi")
    assert validate_path("x.txt") == tmp_path / "x.txt"


def test_validate_path_absolute_in_session_cwd(tmp_path: Path):
    sub = tmp_path / "proj"
    sub.mkdir()
    (sub / "README.md").write_text("hello")
    token = current_cwd_var.set(str(sub))
    try:
        assert validate_path(str(sub / "README.md")) == sub / "README.md"
    finally:
        current_cwd_var.reset(token)
