# Robust Error Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add end-to-end structured logging (JSON lines to file + human-readable stdout) with automatic `task_id` correlation across all layers.

**Architecture:** A new `logging_config.py` module sets up dual log handlers and exports a `ContextVar` (`task_id_var`) that both ReAct loops set at entry; every log line emitted during a task carries the `task_id` automatically. A FastAPI middleware logs all HTTP request/response pairs. The Node.js proxy adds a `log()` helper writing JSON lines to `server.log`.

**Tech Stack:** Python `logging` + `logging.handlers.RotatingFileHandler`, `contextvars.ContextVar`, Starlette `BaseHTTPMiddleware`, Node.js `fs.appendFileSync`.

**Spec:** `docs/superpowers/specs/2026-04-28-robust-error-logging-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `logging_config.py` | `JsonLinesFormatter`, `HumanFormatter`, `setup_logging()`, `task_id_var` |
| Create | `tests/test_logging_config.py` | Tests for `logging_config.py` and `RequestLoggingMiddleware` |
| Modify | `gemma_bridge.py` | Swap `basicConfig` → `setup_logging()`, add `RequestLoggingMiddleware` |
| Modify | `agent.py` | Add logger, set `task_id_var`, log 5 previously-silent events |
| Modify | `agent_utils.py` | Add `logger.error()` to all tool exception handlers |
| Modify | `inference_engine.py` | Add per-call timing logs |
| Modify | `gemma-web/server.js` | Add `log()` helper, structured logs on every route |

---

## Task 1: Create `logging_config.py`

**Files:**
- Create: `logging_config.py`
- Create: `tests/test_logging_config.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_logging_config.py`:

```python
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
    # Standard LogRecord attrs like 'lineno', 'pathname' must not appear as top-level keys
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
    prev_count = len(root.handlers)
    setup_logging(log_file=str(tmp_path / "app.log"), max_bytes=1024, backup_count=1)
    assert len(root.handlers) == 2  # always exactly two, regardless of what was there
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
python -m pytest tests/test_logging_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'logging_config'`

- [ ] **Step 1.3: Implement `logging_config.py`**

Create `logging_config.py` at the project root:

```python
import json
import logging
import logging.handlers
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

task_id_var: ContextVar[str] = ContextVar("task_id", default="")

# Dynamically determine built-in LogRecord attributes so extras are cleanly separated.
_sample = logging.LogRecord("", 0, "", 0, "", (), None)
_BUILTIN_ATTRS = frozenset(_sample.__dict__.keys()) | {"message", "asctime"}
del _sample


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry = {
            "ts": (
                datetime.fromtimestamp(record.created, tz=timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{int(record.msecs):03d}Z"
            ),
            "level": record.levelname,
            "logger": record.name,
            "task_id": task_id_var.get(),
            "msg": record.message,
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in _BUILTIN_ATTRS:
                entry[key] = val
        return json.dumps(entry)


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        task_id = task_id_var.get()
        task_part = f" [task:{task_id}]" if task_id else ""
        base = (
            f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} "
            f"{record.levelname:<5} [{record.name}]{task_part} {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(
    log_file: str = "app.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    level: int = logging.INFO,
) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLinesFormatter())
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(HumanFormatter())
    root.addHandler(stream_handler)
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_logging_config.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 1.5: Commit**

```bash
git add logging_config.py tests/test_logging_config.py
git commit -m "feat: add logging_config module with JsonLinesFormatter and task_id context var"
```

---

## Task 2: Integrate `logging_config.py` into `gemma_bridge.py`

**Files:**
- Modify: `gemma_bridge.py`
- Modify: `tests/test_logging_config.py` (append middleware test)

- [ ] **Step 2.1: Write the failing middleware test**

Append to `tests/test_logging_config.py`:

