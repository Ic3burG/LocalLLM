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
