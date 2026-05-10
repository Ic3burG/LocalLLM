# Agentic Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ReAct-based agentic layer to the Gemma 4 local chat app — file system access, shell execution, cron management, scheduled tasks, and a hybrid trace UI.

**Architecture:** A new `agent.py` FastAPI router is mounted on the existing `gemma_bridge.py` app. It runs a text-based ReAct loop (model outputs `TOOL: name(args)` lines, bridge parses and executes), streaming step events to the frontend via SSE. Safe tools run silently; risky tools pause and ask the user first via an inline confirmation card.

**Tech Stack:** Python/FastAPI, APScheduler (`apscheduler`), `asyncio.Queue` for SSE/confirmation signalling, vanilla JS `EventSource` API, Tailwind CSS (already in use).

---

## File Map

| File                   | Action | Responsibility                                                                   |
| ---------------------- | ------ | -------------------------------------------------------------------------------- |
| `agent.py`             | Create | Tool registry, ReAct loop, confirmation gate, SSE endpoints, scheduler CRUD      |
| `scheduler_tasks.json` | Create | Persisted in-app scheduled task definitions                                      |
| `gemma_bridge.py`      | Modify | Extract `run_inference()` helper; mount agent router; start scheduler            |
| `server.js`            | Modify | Proxy routes for agent run/stream/confirm/schedule                               |
| `gemma-web/index.html` | Modify | Agent toggle, hybrid trace UI, confirmation modal, scheduled tasks sidebar panel |
| `requirements.txt`     | Modify | Add `apscheduler`                                                                |
| `tests/test_agent.py`  | Create | Unit tests for tools, parser, and ReAct loop                                     |

---

## Task 1: Add `apscheduler` to requirements and install

**Files:**

- Modify: `requirements.txt`

- [ ] **Step 1: Add apscheduler to requirements.txt**

Append so the file reads:

```
pdfplumber
sentence-transformers
numpy
python-multipart
apscheduler
```

