import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out heavy/unavailable dependencies before importing gemma_bridge
from unittest.mock import MagicMock, AsyncMock, patch
import types

def _make_stub(*names):
    for name in names:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

_make_stub(
    "fastapi",
    "fastapi.responses",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "litert_lm",
    "uvicorn",
    "pdf_pipeline",
)

# FastAPI() is called at module level; make it return a proper mock
import fastapi as _fastapi_stub
_fastapi_stub.FastAPI.return_value = MagicMock()

import pytest

import importlib
import gemma_bridge
importlib.reload(gemma_bridge)


FAKE_RESPONSE = {"choices": [{"message": {"content": "hello"}}]}


@pytest.mark.asyncio
async def test_run_inference_routes_litert_for_default_model():
    with patch.object(gemma_bridge, "handle_litert_request", new_callable=AsyncMock, return_value=FAKE_RESPONSE) as mock_litert, \
         patch.object(gemma_bridge, "handle_mlx_request", new_callable=AsyncMock) as mock_mlx:
        result = await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-e4b")
        assert result == "hello"
        mock_litert.assert_called_once()
        mock_mlx.assert_not_called()


@pytest.mark.asyncio
async def test_run_inference_routes_mlx_for_mlx_model():
    with patch.object(gemma_bridge, "handle_mlx_request", new_callable=AsyncMock, return_value=FAKE_RESPONSE) as mock_mlx, \
         patch.object(gemma_bridge, "handle_litert_request", new_callable=AsyncMock) as mock_litert:
        result = await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-26b-mlx")
        assert result == "hello"
        mock_mlx.assert_called_once()
        mock_litert.assert_not_called()


@pytest.mark.asyncio
async def test_run_inference_raises_on_malformed_response():
    with patch.object(gemma_bridge, "handle_litert_request", new_callable=AsyncMock, return_value={}):
        with pytest.raises(RuntimeError, match="unexpected response structure"):
            await gemma_bridge.run_inference([{"role": "user", "content": "hi"}], "gemma4-e4b")


# ---------------------------------------------------------------------------
# Tool implementation tests
# ---------------------------------------------------------------------------

import subprocess
from unittest.mock import patch, MagicMock
import sys

import importlib
import agent as _agent_module
importlib.reload(_agent_module)


@pytest.mark.asyncio
async def test_read_file_returns_contents(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello world")
    from agent import _read_file
    result = await _read_file(str(f))
    assert result == "hello world"


@pytest.mark.asyncio
async def test_read_file_missing_returns_error():
    from agent import _read_file
    result = await _read_file("/nonexistent/path/xyz.txt")
    assert result.startswith("ERROR:")


@pytest.mark.asyncio
async def test_list_dir_returns_names(tmp_path):
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "b.txt").write_text("")
    from agent import _list_dir
    result = await _list_dir(str(tmp_path))
    assert "a.txt" in result
    assert "b.txt" in result


@pytest.mark.asyncio
async def test_list_dir_missing_returns_error():
    from agent import _list_dir
    result = await _list_dir("/nonexistent/xyz")
    assert result.startswith("ERROR:")


@pytest.mark.asyncio
async def test_write_file_creates_file(tmp_path):
    from agent import _write_file
    p = tmp_path / "out.txt"
    result = await _write_file(str(p), "content here")
    assert result.startswith("OK:")
    assert p.read_text() == "content here"


@pytest.mark.asyncio
async def test_write_file_creates_parent_dirs(tmp_path):
    from agent import _write_file
    p = tmp_path / "subdir" / "out.txt"
    result = await _write_file(str(p), "data")
    assert result.startswith("OK:")
    assert p.read_text() == "data"


@pytest.mark.asyncio
async def test_append_file_appends(tmp_path):
    from agent import _append_file
    p = tmp_path / "log.txt"
    p.write_text("line1\n")
    result = await _append_file(str(p), "line2\n")
    assert result.startswith("OK:")
    assert p.read_text() == "line1\nline2\n"


@pytest.mark.asyncio
async def test_shell_runs_command():
    from agent import _shell
    result = await _shell("echo hello")
    assert "hello" in result


@pytest.mark.asyncio
async def test_shell_timeout_returns_error():
    from agent import _shell
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 30)):
        result = await _shell("sleep 99")
    assert "timed out" in result.lower()


@pytest.mark.asyncio
async def test_list_crons_returns_output():
    from agent import _list_crons
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="0 9 * * * echo hi\n", returncode=0)
        result = await _list_crons()
    assert "echo hi" in result


@pytest.mark.asyncio
async def test_list_scheduled_tasks_empty(tmp_path, monkeypatch):
    import agent
    monkeypatch.setattr(agent, "SCHEDULER_TASKS_FILE", tmp_path / "tasks.json")
    result = await agent._list_scheduled_tasks()
    assert result == "[]"
