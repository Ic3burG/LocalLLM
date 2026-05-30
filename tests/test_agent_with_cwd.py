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


# --- media-tool validators honor session cwd ------------------------------

from agent_utils import _resolve_screenshot_path, _validate_user_file_path


def test_validate_user_file_path_honors_session_cwd(tmp_path: Path):
    (tmp_path / "photo.png").write_bytes(b"\x89PNG")
    token = current_cwd_var.set(str(tmp_path))
    try:
        resolved = _validate_user_file_path("photo.png")
        assert resolved == tmp_path / "photo.png"
    finally:
        current_cwd_var.reset(token)


def test_validate_user_file_path_still_allows_downloads(tmp_path: Path, monkeypatch):
    # Session cwd set, but legacy ~/Downloads paths must keep working
    monkeypatch.chdir(tmp_path)
    token = current_cwd_var.set(str(tmp_path))
    try:
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        sample = downloads / "test_localllm_sample.png"
        sample.write_bytes(b"\x89PNG")
        try:
            resolved = _validate_user_file_path(str(sample))
            assert resolved == sample.resolve()
        finally:
            sample.unlink(missing_ok=True)
    finally:
        current_cwd_var.reset(token)


def test_resolve_screenshot_path_uses_session_cwd_for_relative(tmp_path: Path):
    token = current_cwd_var.set(str(tmp_path))
    try:
        # Relative path with subdir → must resolve under session cwd, not Downloads
        (tmp_path / "shots").mkdir()
        target = _resolve_screenshot_path("shots/grab.png")
        assert target == (tmp_path / "shots" / "grab.png").resolve()
    finally:
        current_cwd_var.reset(token)


def test_resolve_screenshot_path_bare_basename_still_goes_to_downloads(tmp_path: Path):
    # Bare basename (no parent) → ~/Downloads — session cwd should not change this
    token = current_cwd_var.set(str(tmp_path))
    try:
        target = _resolve_screenshot_path("foo.png")
        assert target == Path.home() / "Downloads" / "foo.png"
    finally:
        current_cwd_var.reset(token)


# --- end-to-end via the FastAPI bridge -----------------------------------

import json

from fastapi.testclient import TestClient


async def _fake_react_with_one_step(
    task_id,
    messages,
    model_id,
    deep_think=False,
    cwd=None,
    cli_session_id=None,
):
    """Stand-in for react_loop_sse: invoke read_file under cwd context, emit done."""
    from agent import sse_queues
    from agent_utils import TOOL_REGISTRY

    q = sse_queues[task_id]
    token = current_cwd_var.set(cwd) if cwd else None
    try:
        tool = TOOL_REGISTRY["read_file"]
        try:
            content = await tool.fn("hello.txt")
        except Exception as exc:  # noqa: BLE001
            content = f"ERROR: {exc}"
        await q.put(
            json.dumps(
                {
                    "type": "step",
                    "tool": "read_file",
                    "args": {"0": "hello.txt"},
                    "result": content,
                    "elapsed_ms": 1,
                }
            )
        )
        await q.put(json.dumps({"type": "done", "message": "ok"}))
    finally:
        if token is not None:
            current_cwd_var.reset(token)
        await q.put(None)


def _drain_stream(client: TestClient, task_id: str, timeout: float = 5.0) -> list:
    events: list = []
    with client.stream("GET", f"/v1/agent/stream/{task_id}", timeout=timeout) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                payload = line[len("data: ") :]
                events.append(json.loads(payload))
                if events[-1].get("type") in ("done", "error"):
                    break
    return events


def test_agent_run_rejects_root_cwd():
    from gemma_bridge import app

    client = TestClient(app)
    for bad in ["/", "/Users", "/etc", "/private", "/var"]:
        resp = client.post("/v1/agent/run", json={"prompt": "hi", "cwd": bad})
        assert resp.status_code == 400, f"expected 400 for cwd={bad!r}"
        assert "top-level root" in resp.json()["detail"]


def test_agent_run_rejects_nonexistent_cwd(tmp_path):
    from gemma_bridge import app

    client = TestClient(app)
    nonexistent = str(tmp_path / "does_not_exist")
    resp = client.post("/v1/agent/run", json={"prompt": "hi", "cwd": nonexistent})
    assert resp.status_code == 400
    assert "does not exist" in resp.json()["detail"]


def test_agent_run_rejects_file_as_cwd(tmp_path):
    from gemma_bridge import app

    afile = tmp_path / "file.txt"
    afile.write_text("hi")

    client = TestClient(app)
    resp = client.post("/v1/agent/run", json={"prompt": "hi", "cwd": str(afile)})
    assert resp.status_code == 400
    assert "not a directory" in resp.json()["detail"]


def test_agent_run_with_cwd_sandboxes_tools(monkeypatch, tmp_path):
    (tmp_path / "hello.txt").write_text("from-session-cwd")
    monkeypatch.setattr("agent.react_loop_sse", _fake_react_with_one_step)

    from gemma_bridge import app

    client = TestClient(app)
    resp = client.post(
        "/v1/agent/run",
        json={
            "prompt": "read hello",
            "model_id": "gemma4-e4b",
            "cwd": str(tmp_path),
            "cli_session_id": "cli-1",
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    events = _drain_stream(client, task_id)
    step = next(e for e in events if e["type"] == "step")
    assert step["tool"] == "read_file"
    assert step["result"] == "from-session-cwd"