- [ ] **Step 2: Install**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pip install apscheduler
```

Expected: `Successfully installed apscheduler-...`

- [ ] **Step 3: Verify import**

```bash
.venv/bin/python -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt && git commit -m "chore: add apscheduler dependency"
```

---

## Task 2: Extract `run_inference` helper from `gemma_bridge.py`

**Files:**

- Modify: `gemma_bridge.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_run_inference_is_importable():
    import inspect, gemma_bridge
    assert hasattr(gemma_bridge, "run_inference")
    sig = inspect.signature(gemma_bridge.run_inference)
    assert "messages" in sig.parameters
    assert "model_id" in sig.parameters
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/test_agent.py::test_run_inference_is_importable -v
```

Expected: `FAILED` — `AttributeError: no attribute 'run_inference'`

- [ ] **Step 3: Add `run_inference` to `gemma_bridge.py`**

After the `strip_thinking` function (around line 107), add:

```python
async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Shared inference helper — routes to LiteRT or MLX and returns response text."""
    is_mlx = "26b" in model_id.lower() or "31b" in model_id.lower() or "mlx" in model_id.lower()
    if is_mlx:
        result = await handle_mlx_request(model_id, messages)
    else:
        result = await handle_litert_request(model_id, messages)
    return result["choices"][0]["message"]["content"]
```

In `chat_completions`, find the routing block:

```python
        is_mlx = "26b" in model_id.lower() or "31b" in model_id.lower() or "mlx" in model_id.lower()

        if is_mlx:
            response = await handle_mlx_request(model_id, messages)
        else:
            response = await handle_litert_request(model_id, messages)
```

Replace it with:

```python
        content = await run_inference(messages, model_id)
        response = format_openai_response(model_id, content)
```

- [ ] **Step 4: Run test**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/test_agent.py::test_run_inference_is_importable -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add gemma_bridge.py tests/test_agent.py && git commit -m "refactor: extract run_inference helper from chat_completions"
```

---

## Task 3: Create `agent.py` with full implementation

**Files:**

- Create: `agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_agent.py`:

```python
def test_tool_registry_has_all_tools():
    from agent import TOOL_REGISTRY
    expected = {
        "read_file", "list_dir", "list_crons", "list_scheduled_tasks",
        "write_file", "append_file", "shell",
        "create_cron", "delete_cron", "create_scheduled_task",
    }
    assert set(TOOL_REGISTRY.keys()) == expected

def test_safe_tools_risk_level():
    from agent import TOOL_REGISTRY
    for name in ("read_file", "list_dir", "list_crons", "list_scheduled_tasks"):
        assert TOOL_REGISTRY[name].risk_level == "safe"

def test_risky_tools_risk_level():
    from agent import TOOL_REGISTRY
    for name in ("write_file", "append_file", "shell", "create_cron", "delete_cron", "create_scheduled_task"):
        assert TOOL_REGISTRY[name].risk_level == "risky"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/test_agent.py::test_tool_registry_has_all_tools -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 3: Create `agent.py`**

Create `/Users/ojdavis/Claude Code/Gemma4/agent.py` with the following content. This is the complete file — write it in one pass:

```python
import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

SCHEDULER_TASKS_FILE = os.path.join(os.getcwd(), "scheduler_tasks.json")
SCHEDULER_LOG_FILE = os.path.join(os.getcwd(), "scheduler_log.jsonl")

event_queues: dict[str, asyncio.Queue] = {}
confirm_queues: dict[str, asyncio.Queue] = {}


@dataclass
class Tool:
    name: str
    description: str
    risk_level: Literal["safe", "risky"]
    fn: Callable[..., str]


# ── Tool implementations ──────────────────────────────────────────────────────

def _read_file(path: str) -> str:
    with open(os.path.expanduser(path), "r", errors="replace") as f:
        return f.read()

def _list_dir(path: str) -> str:
    return "\n".join(sorted(os.listdir(os.path.expanduser(path))))

def _write_file(path: str, content: str) -> str:
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"

def _append_file(path: str, content: str) -> str:
    path = os.path.expanduser(path)
    with open(path, "a") as f:
        f.write(content)
    return f"Appended {len(content)} bytes to {path}"

def _shell(command: str) -> str:
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return (result.stdout + result.stderr).strip() or "(no output)"

def _list_crons() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return "(no crontab for this user)"
    return result.stdout.strip() or "(crontab is empty)"

def _create_cron(name: str, schedule: str, command: str) -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""
    tag = f"# gemma:{name}"
    if tag in existing:
        return f"ERROR: cron job '{name}' already exists. Delete it first."
    new_entry = f"\n{tag}\n{schedule} {command}\n"
    proc = subprocess.run(["crontab", "-"], input=existing.rstrip() + new_entry,
                          text=True, capture_output=True)
    if proc.returncode != 0:
        return f"ERROR writing crontab: {proc.stderr}"
    return f"Created cron job '{name}': {schedule} {command}"

def _delete_cron(name: str) -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return "ERROR: no crontab to delete from"
    tag = f"# gemma:{name}"
    lines = result.stdout.splitlines(keepends=True)
    filtered, skip_next = [], False
    for line in lines:
        if line.strip() == tag:
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        filtered.append(line)
    if len(filtered) == len(lines):
        return f"ERROR: no cron job named '{name}' found"
    proc = subprocess.run(["crontab", "-"], input="".join(filtered),
                          text=True, capture_output=True)
    if proc.returncode != 0:
        return f"ERROR writing crontab: {proc.stderr}"
    return f"Deleted cron job '{name}'"

def _list_scheduled_tasks() -> str:
    tasks = _load_scheduler_tasks()
    if not tasks:
        return "(no scheduled tasks)"
    return "\n".join(f"{t['name']}: {t['schedule']} — {t['prompt'][:60]}" for t in tasks)

def _create_scheduled_task(name: str, schedule: str, prompt: str) -> str:
    tasks = _load_scheduler_tasks()
    if any(t["name"] == name for t in tasks):
        return f"ERROR: scheduled task '{name}' already exists"
    tasks.append({"name": name, "schedule": schedule, "prompt": prompt, "model": "gemma4-e4b"})
    _save_scheduler_tasks(tasks)
    _register_apscheduler_job(name, schedule, prompt)
    return f"Created scheduled task '{name}': {schedule}"

def _delete_scheduled_task_fn(name: str) -> str:
    tasks = _load_scheduler_tasks()
    before = len(tasks)
    tasks = [t for t in tasks if t["name"] != name]
    if len(tasks) == before:
        return f"ERROR: no scheduled task named '{name}'"
    _save_scheduler_tasks(tasks)
    if _scheduler is not None:
        try:
            _scheduler.remove_job(name)
        except Exception:
            pass
    return f"Deleted scheduled task '{name}'"


# ── Tool registry ──────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Tool] = {
    "read_file":             Tool("read_file", "Read a file", "safe", _read_file),
    "list_dir":              Tool("list_dir", "List directory contents", "safe", _list_dir),
    "list_crons":            Tool("list_crons", "Show system crontab", "safe", _list_crons),
    "list_scheduled_tasks":  Tool("list_scheduled_tasks", "List in-app tasks", "safe", _list_scheduled_tasks),
    "write_file":            Tool("write_file", "Create or overwrite a file", "risky", _write_file),
    "append_file":           Tool("append_file", "Append to a file", "risky", _append_file),
    "shell":                 Tool("shell", "Run a shell command", "risky", _shell),
    "create_cron":           Tool("create_cron", "Add a system crontab entry", "risky", _create_cron),
    "delete_cron":           Tool("delete_cron", "Remove a system crontab entry", "risky", _delete_cron),
    "create_scheduled_task": Tool("create_scheduled_task", "Schedule a recurring Gemma task", "risky", _create_scheduled_task),
}


# ── Scheduler helpers ─────────────────────────────────────────────────────────

_scheduler = None

def _load_scheduler_tasks() -> list:
    if not os.path.exists(SCHEDULER_TASKS_FILE):
        return []
    with open(SCHEDULER_TASKS_FILE) as f:
        return json.load(f)

def _save_scheduler_tasks(tasks: list) -> None:
    with open(SCHEDULER_TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

def _register_apscheduler_job(name: str, schedule: str, prompt: str) -> None:
    if _scheduler is None:
        return
    parts = schedule.split()
    if len(parts) != 5:
        return
    minute, hour, day, month, day_of_week = parts
    _scheduler.add_job(
        _run_scheduled_task, "cron", id=name, replace_existing=True,
        minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week,
        args=[name, prompt],
    )

async def _run_scheduled_task(name: str, prompt: str) -> None:
    from gemma_bridge import run_inference
    try:
        result = await run_inference([{"role": "user", "content": prompt}])
        entry = {"timestamp": time.time(), "task": name, "summary": result[:500]}
    except Exception as exc:
        entry = {"timestamp": time.time(), "task": name, "error": str(exc)}
    with open(SCHEDULER_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── ReAct parser ──────────────────────────────────────────────────────────────

TOOL_LINE = re.compile(r"TOOL:\s*(\w+)\((.*?)?\)\s*$", re.MULTILINE | re.DOTALL)
DONE_LINE = re.compile(r"DONE:\s*(.+)", re.DOTALL)


def _parse_args(raw: str) -> list:
    """Parse args using JSON array syntax — no code execution."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        return json.loads(f"[{raw}]")
    except Exception:
        return [raw.strip("\"'")]