```python
def test_request_logging_middleware_logs_http_fields(tmp_path, caplog):
    """RequestLoggingMiddleware emits a log record with method, path, status, elapsed_ms."""
    from unittest.mock import MagicMock, patch
    from fastapi import FastAPI
    from starlette.testclient import TestClient

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

    with caplog.at_level(logging.INFO):
        with TestClient(test_app) as client:
            resp = client.get("/ping")

    assert resp.status_code == 200
    http_records = [r for r in caplog.records if r.getMessage() == "http request"]
    assert len(http_records) >= 1
    r = http_records[0]
    assert getattr(r, "method", None) == "GET"
    assert getattr(r, "path", None) == "/ping"
    assert getattr(r, "status", None) == 200
    assert isinstance(getattr(r, "elapsed_ms", None), int)
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
python -m pytest tests/test_logging_config.py::test_request_logging_middleware_logs_http_fields -v
```

Expected: FAIL — `AttributeError: module 'gemma_bridge' has no attribute 'RequestLoggingMiddleware'`

- [ ] **Step 2.3: Update `gemma_bridge.py`**

Make these changes to `gemma_bridge.py`:

**a) Add imports** — after `import logging`, add:

```python
import time
import uuid as _uuid
from starlette.middleware.base import BaseHTTPMiddleware
from logging_config import setup_logging, task_id_var
```

**b) Replace lines 19-21** (the `basicConfig` block):

Old:
```python
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gemma_bridge")
```

New:
```python
setup_logging()
logger = logging.getLogger("gemma_bridge")
```

**c) After `app = FastAPI()`, add the middleware class and registration:**

```python
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        parts = request.url.path.split("/")
        task_id = ""
        if "stream" in parts:
            idx = parts.index("stream")
            if idx + 1 < len(parts):
                task_id = parts[idx + 1]
        if not task_id:
            task_id = str(_uuid.uuid4())[:8]

        token = task_id_var.set(task_id)
        t0 = time.monotonic()
        try:
            response = await call_next(request)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "http request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
            return response
        except Exception:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "http request failed",
                extra={"method": request.method, "path": request.url.path, "elapsed_ms": elapsed_ms},
                exc_info=True,
            )
            raise
        finally:
            task_id_var.reset(token)

app.add_middleware(RequestLoggingMiddleware)
```

**d) Update `uvicorn.run()`** at the bottom of the file:

Old:
```python
    uvicorn.run(app, host="127.0.0.1", port=PORT)
```

New:
```python
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_config=None)
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_logging_config.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 2.5: Commit**

```bash
git add gemma_bridge.py tests/test_logging_config.py
git commit -m "feat: integrate setup_logging and RequestLoggingMiddleware into gemma_bridge"
```

---

## Task 3: Update `agent.py` — `task_id` propagation + log silent events

**Files:**
- Modify: `agent.py`
- Modify: `tests/test_agent.py` (append 4 new tests)

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_agent.py`:

```python
import logging

@pytest.mark.asyncio
async def test_react_loop_internal_logs_unknown_tool(mock_deps, caplog):
    _, agent = mock_deps
    responses = iter(["TOOL: ghost_tool()", "DONE: done"])
    with patch.object(agent, "run_inference", new_callable=AsyncMock,
                      side_effect=lambda msgs, model_id="gemma4-e4b": next(responses)), \
         caplog.at_level(logging.WARNING):
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
    with patch.object(agent, "run_inference", new_callable=AsyncMock,
                      side_effect=lambda msgs, model_id="gemma4-e4b": next(responses)), \
         caplog.at_level(logging.ERROR):
        await agent._react_loop_internal([{"role": "user", "content": "go"}])
    assert any("tool execution failed" in r.getMessage() for r in caplog.records)

    agent.TOOL_REGISTRY.clear()
    agent.TOOL_REGISTRY.update(original_registry)


@pytest.mark.asyncio
async def test_react_loop_internal_logs_max_iterations(mock_deps, caplog):
    _, agent = mock_deps
    with patch.object(agent, "run_inference", new_callable=AsyncMock,
                      return_value="thinking..."), \
         caplog.at_level(logging.WARNING):
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

    responses = iter(['TOOL: risky_op()', "DONE: done"])

    async def fake_wait_for(coro, timeout):
        raise asyncio.TimeoutError()

    with patch.object(agent, "run_inference", new_callable=AsyncMock,
                      side_effect=lambda msgs, model_id="gemma4-e4b": next(responses)), \
         patch("asyncio.wait_for", side_effect=fake_wait_for), \
         caplog.at_level(logging.WARNING):
        await agent.react_loop_sse(task_id, [{"role": "user", "content": "go"}], "gemma4-e4b")

    assert any("timeout" in r.getMessage().lower() for r in caplog.records)

    agent.TOOL_REGISTRY.clear()
    agent.TOOL_REGISTRY.update(original_registry)
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_agent.py::test_react_loop_internal_logs_unknown_tool tests/test_agent.py::test_react_loop_internal_logs_tool_exception tests/test_agent.py::test_react_loop_internal_logs_max_iterations tests/test_agent.py::test_react_loop_sse_logs_confirmation_timeout -v
```

