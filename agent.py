import asyncio
import io
import json
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from logging_config import task_id_var

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_utils import (
    AGENT_SYSTEM_PROMPT, TOOL_REGISTRY, Tool, parse_model_output, register_tool, log_audit
)

router = APIRouter()
scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)

def estimate_tokens(messages: list) -> int:
    """
    Estimates the number of tokens in a list of messages.
    Heuristic: total_tokens = sum(len(msg.get("content", "")) // 4 + 4 for msg in messages)
    """
    return sum(len(msg.get("content", "")) // 4 + 4 for msg in messages)

from inference_engine import run_inference

# per-task SSE queues and confirmation queues
sse_queues: dict[str, asyncio.Queue] = {}
confirm_queues: dict[str, asyncio.Queue] = {}

SCHEDULER_TASKS_FILE = Path(__file__).parent / "scheduler_tasks.json"
SCHEDULER_LOG_FILE = Path(__file__).parent / "scheduler_log.jsonl"

# ---------------------------------------------------------------------------
# Scheduler tools (keep here because they use the local scheduler instance)
# ---------------------------------------------------------------------------

async def _list_scheduled_tasks() -> str:
    tasks = _load_scheduler_tasks()
    return json.dumps(tasks)

async def _create_scheduled_task(name: str, schedule: str, prompt: str) -> str:
    log_audit(f"CREATE_SCHEDULED_TASK: {name} ({schedule}) {prompt}")
    try:
        tasks = _load_scheduler_tasks()
        tasks.append({"name": name, "schedule": schedule, "prompt": prompt})
        _save_scheduler_tasks(tasks)
        _register_scheduler_task(name, schedule, prompt)
        return "OK: task created"
    except Exception as e:
        return f"ERROR: {e}"

# Register scheduler tools
register_tool("list_scheduled_tasks", "safe", "List scheduled tasks", _list_scheduled_tasks)
register_tool("create_scheduled_task", "risky", "Create scheduled task", _create_scheduled_task)


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
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = await _react_loop_internal(messages, model_id)
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
            logger.warning(
                "failed to register scheduled task on startup",
                extra={"task_name": task.get("name"), "error": str(e)},
            )


# ---------------------------------------------------------------------------
# Internal ReAct loop (no SSE, for scheduler)
# ---------------------------------------------------------------------------

async def _react_loop_internal(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Run ReAct loop without SSE, return final DONE summary."""
    loop_id = f"sched-{str(uuid.uuid4())[:8]}"
    task_id_var.set(loop_id)
    logger.info("internal react loop started", extra={"model_id": model_id})

    # Ensure system prompt is present
    if not any(m["role"] == "system" and "autonomous agent" in m["content"] for m in messages):
        messages.insert(0, {"role": "system", "content": AGENT_SYSTEM_PROMPT})

    for _ in range(20):
        response_text = await run_inference(messages, model_id)
        messages.append({"role": "assistant", "content": response_text})
        parsed = parse_model_output(response_text)
        if parsed is None:
            logger.debug("unparseable model output", extra={"preview": response_text[:200]})
            continue
        kind, name_or_msg, args = parsed
        if kind == "done":
            return name_or_msg
        tool = TOOL_REGISTRY.get(name_or_msg)
        if not tool:
            logger.warning("unknown tool called", extra={"tool": name_or_msg})
            messages.append({"role": "user", "content": f"TOOL_RESULT: ERROR: unknown tool {name_or_msg}"})
            continue
        try:
            result = await tool.fn(*args)
        except Exception as e:
            logger.error("tool execution failed", extra={"tool": name_or_msg, "error": str(e)}, exc_info=True)
            result = f"ERROR: {e}"
        messages.append({"role": "user", "content": f"TOOL_RESULT: {result}"})
    logger.warning("max iterations reached")
    return "Max iterations reached"


# ---------------------------------------------------------------------------
# SSE ReAct loop (with streaming + confirmation gate)
# ---------------------------------------------------------------------------

async def react_loop_sse(task_id: str, messages: list, model_id: str) -> None:
    """Run ReAct loop, emitting SSE events to sse_queues[task_id]."""
    task_id_var.set(task_id)
    logger.info("sse react loop started", extra={"model_id": model_id})

    q = sse_queues[task_id]

    # Ensure system prompt is present
    if not any(m["role"] == "system" and "autonomous agent" in m["content"] for m in messages):
        messages.insert(0, {"role": "system", "content": AGENT_SYSTEM_PROMPT})

    try:
        for _ in range(20):
            response_text = await run_inference(messages, model_id)
            messages.append({"role": "assistant", "content": response_text})

            parsed = parse_model_output(response_text)
            if parsed is None:
                logger.debug("unparseable model output", extra={"preview": response_text[:200]})
                await q.put(json.dumps({"type": "thinking", "text": response_text}))
                continue

            kind, name_or_msg, args = parsed
            if kind == "done":
                await q.put(json.dumps({"type": "done", "message": name_or_msg}))
                return

            tool = TOOL_REGISTRY.get(name_or_msg)
            if not tool:
                logger.warning("unknown tool called", extra={"tool": name_or_msg})
                msg = f"ERROR: unknown tool {name_or_msg}"
                messages.append({"role": "user", "content": f"TOOL_RESULT: {msg}"})
                continue

            # confirmation gate for risky tools
            if tool.risk == "risky":
                args_dict = dict(enumerate(args))
                await q.put(json.dumps({"type": "confirm_request", "task_id": task_id,
                                        "tool": name_or_msg, "args": args_dict}))
                cq = confirm_queues[task_id]
                try:
                    approved = await asyncio.wait_for(cq.get(), timeout=300)
                except asyncio.TimeoutError:
                    logger.warning(
                        "confirmation timed out for risky tool",
                        extra={"tool": name_or_msg},
                    )
                    approved = False
                await q.put(json.dumps({"type": "confirm_resolved", "approved": approved}))
                if not approved:
                    messages.append({"role": "user", "content": "TOOL_RESULT: denied by user"})
                    continue

            t0 = time.monotonic()
            try:
                result = await tool.fn(*args)
            except Exception as e:
                logger.error("tool execution failed", extra={"tool": name_or_msg, "error": str(e)}, exc_info=True)
                result = f"ERROR: {e}"
            elapsed = int((time.monotonic() - t0) * 1000)
            await q.put(json.dumps({"type": "step", "tool": name_or_msg,
                                    "args": dict(enumerate(args)), "result": result, "elapsed_ms": elapsed}))
            messages.append({"role": "user", "content": f"TOOL_RESULT: {result}"})

        logger.warning("max iterations reached")
        await q.put(json.dumps({"type": "error", "message": "Max iterations reached"}))
    except Exception as e:
        await q.put(json.dumps({"type": "error", "message": str(e)}))
    finally:
        await q.put(None)


# ---------------------------------------------------------------------------
# Pydantic models for request bodies
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    prompt: str | None = None
    messages: list[dict] | None = None
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
    sse_queues[task_id] = asyncio.Queue()
    confirm_queues[task_id] = asyncio.Queue()
    
    messages = req.messages or []
    if req.prompt:
        messages.append({"role": "user", "content": req.prompt})
        
    asyncio.create_task(react_loop_sse(task_id, messages, req.model_id))
    return {"task_id": task_id}


@router.get("/stream/{task_id}")
async def stream_agent(task_id: str):
    if task_id not in sse_queues:
        raise HTTPException(status_code=404, detail="Task not found")
    q = sse_queues[task_id]

    async def event_gen():
        try:
            while True:
                event = await q.get()
                if event is None:
                    break
                yield f"data: {event}\n\n"
        finally:
            sse_queues.pop(task_id, None)
            confirm_queues.pop(task_id, None)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/confirm/{task_id}")
async def confirm_action(task_id: str, req: ConfirmRequest):
    if task_id not in confirm_queues:
        raise HTTPException(status_code=404, detail="Task not found")
    await confirm_queues[task_id].put(req.approved)
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
