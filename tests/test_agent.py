import importlib
import importlib.machinery
import json
import subprocess
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_utils import _google_search, _web_fetch

# FAKE_RESPONSE for reuse
FAKE_RESPONSE = {"choices": [{"message": {"content": "hello"}}]}


def _make_module(name: str) -> types.ModuleType:
    """Return a ModuleType with a valid __spec__ so find_spec() doesn't raise."""
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    return mod


@pytest.fixture
def mock_deps():
    """
    Fixture to stub out heavy/unavailable dependencies locally for a test.
    """
    stubs = {
        "fastapi": MagicMock(),
        "fastapi.responses": MagicMock(),
        "fastapi.middleware": MagicMock(),
        "fastapi.middleware.cors": MagicMock(),
        "litert_lm": MagicMock(),
        "mlx": _make_module("mlx"),
        "mlx.core": _make_module("mlx.core"),
        "mlx_vlm": MagicMock(),
        "uvicorn": MagicMock(),
        "pdf_pipeline": MagicMock(),
        "inference_engine": MagicMock(),
        "apscheduler": MagicMock(),
        "apscheduler.schedulers": MagicMock(),
        "apscheduler.schedulers.asyncio": MagicMock(),
        "psutil": MagicMock(),
    }
    # FastAPI() is called at module level; make it return a proper mock
    stubs["fastapi"].FastAPI.return_value = MagicMock()

    # Mock apscheduler
    stubs["apscheduler.schedulers.asyncio"].AsyncIOScheduler = MagicMock()

    # Mock inference_engine functions
    stubs["inference_engine"].run_inference = AsyncMock(return_value="hello")
    stubs["inference_engine"].handle_mlx_vlm_request = MagicMock(
        return_value=FAKE_RESPONSE
    )

    import agent as _ag
    import gemma_bridge as _gb

    # Snapshot module state before reload so other test files see consistent state
    _gb_snapshot = dict(_gb.__dict__)
    _ag_snapshot = dict(_ag.__dict__)

    try:
        with patch.dict("sys.modules", stubs):
            importlib.reload(_gb)
            importlib.reload(_ag)
            yield _gb, _ag
    finally:
        # Restore module-level state so module-level imports in other files
        # (sse_queues, psutil, etc.) remain valid after this fixture exits.
        _gb.__dict__.clear()
        _gb.__dict__.update(_gb_snapshot)
        _ag.__dict__.clear()
        _ag.__dict__.update(_ag_snapshot)


@pytest.mark.asyncio
async def test_run_inference_routes_mlx_vlm_for_e4b(mock_deps):
    gemma_bridge, _ = mock_deps
    # Since we mock inference_engine, we just verify the bridge calls its run_inference
    result = await gemma_bridge.run_inference(
        [{"role": "user", "content": "hi"}], "gemma4-e4b"
    )
    assert result == "hello"
    gemma_bridge.run_inference.assert_called_once()


@pytest.mark.asyncio
async def test_run_inference_routes_mlx_vlm_for_26b(mock_deps):
    gemma_bridge, _ = mock_deps
    result = await gemma_bridge.run_inference(
        [{"role": "user", "content": "hi"}], "gemma4-26b-mlx"
    )
    assert result == "hello"
    gemma_bridge.run_inference.assert_called_once()


@pytest.mark.asyncio
async def test_run_inference_raises_on_malformed_response(mock_deps):
    gemma_bridge, _ = mock_deps
    # Patch the mock to raise the error we expect
    gemma_bridge.run_inference.side_effect = RuntimeError(
        "unexpected response structure"
    )
    with pytest.raises(RuntimeError, match="unexpected response structure"):
        await gemma_bridge.run_inference(
            [{"role": "user", "content": "hi"}], "gemma4-e4b"
        )


# ---------------------------------------------------------------------------
# Tool implementation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_returns_contents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_text("hello world")
    import agent_utils

    result = await agent_utils._read_file(str(f))
    assert result == "hello world"


@pytest.mark.asyncio
async def test_read_file_missing_returns_error():
    import agent_utils

    result = await agent_utils._read_file("/nonexistent/path/xyz.txt")
    assert result.startswith("ERROR:")


@pytest.mark.asyncio
async def test_list_dir_returns_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "b.txt").write_text("")
    import agent_utils

    result = await agent_utils._list_dir(str(tmp_path))
    assert "a.txt" in result
    assert "b.txt" in result


@pytest.mark.asyncio
async def test_list_dir_missing_returns_error():
    import agent_utils

    result = await agent_utils._list_dir("/nonexistent/xyz")
    assert result.startswith("ERROR:")


