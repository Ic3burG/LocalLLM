import json
import logging
import pytest
from logging_config import JsonLinesFormatter, HumanFormatter, setup_logging, task_id_var


@pytest.fixture(autouse=True)
def clean_root_handlers():
    """Ensure root logger handlers don't leak between tests."""
    yield
    logging.getLogger().handlers.clear()


def _make_record(msg="test message", name="mylogger", level=logging.INFO):
    return logging.LogRecord(
        name=name, level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )


def test_json_formatter_basic_fields():
    record = _make_record("hello world")
    data = json.loads(JsonLinesFormatter().format(record))
    assert data["level"] == "INFO"
    assert data["logger"] == "mylogger"
    assert data["msg"] == "hello world"
    assert data["ts"].endswith("Z")
    assert data["task_id"] == ""


def test_json_formatter_injects_task_id():
    token = task_id_var.set("abc-123")
    try:
        data = json.loads(JsonLinesFormatter().format(_make_record()))
        assert data["task_id"] == "abc-123"
    finally:
        task_id_var.reset(token)


def test_json_formatter_includes_extra_fields():
    record = _make_record("tool call")
    record.tool = "shell"
    record.elapsed_ms = 42
    data = json.loads(JsonLinesFormatter().format(record))
    assert data["tool"] == "shell"
    assert data["elapsed_ms"] == 42


def test_json_formatter_does_not_duplicate_builtin_fields():
    record = _make_record()
    data = json.loads(JsonLinesFormatter().format(record))
    assert "lineno" not in data
    assert "pathname" not in data


def test_human_formatter_shows_task_id():
    token = task_id_var.set("task-xyz")
    try:
        line = HumanFormatter().format(_make_record("doing something"))
        assert "[task:task-xyz]" in line
    finally:
        task_id_var.reset(token)


def test_human_formatter_omits_task_id_when_empty():
    line = HumanFormatter().format(_make_record("doing something"))
    assert "[task:" not in line


def test_setup_logging_attaches_two_handlers(tmp_path):
    root = logging.getLogger()
    root.handlers.clear()
    setup_logging(log_file=str(tmp_path / "app.log"), max_bytes=1024, backup_count=1)
    assert len(root.handlers) == 2


def test_setup_logging_writes_json_to_file(tmp_path):
    log_file = tmp_path / "app.log"
    root = logging.getLogger()
    root.handlers.clear()
    setup_logging(log_file=str(log_file), max_bytes=1024, backup_count=1)

    logging.getLogger("writetest").info("log line to file")
    for h in root.handlers:
        h.flush()

    lines = [l for l in log_file.read_text().strip().splitlines() if l]
    assert any(json.loads(l)["msg"] == "log line to file" for l in lines)


def test_setup_logging_replaces_existing_handlers(tmp_path):
    root = logging.getLogger()
    root.addHandler(logging.NullHandler())
    setup_logging(log_file=str(tmp_path / "app.log"), max_bytes=1024, backup_count=1)
    assert len(root.handlers) == 2  # always exactly two, regardless of what was there


@pytest.mark.asyncio
async def test_request_logging_middleware_logs_http_fields(tmp_path, caplog):
    """RequestLoggingMiddleware emits a log record with method, path, status, elapsed_ms."""
    from unittest.mock import MagicMock, patch
    from fastapi import FastAPI

    with patch.dict("sys.modules", {
        "mlx_vlm": MagicMock(),
        "inference_engine": MagicMock(),
        "pdf_pipeline": MagicMock(),
        "uvicorn": MagicMock(),
        "apscheduler": MagicMock(),
        "apscheduler.schedulers": MagicMock(),
        "apscheduler.schedulers.asyncio": MagicMock(),
        "agent": MagicMock(),
    }):
        import importlib
        import gemma_bridge as gb
        importlib.reload(gb)
        middleware_cls = gb.RequestLoggingMiddleware

    test_app = FastAPI()
    test_app.add_middleware(middleware_cls)

    @test_app.get("/ping")
    async def ping():
        return {"ok": True}

    # Use a manual handler to capture records instead of relying on caplog
    records = []
    class TestHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    root = logging.getLogger()
    handler = TestHandler()
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Use httpx.AsyncClient with ASGITransport instead of Starlette's TestClient
    # to avoid the httpx._client AttributeError in older Starlette versions.
    from httpx import AsyncClient, ASGITransport

    try:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver") as client:
            resp = await client.get("/ping")

        assert resp.status_code == 200
        http_records = [r for r in records if r.getMessage() == "http request"]
        assert len(http_records) >= 1
        r = http_records[0]
        assert getattr(r, "method", None) == "GET"
        assert getattr(r, "path", None) == "/ping"
        assert getattr(r, "status", None) == 200
        assert isinstance(getattr(r, "elapsed_ms", None), int)
    finally:
        root.removeHandler(handler)


@pytest.mark.asyncio
async def test_run_inference_logs_timing(caplog):
    """run_inference emits INFO records with model_id and elapsed_ms."""
    from unittest.mock import patch, MagicMock
    FAKE = {"choices": [{"message": {"content": "hi"}}]}

    with patch.dict("sys.modules", {"mlx_vlm": MagicMock()}):
        import importlib
        import inference_engine as ie
        importlib.reload(ie)

    async def fake_run_in_thread(fn, *args):
        return FAKE

    with patch.object(ie, "run_in_inference_thread", side_effect=fake_run_in_thread), \
         caplog.at_level(logging.INFO, logger="inference_engine"):
        result = await ie.run_inference([{"role": "user", "content": "hi"}], "gemma4-e4b")

    assert result == "hi"
    start_records = [r for r in caplog.records if "inference start" in r.getMessage()]
    done_records = [r for r in caplog.records if "inference complete" in r.getMessage()]
    assert len(start_records) >= 1
    assert len(done_records) >= 1
    assert getattr(done_records[0], "elapsed_ms", None) is not None
    assert getattr(done_records[0], "model_id", None) == "gemma4-e4b"