def parse_model_output(text: str) -> tuple[str, str, list]:
    """Return (kind, value, args) — kind is 'tool' | 'done' | 'thinking'."""
    m = TOOL_LINE.search(text)
    if m:
        return ("tool", m.group(1), _parse_args(m.group(2) or ""))
    m = DONE_LINE.search(text)
    if m:
        return ("done", m.group(1).strip(), [])
    return ("thinking", text.strip(), [])


# ── System prompt ──────────────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """You are an autonomous agent with these tools:
  read_file(path), list_dir(path), write_file(path, content),
  append_file(path, content), shell(command), list_crons(),
  create_cron(name, schedule, command), delete_cron(name),
  list_scheduled_tasks(), create_scheduled_task(name, schedule, prompt)

To call a tool output EXACTLY:
  TOOL: tool_name("arg1", "arg2")

To finish output:
  DONE: <summary>

Think step by step. One tool per response."""


# ── Inference indirection (allows monkeypatching in tests) ────────────────────

async def _run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    from gemma_bridge import run_inference
    return await run_inference(messages, model_id)


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _sse_generator(task_id: str):
    queue = event_queues.get(task_id)
    if queue is None:
        yield _sse({"type": "error", "message": "unknown task_id"})
        return
    while True:
        event = await queue.get()
        yield _sse(event)
        if event.get("type") in ("done", "error"):
            break


# ── ReAct loop ────────────────────────────────────────────────────────────────

async def _react_loop(task_id: str, prompt: str, model_id: str) -> None:
    q = event_queues[task_id]
    cq = confirm_queues[task_id]
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    for _ in range(20):
        try:
            raw = await _run_inference(messages, model_id)
        except Exception as exc:
            await q.put({"type": "error", "message": f"Inference failed: {exc}"})
            return

        kind, value, args = parse_model_output(raw)

        if kind == "thinking":
            await q.put({"type": "thinking", "text": value})
            messages.append({"role": "assistant", "content": raw})
            continue

        if kind == "done":
            await q.put({"type": "done", "message": value})
            return

        tool = TOOL_REGISTRY.get(value)
        if tool is None:
            tool_result = f"ERROR: unknown tool '{value}'"
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"TOOL_RESULT: {tool_result}"})
            continue

        if tool.risk_level == "risky":
            await q.put({
                "type": "confirm_request",
                "tool": value,
                "args": {f"arg{i}": a for i, a in enumerate(args)},
            })
            approved = await asyncio.wait_for(cq.get(), timeout=300)
            await q.put({"type": "confirm_resolved", "approved": approved})
            if not approved:
                tool_result = "denied by user"
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": f"TOOL_RESULT: {tool_result}"})
                continue

        t0 = time.monotonic()
        try:
            tool_result = tool.fn(*args)
        except Exception as exc:
            tool_result = f"ERROR: {exc}"
        elapsed = int((time.monotonic() - t0) * 1000)

        await q.put({
            "type": "step", "tool": value, "args": args,
            "result": tool_result[:2000], "elapsed_ms": elapsed,
        })
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"TOOL_RESULT: {tool_result}"})

    await q.put({"type": "error", "message": "Max iterations reached (20)"})


# ── API endpoints ──────────────────────────────────────────────────────────────

@router.post("/run")
async def run_agent(request: Request):
    body = await request.json()
    task_id = str(uuid.uuid4())
    event_queues[task_id] = asyncio.Queue()
    confirm_queues[task_id] = asyncio.Queue()
    asyncio.create_task(_react_loop(
        task_id, body.get("prompt", ""), body.get("model", "gemma4-e4b")
    ))
    return {"task_id": task_id}


@router.get("/stream/{task_id}")
async def stream_agent(task_id: str):
    return StreamingResponse(
        _sse_generator(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/confirm/{task_id}")
async def confirm_action(task_id: str, request: Request):
    body = await request.json()
    q = confirm_queues.get(task_id)
    if q is None:
        return {"error": "unknown task_id"}
    await q.put(bool(body.get("approved", False)))
    return {"status": "ok"}


@router.get("/schedule")
async def list_schedule():
    return {"tasks": _load_scheduler_tasks()}


@router.post("/schedule")
async def create_schedule(request: Request):
    body = await request.json()
    name = body.get("name", "")
    schedule = body.get("schedule", "")
    prompt = body.get("prompt", "")
    if not all([name, schedule, prompt]):
        return {"error": "name, schedule, and prompt are required"}
    return {"result": _create_scheduled_task(name, schedule, prompt)}


@router.delete("/schedule/{name}")
async def delete_schedule(name: str):
    return {"result": _delete_scheduled_task_fn(name)}
```

- [ ] **Step 4: Run tool registry tests**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/test_agent.py::test_tool_registry_has_all_tools tests/test_agent.py::test_safe_tools_risk_level tests/test_agent.py::test_risky_tools_risk_level -v
```

Expected: all 3 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_agent.py && git commit -m "feat: create agent.py with full tool registry, ReAct loop, SSE, and scheduler"
```

---

## Task 4: Test tool implementations

**Files:**

- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write tool tests**

Append to `tests/test_agent.py`:

```python
import tempfile

def test_read_file_returns_contents():
    from agent import _read_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world"); path = f.name
    try:
        assert _read_file(path) == "hello world"
    finally:
        os.unlink(path)

def test_list_dir_returns_filenames():
    from agent import _list_dir
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "a.txt"), "w").close()
        open(os.path.join(d, "b.txt"), "w").close()
        result = _list_dir(d)
        assert "a.txt" in result and "b.txt" in result

def test_write_file_creates_file():
    from agent import _write_file
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out.txt")
        assert "Written" in _write_file(path, "test content")
        assert open(path).read() == "test content"

def test_append_file_adds_content():
    from agent import _append_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("line1\n"); path = f.name
    try:
        _append_file(path, "line2\n")
        assert open(path).read() == "line1\nline2\n"
    finally:
        os.unlink(path)

def test_shell_returns_output():
    from agent import _shell
    assert "hello_world" in _shell("echo hello_world")

def test_list_crons_returns_string():
    from agent import _list_crons
    result = _list_crons()
    assert isinstance(result, str) and len(result) > 0
```

- [ ] **Step 2: Run**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/test_agent.py -k "test_read_file or test_list_dir or test_write_file or test_append_file or test_shell or test_list_crons" -v
```

Expected: all 6 `PASSED`

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent.py && git commit -m "test: tool implementation coverage"
```

---

## Task 5: Test parser and ReAct loop

**Files:**

- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write parser and loop tests**

Append to `tests/test_agent.py`:

```python
def test_parse_tool_call_single_arg():
    from agent import parse_model_output
    kind, name, args = parse_model_output('TOOL: read_file("~/notes.md")')
    assert kind == "tool" and name == "read_file" and args == ["~/notes.md"]

def test_parse_tool_call_two_args():
    from agent import parse_model_output
    kind, name, args = parse_model_output('TOOL: write_file("~/out.txt", "hello")')
    assert kind == "tool" and name == "write_file" and args == ["~/out.txt", "hello"]

def test_parse_done():
    from agent import parse_model_output
    kind, msg, _ = parse_model_output("DONE: Task completed successfully.")
    assert kind == "done" and "Task completed" in msg

def test_parse_thinking():
    from agent import parse_model_output
    kind, text, _ = parse_model_output("I should check the directory first.")
    assert kind == "thinking"

def test_parse_no_args_tool():
    from agent import parse_model_output
    kind, name, args = parse_model_output("TOOL: list_crons()")
    assert kind == "tool" and name == "list_crons" and args == []

def test_react_loop_executes_safe_tool_and_finishes(monkeypatch):
    import asyncio, agent
    task_id = "test-loop-1"
    agent.event_queues[task_id] = asyncio.Queue()
    agent.confirm_queues[task_id] = asyncio.Queue()
    call_count = {"n": 0}
    responses = ['TOOL: shell("echo hello")', "DONE: Shell said hello."]
    async def fake_inference(messages, model_id="gemma4-e4b"):
        r = responses[call_count["n"]]; call_count["n"] += 1; return r
    monkeypatch.setattr(agent, "_run_inference", fake_inference)
    asyncio.run(agent._react_loop(task_id, "run echo hello", "gemma4-e4b"))
    events = []
    while not agent.event_queues[task_id].empty():
        events.append(agent.event_queues[task_id].get_nowait())
    types = [e["type"] for e in events]
    assert "step" in types and types[-1] == "done"

def test_react_loop_max_iterations(monkeypatch):
    import asyncio, agent
    task_id = "test-loop-2"
    agent.event_queues[task_id] = asyncio.Queue()
    agent.confirm_queues[task_id] = asyncio.Queue()
    async def fake_inference(messages, model_id="gemma4-e4b"):
        return "I am thinking..."
    monkeypatch.setattr(agent, "_run_inference", fake_inference)
    asyncio.run(agent._react_loop(task_id, "loop", "gemma4-e4b"))
    events = []
    while not agent.event_queues[task_id].empty():
        events.append(agent.event_queues[task_id].get_nowait())
    assert events[-1]["type"] == "error" and "Max iterations" in events[-1]["message"]

def test_schedule_crud(tmp_path, monkeypatch):
    import agent
    monkeypatch.setattr(agent, "SCHEDULER_TASKS_FILE", str(tmp_path / "tasks.json"))
    monkeypatch.setattr(agent, "_scheduler", None)
    from agent import _create_scheduled_task, _list_scheduled_tasks, _delete_scheduled_task_fn
    assert "Created" in _create_scheduled_task("daily-notes", "0 9 * * *", "Summarise my notes")
    assert "daily-notes" in _list_scheduled_tasks()
    assert "Deleted" in _delete_scheduled_task_fn("daily-notes")
    assert _list_scheduled_tasks() == "(no scheduled tasks)"
```

- [ ] **Step 2: Run full test suite**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/test_agent.py -v
```

Expected: all tests `PASSED`

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent.py && git commit -m "test: parser, ReAct loop, and scheduler CRUD coverage"
```

---

## Task 6: Mount agent router in `gemma_bridge.py`

**Files:**

- Modify: `gemma_bridge.py`

- [ ] **Step 1: Add startup event and router mount**

In `gemma_bridge.py`, add after the existing imports:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
```

After the `app.add_middleware(CORSMiddleware, ...)` block, add:

```python
@app.on_event("startup")
async def startup_event():
    import agent as agent_module
    scheduler = AsyncIOScheduler()
    agent_module._scheduler = scheduler
    for task in agent_module._load_scheduler_tasks():
        agent_module._register_apscheduler_job(task["name"], task["schedule"], task["prompt"])
    scheduler.start()
    logger.info("APScheduler started with %d persisted tasks", len(agent_module._load_scheduler_tasks()))

from agent import router as agent_router
app.include_router(agent_router, prefix="/v1/agent")
```

- [ ] **Step 2: Verify routes are registered**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/python -c "
from gemma_bridge import app
paths = [getattr(r, 'path', '') for r in app.routes]
for p in ['/v1/agent/run', '/v1/agent/stream/{task_id}', '/v1/agent/confirm/{task_id}', '/v1/agent/schedule']:
    assert p in paths, f'Missing route: {p}'
print('All agent routes registered OK')
" 2>&1 | tail -5
```

Expected: `All agent routes registered OK`

- [ ] **Step 3: Run full test suite**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/ -v
```

Expected: all `PASSED`

- [ ] **Step 4: Commit**

```bash
git add gemma_bridge.py && git commit -m "feat: mount agent router and start AsyncIOScheduler on app startup"
```

---

## Task 7: Add proxy routes to `server.js`

**Files:**

- Modify: `gemma-web/server.js`

- [ ] **Step 1: Add proxy routes**

In `gemma-web/server.js`, add before the `app.listen(...)` line:

```javascript
app.post("/api/agent", async (req, res) => {
  try {
    const response = await axios.post(
      "http://localhost:9379/v1/agent/run",
      req.body
    );
    res.json(response.data);
  } catch (error) {
    console.error("Agent run error:", error.message);
    res.status(500).json({ error: "Failed to start agent run" });
  }
});

app.get("/api/agent/stream/:taskId", async (req, res) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  try {
    const response = await axios.get(
      `http://localhost:9379/v1/agent/stream/${req.params.taskId}`,
      { responseType: "stream" }
    );
    response.data.pipe(res);
    req.on("close", () => response.data.destroy());
  } catch (error) {
    res.write(
      "data: " +
        JSON.stringify({ type: "error", message: error.message }) +
        "\n\n"
    );
    res.end();
  }
});

app.post("/api/agent/confirm/:taskId", async (req, res) => {
  try {
    const response = await axios.post(
      `http://localhost:9379/v1/agent/confirm/${req.params.taskId}`,
      req.body
    );
    res.json(response.data);
  } catch (error) {
    res.status(500).json({ error: "Failed to send confirmation" });
  }
});

app.get("/api/agent/schedule", async (req, res) => {
  try {
    const response = await axios.get("http://localhost:9379/v1/agent/schedule");
    res.json(response.data);
  } catch (error) {
    res.status(500).json({ error: "Failed to fetch schedule" });
  }
});

app.post("/api/agent/schedule", async (req, res) => {
  try {
    const response = await axios.post(
      "http://localhost:9379/v1/agent/schedule",
      req.body
    );
    res.json(response.data);
  } catch (error) {
    res.status(500).json({ error: "Failed to create scheduled task" });
  }
});

app.delete("/api/agent/schedule/:name", async (req, res) => {
  try {
    const response = await axios.delete(
      `http://localhost:9379/v1/agent/schedule/${req.params.name}`
    );
    res.json(response.data);
  } catch (error) {
    res.status(500).json({ error: "Failed to delete scheduled task" });
  }
});
```

- [ ] **Step 2: Check for syntax errors**

```bash
node --check "/Users/ojdavis/Claude Code/Gemma4/gemma-web/server.js" && echo "syntax ok"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add gemma-web/server.js && git commit -m "feat: add agent proxy routes to server.js"
```

---

## Task 8: UI — Agent mode toggle, trace, and confirmation

**Files:**

- Modify: `gemma-web/index.html`

**Security note:** All dynamic content from the agent (tool names, args, results) must be escaped before insertion into the page. Use the `escapeHtml` helper below for all untrusted values.

- [ ] **Step 1: Add CSS to the style block**

Inside `<style>` in `index.html`, add:

```css
.agent-trace {
  border-left: 2px solid #7c3aed;
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 0 6px 6px 0;
  background: rgba(124, 58, 237, 0.05);
  font-size: 12px;
}
.dark .agent-trace {
  background: rgba(124, 58, 237, 0.1);
}
.agent-trace-steps {
  margin-top: 6px;
  font-family: monospace;
  font-size: 11px;
  line-height: 1.8;
  display: none;
}
.agent-trace-steps.open {
  display: block;
}
.confirm-card {
  border: 1px solid #f59e0b;
  border-radius: 8px;
  padding: 12px;
  background: rgba(245, 158, 11, 0.05);
}
.dark .confirm-card {
  background: rgba(245, 158, 11, 0.08);
}
```

- [ ] **Step 2: Add toggle HTML above the chat form**

Find `<form id="chat-form"` and add immediately before it:

```html
<div class="flex gap-2 mb-2 px-1">
  <button
    id="mode-chat"
    onclick="setMode('chat')"
    class="px-3 py-1 rounded-full text-xs font-medium bg-blue-600 text-white transition-colors"
  >
    💬 Chat
  </button>
  <button
    id="mode-agent"
    onclick="setMode('agent')"
    class="px-3 py-1 rounded-full text-xs font-medium bg-transparent text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#2a2b2c] transition-colors"
  >
    🤖 Agent
  </button>
</div>
```

- [ ] **Step 3: Add JS helpers to the script block**

Add these functions to the script block (near the top, after variable declarations). Note: `escapeHtml` must be defined first as other helpers depend on it.

```javascript
let currentMode = "chat";

function escapeHtml(str) {
  const el = document.createElement("div");
  el.textContent = String(str);
  return el.textContent; // returns safe text — use with textContent, not as HTML
}

// Use this when you need to embed a safe string inside an HTML template
function escapeHtmlAttr(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setMode(mode) {
  currentMode = mode;
  const on =
    "px-3 py-1 rounded-full text-xs font-medium text-white transition-colors ";
  const off =
    "px-3 py-1 rounded-full text-xs font-medium bg-transparent text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#2a2b2c] transition-colors";
  document.getElementById("mode-chat").className =
    mode === "chat" ? on + "bg-blue-600" : off;
  document.getElementById("mode-agent").className =
    mode === "agent" ? on + "bg-purple-600" : off;
}

const SAFE_TOOLS = new Set([
  "read_file",
  "list_dir",
  "list_crons",
  "list_scheduled_tasks",
]);

function toggleTrace(id) {
  const el = document.getElementById(id);
  const tog = document.getElementById(id + "-toggle");
  el.classList.toggle("open");
  tog.textContent = el.classList.contains("open") ? "▲ collapse" : "▼ expand";
}

function buildAgentTrace(steps) {
  const id = "trace-" + Date.now();
  const elapsed = steps.reduce((s, e) => s + (e.elapsed_ms || 0), 0);
  const wrap = document.createElement("div");
  wrap.className = "agent-trace";

  const header = document.createElement("div");
  header.style.cssText =
    "display:flex;justify-content:space-between;align-items:center;cursor:pointer;color:#6b7280";
  header.setAttribute("onclick", `toggleTrace('${id}')`);
  const countSpan = document.createElement("span");
  countSpan.textContent = `⚙ ${steps.length} step${steps.length !== 1 ? "s" : ""} · ${(elapsed / 1000).toFixed(1)}s`;
  const togSpan = document.createElement("span");
  togSpan.id = id + "-toggle";
  togSpan.textContent = "▼ expand";
  header.appendChild(countSpan);
  header.appendChild(togSpan);

  const stepsEl = document.createElement("div");
  stepsEl.id = id;
  stepsEl.className = "agent-trace-steps";
  steps.forEach((s) => {
    const row = document.createElement("div");
    const label = document.createElement("span");
    label.style.color = SAFE_TOOLS.has(s.tool) ? "#22c55e" : "#f59e0b";
    const argsStr = (s.args || []).map((a) => JSON.stringify(a)).join(", ");
    label.textContent = `→ ${s.tool}(${argsStr})`;
    const result = document.createElement("div");
    result.style.cssText = "padding-left:14px;color:#6b7280";
    result.textContent = String(s.result || "").substring(0, 120);
    row.appendChild(label);
    row.appendChild(result);
    stepsEl.appendChild(row);
  });

  wrap.appendChild(header);
  wrap.appendChild(stepsEl);
  return wrap;
}

function buildConfirmCard(task_id, event) {
  const card = document.createElement("div");
  card.className = "confirm-card";

  const title = document.createElement("div");
  title.style.cssText = "font-weight:600;margin-bottom:8px";
  title.textContent = "⚠️ Agent wants to call a risky tool";

  const argVals = Object.values(event.args || {})
    .map((a) => JSON.stringify(a))
    .join(", ");
  const code = document.createElement("code");
  code.style.cssText =
    "font-size:11px;background:rgba(0,0,0,0.1);padding:2px 6px;border-radius:4px";
  code.textContent = `${event.tool}(${argVals})`;

  const desc = document.createElement("div");
  desc.style.cssText = "font-size:12px;color:#6b7280;margin:8px 0";
  desc.textContent = "This action may modify your system. Allow it?";

  const btnRow = document.createElement("div");
  btnRow.style.display = "flex";
  btnRow.style.gap = "8px";

  const allow = document.createElement("button");
  allow.className = "px-3 py-1 bg-green-600 text-white rounded text-sm";
  allow.textContent = "✓ Allow";
  allow.onclick = () => sendConfirm(task_id, true, allow);

  const deny = document.createElement("button");
  deny.className =
    "px-3 py-1 bg-red-100 text-red-600 border border-red-400 rounded text-sm";
  deny.textContent = "✕ Deny";
  deny.onclick = () => sendConfirm(task_id, false, deny);

  btnRow.appendChild(allow);
  btnRow.appendChild(deny);
  card.appendChild(title);
  card.appendChild(code);
  card.appendChild(desc);
  card.appendChild(btnRow);
  return card;
}

async function sendConfirm(task_id, approved, btn) {
  btn
    .closest(".confirm-card")
    .querySelectorAll("button")
    .forEach((b) => {
      b.disabled = true;
    });
  await fetch(`/api/agent/confirm/${task_id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
}

async function handleAgentSubmit(prompt) {
  appendMessage("user", prompt);
  userInput.value = "";
  userInput.style.height = "auto";

  const chatMessages = document.getElementById("chat-messages");
  const placeholder = document.createElement("div");
  placeholder.className = "message-gemma flex flex-col gap-1 max-w-[85%]";
  const spinner = document.createElement("div");
  spinner.className = "typing-indicator text-gray-400 text-sm px-2";
  spinner.textContent = "⚙ Agent running...";
  placeholder.appendChild(spinner);
  chatMessages.appendChild(placeholder);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  const runRes = await fetch("/api/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      model: document.getElementById("model-select").value,
    }),
  });
  const { task_id } = await runRes.json();

  const steps = [];
  const source = new EventSource(`/api/agent/stream/${task_id}`);

  source.onmessage = (e) => {
    const event = JSON.parse(e.data);

    if (event.type === "step") {
      steps.push(event);
    }

    if (event.type === "confirm_request") {
      placeholder.textContent = "";
      placeholder.appendChild(buildConfirmCard(task_id, event));
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    if (event.type === "confirm_resolved") {
      placeholder.textContent = "";
      const newSpinner = document.createElement("div");
      newSpinner.className = "typing-indicator text-gray-400 text-sm px-2";
      newSpinner.textContent = "⚙ Agent running...";
      placeholder.appendChild(newSpinner);
    }

    if (event.type === "done" || event.type === "error") {
      source.close();
      placeholder.textContent = "";
      if (steps.length > 0) placeholder.appendChild(buildAgentTrace(steps));
      const msg = document.createElement("div");
      msg.className = "prose dark:prose-invert";
      if (event.type === "done") {
        msg.textContent = event.message || "";
      } else {
        msg.style.color = "#f87171";
        msg.textContent = "⚠ " + (event.message || "Agent error");
      }
      placeholder.appendChild(msg);
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  };

  source.onerror = () => {
    source.close();
    placeholder.textContent = "";
    const err = document.createElement("span");
    err.className = "text-red-400 text-sm";
    err.textContent = "⚠ Connection to agent lost";
    placeholder.appendChild(err);
  };
}
```

- [ ] **Step 4: Branch the form submit handler**

Inside `chatForm.addEventListener('submit', async (e) => {`, add at the top of the handler body (after the empty-input guard):

```javascript
const userPrompt = userInput.value.trim();
if (!userPrompt) return;
if (currentMode === "agent") {
  e.preventDefault();
  await handleAgentSubmit(userPrompt);
  return;
}
```

If the existing handler already declares `userPrompt` or a similar variable, reuse that variable name instead.

- [ ] **Step 5: Verify in browser**

Open http://localhost:3001. Confirm:

- Chat/Agent toggle appears above input
- Clicking Agent turns button purple
- Sending a message in Agent mode shows "⚙ Agent running..." while running

- [ ] **Step 6: Commit**

```bash
git add gemma-web/index.html && git commit -m "feat: add agent mode toggle, hybrid trace, and confirmation card UI"
```

---

## Task 9: UI — Scheduled tasks sidebar panel

**Files:**

- Modify: `gemma-web/index.html`

- [ ] **Step 1: Add sidebar HTML**

Find the closing `</aside>` of `<aside id="sidebar"`. Add immediately before it:

```html
<div
  class="border-t border-gray-200 dark:border-[#3c3d40] mt-auto flex-shrink-0"
>
  <button
    onclick="toggleSchedulePanel()"
    class="w-full flex items-center justify-between px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-[#2a2b2c] transition-colors"
  >
    <span>📅 Scheduled Tasks</span>
    <span id="schedule-panel-toggle">▶</span>
  </button>
  <div id="schedule-panel" class="hidden px-3 pb-3 text-xs space-y-2">
    <div id="schedule-list"></div>
    <button
      onclick="openAddSchedule()"
      class="w-full py-1 border border-dashed border-gray-300 dark:border-gray-600 rounded text-gray-400 hover:text-blue-500 hover:border-blue-400 transition-colors"
    >
      + Add Task
    </button>
    <div id="add-schedule-form" class="hidden space-y-1">
      <input
        id="sched-name"
        placeholder="Name"
        class="w-full px-2 py-1 border border-gray-300 dark:border-gray-600 bg-transparent rounded"
      />
      <input
        id="sched-cron"
        placeholder="Cron schedule (e.g. 0 9 * * *)"
        class="w-full px-2 py-1 border border-gray-300 dark:border-gray-600 bg-transparent rounded"
      />
      <textarea
        id="sched-prompt"
        placeholder="Prompt for Gemma"
        rows="2"
        class="w-full px-2 py-1 border border-gray-300 dark:border-gray-600 bg-transparent rounded resize-none"
      ></textarea>
      <div class="flex gap-1">
        <button
          onclick="saveSchedule()"
          class="flex-1 py-1 bg-blue-600 text-white rounded"
        >
          Save
        </button>
        <button
          onclick="cancelAddSchedule()"
          class="flex-1 py-1 border border-gray-300 dark:border-gray-600 rounded"
        >
          Cancel
        </button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add schedule panel JS**

Add to the script block:

```javascript
async function toggleSchedulePanel() {
  const panel = document.getElementById("schedule-panel");
  const toggle = document.getElementById("schedule-panel-toggle");
  const opening = panel.classList.contains("hidden");
  panel.classList.toggle("hidden");
  toggle.textContent = opening ? "▼" : "▶";
  if (opening) await refreshScheduleList();
}

async function refreshScheduleList() {
  const res = await fetch("/api/agent/schedule");
  const { tasks } = await res.json();
  const list = document.getElementById("schedule-list");
  list.textContent = "";
  if (!tasks || tasks.length === 0) {
    const empty = document.createElement("div");
    empty.className = "text-gray-400 py-1";
    empty.textContent = "No scheduled tasks";
    list.appendChild(empty);
    return;
  }
  tasks.forEach((t) => {
    const row = document.createElement("div");
    row.className =
      "flex items-start justify-between gap-1 py-1 border-b border-gray-100 dark:border-gray-700";

    const info = document.createElement("div");
    info.className = "min-w-0";

    const name = document.createElement("div");
    name.className = "font-medium text-gray-700 dark:text-gray-300 truncate";
    name.textContent = t.name;

    const schedule = document.createElement("div");
    schedule.className = "text-gray-400";
    schedule.textContent = t.schedule;

    const prompt = document.createElement("div");
    prompt.className = "text-gray-400 truncate";
    prompt.textContent = t.prompt.substring(0, 50);

    info.appendChild(name);
    info.appendChild(schedule);
    info.appendChild(prompt);

    const del = document.createElement("button");
    del.className = "text-red-400 hover:text-red-600 shrink-0 ml-1";
    del.textContent = "✕";
    del.onclick = () => deleteSchedule(t.name);

    row.appendChild(info);
    row.appendChild(del);
    list.appendChild(row);
  });
}

function openAddSchedule() {
  document.getElementById("add-schedule-form").classList.remove("hidden");
}

function cancelAddSchedule() {
  document.getElementById("add-schedule-form").classList.add("hidden");
  ["sched-name", "sched-cron", "sched-prompt"].forEach((id) => {
    document.getElementById(id).value = "";
  });
}

async function saveSchedule() {
  const name = document.getElementById("sched-name").value.trim();
  const schedule = document.getElementById("sched-cron").value.trim();
  const prompt = document.getElementById("sched-prompt").value.trim();
  if (!name || !schedule || !prompt) {
    alert("All fields are required");
    return;
  }
  const res = await fetch("/api/agent/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, schedule, prompt }),
  });
  const data = await res.json();
  if (data.error) {
    alert(data.error);
    return;
  }
  cancelAddSchedule();
  await refreshScheduleList();
}

async function deleteSchedule(name) {
  if (!confirm(`Delete scheduled task "${name}"?`)) return;
  await fetch(`/api/agent/schedule/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  await refreshScheduleList();
}
```

- [ ] **Step 3: Verify in browser**

Open http://localhost:3001. Click "📅 Scheduled Tasks" — panel expands. Click "+ Add Task", fill in all three fields, Save. Task appears in the list. Click ✕ to delete.

- [ ] **Step 4: Run final test suite**

```bash
cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 5: Final commit**

```bash
git add gemma-web/index.html && git commit -m "feat: add scheduled tasks sidebar panel"
```

---

## End-to-End Smoke Test

1. `cd "/Users/ojdavis/Claude Code/Gemma4" && .venv/bin/python gemma_bridge.py`
2. `cd "/Users/ojdavis/Claude Code/Gemma4/gemma-web" && node server.js`
3. Open http://localhost:3001
4. Switch to **🤖 Agent** → send: `list the files in my Desktop`
   - Trace shows `⚙ 1 step · Xs`, expand to see `list_dir` result and a DONE summary
5. Send: `write "hello from Gemma" to /tmp/gemma-test.txt`
   - Yellow confirmation card appears; click Allow → file written; trace shows write_file as approved
6. `cat /tmp/gemma-test.txt` → `hello from Gemma`
7. Click "📅 Scheduled Tasks" → "+ Add Task" → save a task → confirm it appears in the list