Expected: all 4 FAIL — no log records with the expected messages.

- [ ] **Step 3.3: Update `agent.py`**

**a) Add to the top-level imports** (after `import asyncio`):

```python
import logging
from logging_config import task_id_var
```

**b) Add after `scheduler = AsyncIOScheduler()` line:**

```python
logger = logging.getLogger(__name__)
```

**c) In `load_scheduler_tasks_on_startup`**, replace the `print()` call:

Old:
```python
            print(f"[agent] Failed to register task {task.get('name')}: {e}")
```

New:
```python
            logger.warning(
                "failed to register scheduled task on startup",
                extra={"task_name": task.get("name"), "error": str(e)},
            )
```

**d) In `_react_loop_internal`**, add at the top of the function (after the docstring):

```python
    loop_id = f"sched-{str(uuid.uuid4())[:8]}"
    task_id_var.set(loop_id)
    logger.info("internal react loop started", extra={"model_id": model_id})
```

Then add these log calls in the loop body:

After `if parsed is None:` / `continue`:
```python
            if parsed is None:
                logger.debug("unparseable model output", extra={"preview": response_text[:200]})
                continue
```

After `if not tool:` block:
```python
            if not tool:
                logger.warning("unknown tool called", extra={"tool": name_or_msg})
                messages.append({"role": "user", "content": f"TOOL_RESULT: ERROR: unknown tool {name_or_msg}"})
                continue
```

In the `except Exception as e:` inside the tool call block:
```python
            try:
                result = await tool.fn(*args)
            except Exception as e:
                logger.error("tool execution failed", extra={"tool": name_or_msg, "error": str(e)}, exc_info=True)
                result = f"ERROR: {e}"
```

Before `return "Max iterations reached"`:
```python
    logger.warning("max iterations reached")
    return "Max iterations reached"
```

**e) In `react_loop_sse`**, add at the very top of the function body (before `q = sse_queues[task_id]`):

```python
    task_id_var.set(task_id)
    logger.info("sse react loop started", extra={"model_id": model_id})
```

Add the same log calls as in `_react_loop_internal` for: unparseable output, unknown tool, tool exception, max iterations. Also add for confirmation timeout:

```python
                except asyncio.TimeoutError:
                    logger.warning(
                        "confirmation timed out for risky tool",
                        extra={"tool": name_or_msg},
                    )
                    approved = False
```

And before `await q.put(json.dumps({"type": "error", "message": "Max iterations reached"}))`:
```python
        logger.warning("max iterations reached")
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_agent.py -v
```

Expected: all tests PASS (including the 4 new ones and all pre-existing ones).

- [ ] **Step 3.5: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat: propagate task_id via ContextVar and log 5 previously-silent agent events"
```

---

## Task 4: Update `agent_utils.py` — log tool errors

**Files:**
- Modify: `agent_utils.py`
- Modify: `tests/test_agent.py` (append 2 tests)

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/test_agent.py`:

