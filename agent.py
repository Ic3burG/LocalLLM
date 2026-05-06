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
    AGENT_SYSTEM_PROMPT, TOOL_REGISTRY, Tool, parse_model_output, register_tool, log_audit,
    strip_thinking_blocks,
)

router = APIRouter()
scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)

def estimate_tokens(messages: list[dict]) -> int:
    """
    Estimates the number of tokens in a list of messages.
    Heuristic: total_tokens = sum(len(str(msg.get("content") or "")) // 4 + 4 for msg in messages)
    """
    return sum(len(str(msg.get("content") or "")) // 4 + 4 for msg in messages)

async def summarize_history(messages: list[dict]) -> list[dict]:
    SOFT_LIMIT = 16000
    HARD_LIMIT = 28000
    
    if estimate_tokens(messages) <= SOFT_LIMIT:
        return messages

    # Perform summarization
    system_prompt_msg = messages[0] if messages and messages[0]["role"] == "system" else None
    
    if system_prompt_msg:
        remaining = messages[1:]
    else:
        remaining = messages
        
    midpoint = len(remaining) // 2
    to_summarize = remaining[:midpoint]
    keep = remaining[midpoint:]

    if to_summarize:
        summary_prompt = (
            "Please summarize the following conversation history concisely, "
            "focusing on key decisions and outcomes:\n\n"
            f"{json.dumps(to_summarize)}"
        )

        import inference_engine
        summary = await inference_engine.run_inference(
            [{"role": "user", "content": summary_prompt}],
            model_id="gemma4-e4b"
        )
        
        summary_text = f"\n\n[PERSISTENT SESSION CONTEXT: {summary}]"
        
        if system_prompt_msg:
            # Merge into existing system message
            new_system_content = system_prompt_msg["content"] + summary_text
            new_messages = [{"role": "system", "content": new_system_content}] + keep
        else:
            # Create new system message at start
            new_messages = [{"role": "system", "content": summary_text.strip()}] + keep
    else:
        new_messages = messages

    # Apply HARD_LIMIT
    while estimate_tokens(new_messages) > HARD_LIMIT and len(new_messages) > 1:
        # Find first non-system message to drop (index 1 if messages[0] is system)
        if new_messages[0]["role"] == "system":
            if len(new_messages) > 1:
                new_messages.pop(1)
            else:
                break # Can't drop the only system message
        else:
            new_messages.pop(0)
            
    return new_messages

from inference_engine import run_inference, is_model_loaded

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

    # Merge all system messages into a single agent system prompt to prevent
    # consecutive system-role messages, which Gemma 3 rejects outright.
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    if not any("autonomous agent" in m["content"] for m in system_msgs):
        extra = "\n\n".join(m["content"] for m in system_msgs if m["content"])
        merged = f"{AGENT_SYSTEM_PROMPT}\n\n{extra}" if extra else AGENT_SYSTEM_PROMPT
        messages.clear()
        messages.append({"role": "system", "content": merged})
        messages.extend(non_system)

    # Prepend the current date/time so the model can resolve "today"/"tomorrow"
    # without needing to call get_current_datetime() first.
    now_str = datetime.now().astimezone().strftime("%A, %Y-%m-%d %H:%M:%S %Z")
    messages[0]["content"] = f"Current date and time: {now_str}\n\n" + messages[0]["content"]

    for _ in range(20):
        messages = await summarize_history(messages)
        response_text = await run_inference(messages, model_id)
        messages.append({"role": "assistant", "content": response_text})
        logger.info("model raw output", extra={"model_id": model_id, "preview": response_text[:500]})
        parsed = parse_model_output(response_text)
        if parsed is None:
            clean_response = strip_thinking_blocks(response_text)
            if not clean_response:
                logger.warning("empty response after stripping thinking, nudging model")
                messages.append({"role": "user", "content": "Please provide your answer."})
                continue
            logger.info("plain text response, treating as done", extra={"preview": clean_response[:200]})
            return clean_response
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

    # Merge all system messages into a single agent system prompt to prevent
    # consecutive system-role messages, which Gemma 3 rejects outright.
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    if not any("autonomous agent" in m["content"] for m in system_msgs):
        extra = "\n\n".join(m["content"] for m in system_msgs if m["content"])
        merged = f"{AGENT_SYSTEM_PROMPT}\n\n{extra}" if extra else AGENT_SYSTEM_PROMPT
        messages.clear()
        messages.append({"role": "system", "content": merged})
        messages.extend(non_system)

    # Prepend the current date/time so the model can resolve "today"/"tomorrow"
    # without needing to call get_current_datetime() first.
    now_str = datetime.now().astimezone().strftime("%A, %Y-%m-%d %H:%M:%S %Z")
    messages[0]["content"] = f"Current date and time: {now_str}\n\n" + messages[0]["content"]

    try:
        empty_retries = 0
        for _ in range(20):
            # Notify the UI when the model needs to be loaded from disk so the
            # user sees a meaningful status instead of a silent "Thinking..." wait.
            if not is_model_loaded(model_id):
                await q.put(json.dumps({"type": "status", "message": f"Loading {model_id}…"}))

            messages = await summarize_history(messages)
            response_text = await run_inference(messages, model_id)
            messages.append({"role": "assistant", "content": response_text})
            logger.info("model raw output", extra={"model_id": model_id, "preview": response_text[:500]})

            parsed = parse_model_output(response_text)
            if parsed is None:
                # Extract thinking content before stripping so we can surface it in the UI
                thinking_match = re.search(
                    r'<\|channel\|?>thought\n?(.*?)(?:<\|?channel\|>|$)',
                    response_text, flags=re.DOTALL
                )
                thinking_content = thinking_match.group(1).strip() if thinking_match else None
                if thinking_content:
                    await q.put(json.dumps({"type": "thinking", "content": thinking_content}))

                clean_response = strip_thinking_blocks(response_text)
                if not clean_response:
                    empty_retries += 1
                    logger.warning("empty response after stripping thinking", extra={"retry": empty_retries})
                    if empty_retries >= 3:
                        logger.error("model produced no response after 3 attempts, giving up")
                        await q.put(json.dumps({"type": "error", "message": f"Model {model_id} produced no response after 3 attempts. Try a simpler query or a different model."}))
                        return
                    messages.append({"role": "user", "content": "Please provide your answer."})
                    continue
                empty_retries = 0
                logger.info("plain text response, treating as done", extra={"preview": clean_response[:200]})
                await q.put(json.dumps({"type": "done", "message": clean_response}))
                return

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
