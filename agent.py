import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()
scheduler = AsyncIOScheduler()

# Lazy import to avoid circular dependency when gemma_bridge.py is run as __main__
async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    from gemma_bridge import run_inference as _run_inference
    return await _run_inference(messages, model_id)

# per-task SSE queues and confirmation queues
_sse_queues: dict[str, asyncio.Queue] = {}
_confirm_queues: dict[str, asyncio.Queue] = {}

SCHEDULER_TASKS_FILE = Path(__file__).parent / "scheduler_tasks.json"
SCHEDULER_LOG_FILE = Path(__file__).parent / "scheduler_log.jsonl"


@dataclass
class Tool:
    name: str
    risk: str  # "safe" or "risky"
    description: str
    fn: Any  # callable


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _read_file(path: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        return p.read_text()
    except Exception as e:
        return f"ERROR: {e}"


async def _list_dir(path: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        entries = [entry.name for entry in p.iterdir()]
        return "\n".join(entries)
    except Exception as e:
        return f"ERROR: {e}"


async def _list_crons() -> str:
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return "No crontab for this user."


async def _list_scheduled_tasks() -> str:
    tasks = _load_scheduler_tasks()
    return json.dumps(tasks)


async def _write_file(path: str, content: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"OK: wrote {len(content)} bytes"
    except Exception as e:
        return f"ERROR: {e}"


async def _append_file(path: str, content: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(content)
        return f"OK: appended {len(content)} bytes"
    except Exception as e:
        return f"ERROR: {e}"


async def _shell(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "ERROR: timed out"


async def _create_cron(name: str, schedule: str, command: str) -> str:
    try:
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError:
            existing = ""
        new_entry = f"# gemma:{name}\n{schedule} {command}\n"
        new_crontab = existing + new_entry
        subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            text=True,
            check=True,
        )
        return "OK: cron created"
    except Exception as e:
        return f"ERROR: {e}"


async def _delete_cron(name: str) -> str:
    try:
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError:
            existing = ""
        lines = existing.splitlines(keepends=True)
        tag = f"# gemma:{name}"
        new_lines = []
        i = 0
        found = False
        while i < len(lines):
            if lines[i].strip() == tag:
                found = True
                i += 1  # skip the tag line
                if i < len(lines):
                    i += 1  # skip the following cron line
            else:
                new_lines.append(lines[i])
                i += 1
        if not found:
            return "ERROR: not found"
        subprocess.run(
            ["crontab", "-"],
            input="".join(new_lines),
            text=True,
            check=True,
        )
        return "OK: cron deleted"
    except Exception as e:
        return f"ERROR: {e}"


async def _create_scheduled_task(name: str, schedule: str, prompt: str) -> str:
    try:
        tasks = _load_scheduler_tasks()
        tasks.append({"name": name, "schedule": schedule, "prompt": prompt})
        _save_scheduler_tasks(tasks)
        _register_scheduler_task(name, schedule, prompt)
        return "OK: task created"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Tool] = {
    "read_file": Tool("read_file", "safe", "Read file contents", _read_file),
    "list_dir": Tool("list_dir", "safe", "List directory", _list_dir),
    "list_crons": Tool("list_crons", "safe", "List crontab", _list_crons),
    "list_scheduled_tasks": Tool("list_scheduled_tasks", "safe", "List scheduled tasks", _list_scheduled_tasks),
    "write_file": Tool("write_file", "risky", "Write file", _write_file),
    "append_file": Tool("append_file", "risky", "Append to file", _append_file),
    "shell": Tool("shell", "risky", "Run shell command", _shell),
    "create_cron": Tool("create_cron", "risky", "Create cron job", _create_cron),
    "delete_cron": Tool("delete_cron", "risky", "Delete cron job", _delete_cron),
    "create_scheduled_task": Tool("create_scheduled_task", "risky", "Create scheduled task", _create_scheduled_task),
}


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------

def _load_scheduler_tasks() -> list:
    if SCHEDULER_TASKS_FILE.exists():
        return json.loads(SCHEDULER_TASKS_FILE.read_text())
    return []


def _save_scheduler_tasks(tasks: list) -> None:
    SCHEDULER_TASKS_FILE.write_text(json.dumps(tasks, indent=2))


async def _run_scheduler_task(task_name: str, prompt: str, model_id: str = "gemma4-e4b") -> None:
    """Run a full ReAct agent loop for a scheduled task and log the result."""
    try:
        result = await _react_loop_internal(prompt, model_id)
        _log_scheduler_result(task_name, result, None)
    except Exception as e:
        _log_scheduler_result(task_name, None, str(e))


def _log_scheduler_result(task_name: str, summary: str | None, error: str | None) -> None:
    entry = {"ts": datetime.utcnow().isoformat(), "task": task_name, "summary": summary, "error": error}
    with open(SCHEDULER_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _register_scheduler_task(name: str, schedule: str, prompt: str) -> None:
    """Parse cron schedule string and add job to APScheduler."""
    parts = schedule.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron schedule: {schedule}")
    minute, hour, day, month, dow = parts
    scheduler.add_job(
        _run_scheduler_task,
        "cron",
        args=[name, prompt],
        minute=minute, hour=hour, day=day, month=month, day_of_week=dow,
        id=f"gemma_task_{name}",
        replace_existing=True,
    )


def load_scheduler_tasks_on_startup() -> None:
    """Called from gemma_bridge.py startup to register all persisted tasks."""
    for task in _load_scheduler_tasks():
        try:
            _register_scheduler_task(task["name"], task["schedule"], task["prompt"])
        except Exception as e:
            print(f"[agent] Failed to register task {task.get('name')}: {e}")


# ---------------------------------------------------------------------------
# Arg parser
# ---------------------------------------------------------------------------

def parse_model_output(text: str) -> tuple[str, str, list] | None:
    """Return (type, tool_or_message, args) or None if neither TOOL nor DONE found.

    Handles both the text-based format (TOOL: name(args)) and Gemma's native
    function-call format (<|tool_call>call:name(args)<tool_call|>).
    """
    # Native Gemma format: <|tool_call>call:tool_name("arg")<tool_call|>
    native_match = re.search(r'<\|tool_call\>call:(\w+)\((.*?)\)<tool_call\|>', text, re.DOTALL)
    # Text-based format: TOOL: tool_name("arg")
    tool_match = re.search(r'TOOL:\s*(\w+)\((.*)\)\s*$', text, re.MULTILINE)
    done_match = re.search(r'DONE:\s*(.+)', text, re.MULTILINE)

    active_match = native_match or tool_match
    if active_match:
        tool_name = active_match.group(1)
        raw_args = active_match.group(2).strip()
        try:
            args = json.loads(f"[{raw_args}]") if raw_args else []
        except json.JSONDecodeError:
            # Heuristic: try splitting on comma+space for multi-arg tools
            parts = [p.strip().strip('"\'') for p in raw_args.split(', ')]
            args = parts if len(parts) > 1 else [raw_args]
        return ("tool", tool_name, args)
    if done_match:
        return ("done", done_match.group(1).strip(), [])
    return None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are an autonomous agent. You have access to these tools:
  read_file(path), list_dir(path), write_file(path, content),
  append_file(path, content), shell(command), list_crons(),
  create_cron(name, schedule, command), delete_cron(name),
  list_scheduled_tasks(), create_scheduled_task(name, schedule, prompt)

To call a tool, output EXACTLY one line:
  TOOL: tool_name("arg1", "arg2")

To finish, output:
  DONE: <concise summary of what was accomplished>

Think step by step. Only call one tool per response."""


# ---------------------------------------------------------------------------
# Internal ReAct loop (no SSE, for scheduler)
# ---------------------------------------------------------------------------

async def _react_loop_internal(user_prompt: str, model_id: str = "gemma4-e4b") -> str:
    """Run ReAct loop without SSE, return final DONE summary."""
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    for _ in range(20):
        response_text = await run_inference(messages, model_id)
        messages.append({"role": "assistant", "content": response_text})
        parsed = parse_model_output(response_text)
        if parsed is None:
            continue
        kind, name_or_msg, args = parsed
        if kind == "done":
            return name_or_msg
        tool = TOOL_REGISTRY.get(name_or_msg)
        if not tool:
            messages.append({"role": "user", "content": f"TOOL_RESULT: ERROR: unknown tool {name_or_msg}"})
            continue
        try:
            result = await tool.fn(*args)
        except Exception as e:
            result = f"ERROR: {e}"
        messages.append({"role": "user", "content": f"TOOL_RESULT: {result}"})
    return "Max iterations reached"


# ---------------------------------------------------------------------------
# SSE ReAct loop (with streaming + confirmation gate)
# ---------------------------------------------------------------------------

async def _react_loop_sse(task_id: str, user_prompt: str, model_id: str) -> None:
    """Run ReAct loop, emitting SSE events to _sse_queues[task_id]."""
    q = _sse_queues[task_id]
    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    try:
        for _ in range(20):
            response_text = await run_inference(messages, model_id)
            messages.append({"role": "assistant", "content": response_text})

            parsed = parse_model_output(response_text)
            if parsed is None:
                await q.put(json.dumps({"type": "thinking", "text": response_text}))
                continue

            kind, name_or_msg, args = parsed
            if kind == "done":
                await q.put(json.dumps({"type": "done", "message": name_or_msg}))
                return

            tool = TOOL_REGISTRY.get(name_or_msg)
            if not tool:
                msg = f"ERROR: unknown tool {name_or_msg}"
                messages.append({"role": "user", "content": f"TOOL_RESULT: {msg}"})
                continue

            # confirmation gate for risky tools
            if tool.risk == "risky":
                args_dict = dict(enumerate(args))
                await q.put(json.dumps({"type": "confirm_request", "task_id": task_id,
                                        "tool": name_or_msg, "args": args_dict}))
                cq = _confirm_queues[task_id]
                try:
                    approved = await asyncio.wait_for(cq.get(), timeout=300)
                except asyncio.TimeoutError:
                    approved = False
                await q.put(json.dumps({"type": "confirm_resolved", "approved": approved}))
                if not approved:
                    messages.append({"role": "user", "content": "TOOL_RESULT: denied by user"})
                    continue

            t0 = time.monotonic()
            try:
                result = await tool.fn(*args)
            except Exception as e:
                result = f"ERROR: {e}"
            elapsed = int((time.monotonic() - t0) * 1000)
            await q.put(json.dumps({"type": "step", "tool": name_or_msg,
                                    "args": dict(enumerate(args)), "result": result, "elapsed_ms": elapsed}))
            messages.append({"role": "user", "content": f"TOOL_RESULT: {result}"})

        await q.put(json.dumps({"type": "error", "message": "Max iterations reached"}))
    except Exception as e:
        await q.put(json.dumps({"type": "error", "message": str(e)}))
    finally:
        await q.put(None)


# ---------------------------------------------------------------------------
# Pydantic models for request bodies
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    prompt: str
    model_id: str = "gemma4-e4b"


class ConfirmRequest(BaseModel):
    approved: bool


class ScheduleTaskRequest(BaseModel):
    name: str
    schedule: str
    prompt: str


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/run")
async def run_agent(req: AgentRequest):
    task_id = str(uuid.uuid4())
    _sse_queues[task_id] = asyncio.Queue()
    _confirm_queues[task_id] = asyncio.Queue()
    asyncio.create_task(_react_loop_sse(task_id, req.prompt, req.model_id))
    return {"task_id": task_id}


@router.get("/stream/{task_id}")
async def stream_agent(task_id: str):
    if task_id not in _sse_queues:
        raise HTTPException(status_code=404, detail="Task not found")
    q = _sse_queues[task_id]

    async def event_gen():
        try:
            while True:
                event = await q.get()
                if event is None:
                    break
                yield f"data: {event}\n\n"
        finally:
            _sse_queues.pop(task_id, None)
            _confirm_queues.pop(task_id, None)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/confirm/{task_id}")
async def confirm_action(task_id: str, req: ConfirmRequest):
    if task_id not in _confirm_queues:
        raise HTTPException(status_code=404, detail="Task not found")
    await _confirm_queues[task_id].put(req.approved)
    return {"ok": True}


@router.get("/schedule")
async def list_scheduled_tasks_endpoint():
    return _load_scheduler_tasks()


@router.post("/schedule")
async def create_scheduled_task_endpoint(req: ScheduleTaskRequest):
    tasks = _load_scheduler_tasks()
    if any(t["name"] == req.name for t in tasks):
        raise HTTPException(status_code=400, detail="Task name already exists")
    tasks.append({"name": req.name, "schedule": req.schedule, "prompt": req.prompt})
    _save_scheduler_tasks(tasks)
    _register_scheduler_task(req.name, req.schedule, req.prompt)
    return {"ok": True}


@router.delete("/schedule/{name}")
async def delete_scheduled_task_endpoint(name: str):
    tasks = _load_scheduler_tasks()
    new_tasks = [t for t in tasks if t["name"] != name]
    if len(new_tasks) == len(tasks):
        raise HTTPException(status_code=404, detail="Task not found")
    _save_scheduler_tasks(new_tasks)
    job_id = f"gemma_task_{name}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    return {"ok": True}