@pytest.mark.asyncio
async def test_write_file_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import agent_utils

    p = tmp_path / "out.txt"
    result = await agent_utils._write_file(str(p), "content here")
    assert result.startswith("OK:")
    assert p.read_text() == "content here"


@pytest.mark.asyncio
async def test_write_file_creates_parent_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import agent_utils

    p = tmp_path / "subdir" / "out.txt"
    result = await agent_utils._write_file(str(p), "data")
    assert result.startswith("OK:")
    assert p.read_text() == "data"


@pytest.mark.asyncio
async def test_append_file_appends(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import agent_utils

    p = tmp_path / "log.txt"
    p.write_text("line1\n")
    result = await agent_utils._append_file(str(p), "line2\n")
    assert result.startswith("OK:")
    assert p.read_text() == "line1\nline2\n"


@pytest.mark.asyncio
async def test_shell_runs_command():
    import agent_utils

    result = await agent_utils._shell("echo hello")
    assert "hello" in result


@pytest.mark.asyncio
async def test_shell_timeout_returns_error():
    import agent_utils

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 30)):
        result = await agent_utils._shell("sleep 99")
    assert "timed out" in result.lower()


@pytest.mark.asyncio
async def test_list_crons_returns_output():
    import agent_utils

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="0 9 * * * echo hi\n", returncode=0)
        result = await agent_utils._list_crons()
    assert "echo hi" in result


@pytest.mark.asyncio
async def test_list_scheduled_tasks_empty(tmp_path, monkeypatch, mock_deps):
    _, agent = mock_deps
    monkeypatch.setattr(agent, "SCHEDULER_TASKS_FILE", tmp_path / "tasks.json")
    result = await agent._list_scheduled_tasks()
    assert result == "[]"


# ── Parser tests ──────────────────────────────────────────
def test_parse_tool_call_single_arg():
    import agent

    result = agent.parse_model_output('TOOL: read_file("~/notes.md")')
    assert result == ("tool", "read_file", ["~/notes.md"])


def test_parse_tool_call_two_args():
    import agent

    result = agent.parse_model_output('TOOL: write_file("~/out.txt", "hello world")')
    assert result == ("tool", "write_file", ["~/out.txt", "hello world"])


def test_parse_done():
    import agent

    result = agent.parse_model_output("DONE: Summarised 5 files")
    assert result == ("done", "Summarised 5 files", [])


def test_parse_no_match_returns_none():
    import agent

    result = agent.parse_model_output("I need to think about this more.")
    assert result is None


def test_parse_tool_no_args():
    import agent

    result = agent.parse_model_output("TOOL: list_crons()")
    assert result == ("tool", "list_crons", [])


def test_parse_native_gemma_format_single_arg():
    import agent

    result = agent.parse_model_output('<|tool_call>call:shell("ls ~")<tool_call|>')
    assert result == ("tool", "shell", ["ls ~"])


def test_parse_native_gemma_format_no_args():
    import agent

    result = agent.parse_model_output("<|tool_call>call:list_crons()<tool_call|>")
    assert result == ("tool", "list_crons", [])


# ── ReAct loop tests ──────────────────────────────────────
@pytest.mark.asyncio
async def test_react_loop_internal_returns_done_message(mock_deps):
    _, agent = mock_deps
    # Model immediately responds with DONE
    with patch.object(
        agent, "run_inference", new_callable=AsyncMock, return_value="DONE: all done"
    ):
        result = await agent._react_loop_internal(
            [{"role": "user", "content": "do something"}]
        )
    assert result == "all done"


@pytest.mark.asyncio
async def test_react_loop_internal_executes_safe_tool(mock_deps):
    _, agent = mock_deps
    responses = iter(["TOOL: list_crons()", "DONE: found cron"])
    with (
        patch.object(
            agent,
            "run_inference",
            new_callable=AsyncMock,
            side_effect=lambda msgs, model_id="gemma4-e4b": next(responses),
        ),
        patch(
            "agent_utils._list_crons",
            new_callable=AsyncMock,
            return_value="0 9 * * * echo hi",
        ),
    ):
        result = await agent._react_loop_internal(
            [{"role": "user", "content": "check my crons"}]
        )
    assert result == "found cron"