```python
@pytest.mark.asyncio
async def test_shell_logs_error_on_timeout(caplog):
    import subprocess
    import agent_utils
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 30)), \
         caplog.at_level(logging.ERROR, logger="agent_utils"):
        result = await agent_utils._shell("sleep 99")
    assert result == "ERROR: timed out"
    assert any("shell" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_web_fetch_logs_error_on_exception(caplog):
    import agent_utils
    with patch("requests.get", side_effect=Exception("connection refused")), \
         caplog.at_level(logging.ERROR, logger="agent_utils"):
        result = await agent_utils._web_fetch("https://example.com")
    assert result.startswith("ERROR:")
    assert any("web_fetch" in r.getMessage().lower() for r in caplog.records)
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_agent.py::test_shell_logs_error_on_timeout tests/test_agent.py::test_web_fetch_logs_error_on_exception -v
```

Expected: both FAIL — no matching log records.

- [ ] **Step 4.3: Update `agent_utils.py`**

`agent_utils.py` already has `logger = logging.getLogger(__name__)` at line 28. Add `logger.error()` calls to each tool's `except` block. The pattern is: add one line before every `return f"ERROR: {e}"`.

Update `_read_file`:
```python
    except Exception as e:
        logger.error("read_file failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"
```

Update `_list_dir`:
```python
    except Exception as e:
        logger.error("list_dir failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"
```

Update `_write_file` (in the inner `except`):
```python
    except Exception as e:
        logger.error("write_file failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"
```

Update `_append_file`:
```python
    except Exception as e:
        logger.error("append_file failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"
```

Update `_shell` — there are two error paths. Replace both:
```python
    except subprocess.TimeoutExpired:
        logger.error("shell timed out", extra={"command": command})
        return "ERROR: timed out"
    # (the outer try/except after subprocess.run returns):
```

Wait — `_shell` has only one `try/except`:
```python
async def _shell(command: str) -> str:
    log_audit(f"SHELL: {command}")
    try:
        result = subprocess.run(...)
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "ERROR: timed out"
```

Replace the `except` block with:
```python
    except subprocess.TimeoutExpired:
        logger.error("shell timed out", extra={"command": command})
        return "ERROR: timed out"
```

Update `_web_fetch`:
```python
    except Exception as e:
        logger.error("web_fetch failed: %s", e, extra={"url": url})
        return f"ERROR: {e}"
```

Update `_grep_search`:
```python
    except Exception as e:
        logger.error("grep_search failed: %s", e, extra={"pattern": pattern, "path": path})
        return f"ERROR: {e}"
```

Update `_python_interpreter`:
```python
    except Exception:
        sys.stdout = old_stdout
        tb = traceback.format_exc()
        logger.error("python_interpreter raised exception", extra={"code_preview": code[:200]})
        return tb
```

Update `_google_search`:
```python
    except Exception as e:
        logger.error("google_search failed: %s", e, extra={"query": query})
        return f"ERROR: {e}"
```

Update `_clipboard_paste`:
```python
    except Exception as e:
        logger.error("clipboard_paste failed: %s", e)
        return f"ERROR: {e}"
```

Update `_clipboard_copy`:
```python
    except Exception as e:
        logger.error("clipboard_copy failed: %s", e)
        return f"ERROR: {e}"
```

Update `_git_status` and `_git_log`:
```python
    except Exception as e:
        logger.error("git_status failed: %s", e)
        return f"ERROR: {e}"
```
```python
    except Exception as e:
        logger.error("git_log failed: %s", e)
        return f"ERROR: {e}"
```

Update `_create_cron` and `_delete_cron` and `_list_crons`:
```python
    except Exception as e:
        logger.error("create_cron failed: %s", e, extra={"name": name})
        return f"ERROR: {e}"
```
```python
    except Exception as e:
        logger.error("delete_cron failed: %s", e, extra={"name": name})
        return f"ERROR: {e}"
```
```python
    except subprocess.CalledProcessError:
        return "No crontab for this user."
    # no logger.error needed — this is not an error
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_agent.py tests/test_agent_tools.py -v
```