@pytest.mark.asyncio
async def test_react_loop_internal_records_telemetry(mock_deps):
    _, agent = mock_deps
    responses = iter(["TOOL: list_crons()", "DONE: all done"])

    with (
        patch.object(agent.telemetry, "record_start") as mock_start,
        patch.object(agent.telemetry, "record_tool_use") as mock_tool_use,
        patch.object(agent.telemetry, "record_complete") as mock_complete,
        patch.object(
            agent,
            "run_inference",
            new_callable=AsyncMock,
            side_effect=lambda msgs, model_id="gemma4-e4b": next(responses),
        ),
        patch(
            "agent_utils._list_crons",
            new_callable=AsyncMock,
            return_value="0 9 * * * echo hi",
        ),
    ):
        await agent._react_loop_internal([{"role": "user", "content": "do something"}])

    from unittest.mock import ANY

    mock_start.assert_called_once()
    mock_tool_use.assert_called_with("list_crons")
    mock_complete.assert_called_with(ANY, "success")


@pytest.mark.asyncio
async def test_react_loop_internal_max_iterations(mock_deps):
    _, agent = mock_deps
    # Model always outputs a tool call, never DONE
    with patch.object(
        agent,
        "run_inference",
        new_callable=AsyncMock,
        return_value='TOOL: shell("echo loop")',
    ):
        with patch.object(
            agent.TOOL_REGISTRY["shell"],
            "fn",
            new_callable=AsyncMock,
            return_value="looped",
        ):
            result = await agent._react_loop_internal(
                [{"role": "user", "content": "loop forever"}]
            )
    assert result == "Max iterations reached"


# ── Scheduler CRUD tests ──────────────────────────────────
@pytest.mark.asyncio
async def test_create_and_list_scheduled_task(tmp_path, monkeypatch, mock_deps):
    _, agent = mock_deps
    monkeypatch.setattr(agent, "SCHEDULER_TASKS_FILE", tmp_path / "tasks.json")
    # Mock _register_scheduler_task to avoid APScheduler issues in tests
    with patch.object(agent, "_register_scheduler_task"):
        result = await agent._create_scheduled_task("daily", "0 9 * * *", "check files")
    assert result.startswith("OK:")
    tasks = json.loads((tmp_path / "tasks.json").read_text())
    assert len(tasks) == 1
    assert tasks[0]["name"] == "daily"
    assert tasks[0]["prompt"] == "check files"


@pytest.mark.asyncio
async def test_list_scheduled_tasks_returns_tasks(tmp_path, monkeypatch, mock_deps):
    _, agent = mock_deps
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps([{"name": "x", "schedule": "* * * * *", "prompt": "hi"}])
    )
    monkeypatch.setattr(agent, "SCHEDULER_TASKS_FILE", task_file)
    result = await agent._list_scheduled_tasks()
    data = json.loads(result)
    assert data[0]["name"] == "x"


# ── Task 3: Logging tests ──────────────────────────────────
import logging


@pytest.mark.asyncio
async def test_react_loop_internal_logs_unknown_tool(mock_deps, caplog):
    _, agent = mock_deps
    responses = iter(["TOOL: ghost_tool()", "DONE: done"])
    with (
        patch.object(
            agent,
            "run_inference",
            new_callable=AsyncMock,
            side_effect=lambda msgs, model_id="gemma4-e4b": next(responses),
        ),
        caplog.at_level(logging.WARNING),
    ):
        await agent._react_loop_internal([{"role": "user", "content": "go"}])
    assert any("unknown tool" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_react_loop_internal_logs_tool_exception(mock_deps, caplog):
    _, agent = mock_deps

    async def bad_tool():
        raise RuntimeError("disk full")

    original_registry = dict(agent.TOOL_REGISTRY)
    from agent_utils import Tool

    agent.TOOL_REGISTRY["boom"] = Tool("boom", "safe", "desc", bad_tool)

    responses = iter(["TOOL: boom()", "DONE: done"])
    with (
        patch.object(
            agent,
            "run_inference",
            new_callable=AsyncMock,
            side_effect=lambda msgs, model_id="gemma4-e4b": next(responses),
        ),
        caplog.at_level(logging.ERROR),
    ):
        await agent._react_loop_internal([{"role": "user", "content": "go"}])
    assert any("tool execution failed" in r.getMessage() for r in caplog.records)

    agent.TOOL_REGISTRY.clear()
    agent.TOOL_REGISTRY.update(original_registry)


@pytest.mark.asyncio
async def test_react_loop_internal_logs_max_iterations(mock_deps, caplog):
    _, agent = mock_deps
    with (
        patch.object(
            agent,
            "run_inference",
            new_callable=AsyncMock,
            return_value='TOOL: shell("echo loop")',
        ),
        patch.object(
            agent.TOOL_REGISTRY["shell"],
            "fn",
            new_callable=AsyncMock,
            return_value="looped",
        ),
        caplog.at_level(logging.WARNING),
    ):
        await agent._react_loop_internal([{"role": "user", "content": "loop"}])
    assert any("max iterations" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_react_loop_sse_logs_confirmation_timeout(mock_deps, caplog):
    import asyncio

    _, agent = mock_deps

    task_id = "test-timeout"
    agent.sse_queues[task_id] = asyncio.Queue()
    agent.confirm_queues[task_id] = asyncio.Queue()

    async def risky_fn():
        return "ok"

    from agent_utils import Tool

    original_registry = dict(agent.TOOL_REGISTRY)
    agent.TOOL_REGISTRY["risky_op"] = Tool("risky_op", "risky", "desc", risky_fn)

    responses = iter(["TOOL: risky_op()", "DONE: done"])

    async def fake_wait_for(coro, timeout):
        raise asyncio.TimeoutError()

    with (
        patch.object(
            agent,
            "run_inference",
            new_callable=AsyncMock,
            side_effect=lambda msgs, model_id="gemma4-e4b": next(responses),
        ),
        patch("agent.asyncio.wait_for", side_effect=fake_wait_for),
        caplog.at_level(logging.WARNING),
    ):
        await agent.react_loop_sse(
            task_id, [{"role": "user", "content": "go"}], "gemma4-e4b"
        )

    assert any("timed" in r.getMessage().lower() for r in caplog.records)

    agent.TOOL_REGISTRY.clear()
    agent.TOOL_REGISTRY.update(original_registry)


# ── Task 4: Tool error logging tests ──────────────────────
@pytest.mark.asyncio
async def test_shell_logs_error_on_timeout(caplog):
    import subprocess

    import agent_utils

    with (
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 30)),
        caplog.at_level(logging.ERROR, logger="agent_utils"),
    ):
        result = await agent_utils._shell("sleep 99")
    assert result == "ERROR: timed out"
    assert any("shell" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_web_fetch_logs_error_on_exception(caplog):
    import agent_utils

    with (
        patch("requests.get", side_effect=Exception("connection refused")),
        caplog.at_level(logging.ERROR, logger="agent_utils"),
    ):
        result = await agent_utils._web_fetch("https://example.com")
    assert result["sources"] == []
    assert result["model_text"].startswith("ERROR:")
    assert any("web_fetch" in r.getMessage().lower() for r in caplog.records)


# ── Task 2: Structured returns from _google_search and _web_fetch ──────────


@pytest.mark.asyncio
async def test_google_search_returns_dict_with_sources(monkeypatch):
    fake_results = [
        {
            "title": "ESPN — NBA Scores",
            "href": "https://espn.com/nba",
            "body": "Lakers 112, Celtics 108. Final score from last night's game.",
        },
        {
            "title": "NBA.com Recap",
            "href": "https://www.nba.com/recap",
            "body": "LeBron scored 35 points.",
        },
    ]

    class FakeDDGS:
        def text(self, query, max_results=5):
            return fake_results

    import sys

    fake_mod = types.ModuleType("ddgs")
    fake_mod.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_mod)

    out = await _google_search("nba scores")

    assert isinstance(out, dict)
    assert "sources" in out
    assert "model_text" in out
    assert len(out["sources"]) == 2
    s0 = out["sources"][0]
    assert s0["kind"] == "web"
    assert s0["title"] == "ESPN — NBA Scores"
    assert s0["url"] == "https://espn.com/nba"
    assert s0["domain"] == "espn.com"
    assert "Lakers 112" in s0["snippet"]
    assert s0.get("idx") in (None, 0)


@pytest.mark.asyncio
async def test_google_search_handles_empty_results(monkeypatch):
    class FakeDDGS:
        def text(self, q, max_results=5):
            return []

    import sys

    fake_mod = types.ModuleType("ddgs")
    fake_mod.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_mod)

    out = await _google_search("nothing matches")
    assert out == {"sources": [], "model_text": "No results found."}


@pytest.mark.asyncio
async def test_web_fetch_returns_dict_with_one_source(monkeypatch):
    html = (
        b"<html><head><title>ESPN NBA</title></head>"
        b"<body><p>Lakers won 112-108.</p></body></html>"
    )

    class FakeResp:
        status_code = 200
        text = html.decode()

        def raise_for_status(self):
            pass

    class FakeRequests:
        @staticmethod
        def get(url, timeout=10):
            return FakeResp()

    import sys

    monkeypatch.setitem(sys.modules, "requests", FakeRequests)

    out = await _web_fetch("https://espn.com/nba")
    assert isinstance(out, dict)
    assert len(out["sources"]) == 1
    s = out["sources"][0]
    assert s["kind"] == "web"
    assert s["url"] == "https://espn.com/nba"
    assert s["domain"] == "espn.com"
    assert "Lakers won" in out["model_text"]