Expected: all tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add agent_utils.py tests/test_agent.py
git commit -m "feat: log errors in all agent_utils tool exception handlers"
```

---

## Task 5: Update `inference_engine.py` — per-call timing logs

**Files:**
- Modify: `inference_engine.py`
- Modify: `tests/test_logging_config.py` (append 1 test)

- [ ] **Step 5.1: Write the failing test**

Append to `tests/test_logging_config.py`:

```python
@pytest.mark.asyncio
async def test_run_inference_logs_timing(caplog):
    """run_inference emits INFO records with model_id and elapsed_ms."""
    from unittest.mock import patch, AsyncMock, MagicMock
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
```

- [ ] **Step 5.2: Run test to verify it fails**

```bash
python -m pytest tests/test_logging_config.py::test_run_inference_logs_timing -v
```

Expected: FAIL — no "inference start" or "inference complete" log records.

- [ ] **Step 5.3: Update `inference_engine.py`**

The `run_inference` function is at the bottom of `inference_engine.py`. Replace it:

Old:
```python
async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Shared inference helper — runs blocking inference in the dedicated mlx
    thread so the asyncio event loop stays responsive and mlx GPU streams remain
    valid (streams are thread-local in mlx)."""
    result = await run_in_inference_thread(handle_mlx_vlm_request, model_id, messages)
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"run_inference: unexpected response structure: {e}") from e
```

New:
```python
async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Shared inference helper — runs blocking inference in the dedicated mlx
    thread so the asyncio event loop stays responsive and mlx GPU streams remain
    valid (streams are thread-local in mlx)."""
    import time as _time
    t0 = _time.monotonic()
    logger.info("inference start", extra={"model_id": model_id, "msg_count": len(messages)})
    result = await run_in_inference_thread(handle_mlx_vlm_request, model_id, messages)
    elapsed_ms = int((_time.monotonic() - t0) * 1000)
    logger.info("inference complete", extra={"model_id": model_id, "elapsed_ms": elapsed_ms})
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        logger.error(
            "unexpected inference response structure",
            extra={"model_id": model_id, "result_preview": str(result)[:200]},
        )
        raise RuntimeError(f"run_inference: unexpected response structure: {e}") from e
```

Note: `time` is already imported at the top of `inference_engine.py` as `import time`, so you can use `time.monotonic()` directly instead of the local `import time as _time`. Remove the local import and use `time.monotonic()`:

```python
async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    t0 = time.monotonic()
    logger.info("inference start", extra={"model_id": model_id, "msg_count": len(messages)})
    result = await run_in_inference_thread(handle_mlx_vlm_request, model_id, messages)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("inference complete", extra={"model_id": model_id, "elapsed_ms": elapsed_ms})
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        logger.error(
            "unexpected inference response structure",
            extra={"model_id": model_id, "result_preview": str(result)[:200]},
        )
        raise RuntimeError(f"run_inference: unexpected response structure: {e}") from e
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
python -m pytest tests/test_logging_config.py -v
```

Expected: all tests PASS.

- [ ] **Step 5.5: Run the full test suite**

```bash
python -m pytest -v
```

Expected: all tests PASS. Fix any regressions before committing.

- [ ] **Step 5.6: Commit**

```bash
git add inference_engine.py tests/test_logging_config.py
git commit -m "feat: add per-call timing logs to run_inference"
```

---

## Task 6: Update `server.js` — structured logging

**Files:**
- Modify: `gemma-web/server.js`

No automated test for Node.js in this project. Verify manually by checking `server.log` after making a request.

- [ ] **Step 6.1: Add `fs` require and `log()` helper**

After the existing requires at the top of `gemma-web/server.js`, add:

```javascript
const fs = require("fs");
const LOG_FILE = path.join(__dirname, "server.log");

function log(level, msg, fields = {}) {
  const entry = JSON.stringify({ ts: new Date().toISOString(), level, msg, ...fields });
  fs.appendFileSync(LOG_FILE, entry + "\n");
  if (level === "ERROR") {
    console.error(`${new Date().toISOString()} ${level} [server] ${msg}`, Object.keys(fields).length ? fields : "");
  } else {
    console.log(`${new Date().toISOString()} ${level} [server] ${msg}`, Object.keys(fields).length ? fields : "");
  }
}
```

- [ ] **Step 6.2: Replace every `console.error` in route handlers**

Replace each error handler with a `log()` call that captures the upstream status code when available. Here is the complete updated set of catch blocks:

`/api/document`:
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "document upload failed", { path: "/api/document", error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to upload document to bridge" });
  }
```

`/api/chat`:
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "chat completion failed", { path: "/api/chat", error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to connect to Gemma 4 server" });
  }
```

`/api/chat/stream` (POST):
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "chat stream start failed", { path: "/api/chat/stream", error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to start chat stream" });
  }
```

`/api/chat/stream/:taskId` (SSE proxy error event):
```javascript
  proxyReq.on("error", (err) => {
    log("ERROR", "SSE proxy error", { task_id: taskId, error: err.message });
    res.end();
  });
```

`/api/title`:
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "title generation failed", { path: "/api/title", error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to generate title" });
  }
```

`/api/agent/confirm/:taskId`:
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "agent confirm failed", { task_id: taskId, error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to confirm agent task" });
  }
```

`/api/agent/schedule` (GET):
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "fetch schedule failed", { error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to fetch agent schedule" });
  }
```

`/api/agent/schedule` (POST):
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "create schedule failed", { error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to create agent schedule" });
  }
```

`/api/agent/schedule/:name` (DELETE):
```javascript
  } catch (error) {
    const status = error.response?.status;
    log("ERROR", "delete schedule failed", { name, error: error.message, upstream_status: status });
    res.status(500).json({ error: "Failed to delete agent schedule" });
  }
```

Also update the startup log:
```javascript
app.listen(port, () => {
  log("INFO", "server started", { port });
});
```

- [ ] **Step 6.3: Add request logging to high-traffic routes**

Add a request log at the start of the key POST routes (`/api/chat`, `/api/chat/stream`, `/api/agent/confirm/:taskId`) so you can see incoming traffic:

```javascript
app.post("/api/chat", async (req, res) => {
  const t0 = Date.now();
  try {
    const { messages, model, doc_ids } = req.body;
    log("INFO", "chat request", { model: model || "gemma4-e4b", msg_count: messages?.length });
    // ... existing axios call ...
    log("INFO", "chat response", { elapsed_ms: Date.now() - t0 });
    res.json(response.data);
  } catch (error) { ... }
});
```

Apply the same `t0` + elapsed_ms pattern to `/api/chat/stream` (POST) and `/api/document`.

- [ ] **Step 6.4: Verify manually**

Start the Node server and make a test request:

```bash
cd "/Users/ojdavis/Claude Code/Gemma4/gemma-web"
node server.js &
curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/api/backend/status
tail -5 server.log
```

Expected: `server.log` contains a JSON line with `"level":"INFO","msg":"server started"` and no Python errors in stdout.

- [ ] **Step 6.5: Commit**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4"
git add gemma-web/server.js
git commit -m "feat: add structured JSON logging to Node.js proxy server"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `logging_config.py` with dual handlers, `task_id_var`, JSON formatter — Task 1
- ✅ `setup_logging()` replaces `basicConfig` in `gemma_bridge.py` — Task 2
- ✅ `RequestLoggingMiddleware` for HTTP request/response — Task 2
- ✅ `task_id_var.set()` in both ReAct loops — Task 3
- ✅ Unparseable model output logged — Task 3
- ✅ Unknown tool logged — Task 3
- ✅ Tool execution exception logged — Tasks 3 & 4
- ✅ Max iterations logged — Task 3
- ✅ Confirmation timeout logged — Task 3
- ✅ All `agent_utils` tool errors logged — Task 4
- ✅ Per-call inference timing — Task 5
- ✅ Node.js `log()` helper with JSON lines — Task 6
- ✅ Node.js upstream error status captured — Task 6

**Placeholder scan:** No TBDs. All code blocks contain actual implementation.

**Type consistency:** `task_id_var` defined once in `logging_config.py`, imported in `gemma_bridge.py` and `agent.py`. `JsonLinesFormatter` / `HumanFormatter` / `setup_logging` / `RequestLoggingMiddleware` all defined in their correct modules.
