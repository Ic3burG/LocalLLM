# Agentic Layer Design — Gemma 4 Local AI Suite

**Date:** 2026-04-27  
**Status:** Approved

---

## Overview

Extend the Gemma 4 local chat app from a pure chat interface into an agentic tool that can interact with the filesystem, run shell commands, manage cron jobs, and execute recurring tasks on a schedule. The model orchestrates multi-step work via a ReAct loop; a smart confirmation gate separates safe actions (run silently) from risky ones (ask the user first).

---

## Architecture

### Process Layout

One Python process on port 9379 runs both `gemma_bridge.py` (inference) and the new `agent.py` (orchestration) as FastAPI routers mounted on the same app:

```
Browser (index.html)
  ├─ /api/chat  ──────────────────────────────┐
  └─ /api/agent, /api/agent/confirm/:id  ──┐  │
                                            ▼  ▼
                              server.js — Node proxy (port 3001)
                                            ▼  ▼
                              Python process (port 9379)
                                ├─ gemma_bridge.py  (/v1/chat/*, /v1/memory, /v1/document)
                                └─ agent.py         (/v1/agent/*)
                                     ├─ calls gemma_bridge inference functions directly (no HTTP)
                                     ├─ Tool Registry (10 tools)
                                     ├─ ReAct Loop
                                     ├─ Confirmation Gate
                                     ├─ SSE Streaming
                                     └─ Dual Scheduler (APScheduler + crontab)
```

`agent.py` calls model inference via direct Python function calls into `gemma_bridge.py` — not via HTTP — to avoid loopback overhead on every ReAct step. `gemma_bridge.py` will expose a shared `run_inference(messages, model_id) -> str` helper that both the `/v1/chat/completions` endpoint and `agent.py` call, routing to `handle_litert_request` or `handle_mlx_request` based on model ID.

---

## Files

### New

- `agent.py` — FastAPI router; all agentic logic lives here
- `scheduler_tasks.json` — persisted in-app scheduled task definitions

### Modified

- `gemma_bridge.py` — add `app.include_router(agent_router, prefix="/v1/agent")`
- `server.js` — proxy routes for `/api/agent`, `/api/agent/confirm/:id`, `/api/agent/schedule/*`
- `index.html` — agent mode toggle, hybrid trace UI, confirmation modal, scheduled tasks sidebar panel

---

## Tool Registry

Tools are defined as Python dataclasses with a `risk_level` field. The confirmation gate reads this field to decide whether to pause and ask the user.

### Safe (auto-run, no prompt)

| Tool                     | Description                           |
| ------------------------ | ------------------------------------- |
| `read_file(path)`        | Read any file and return its contents |
| `list_dir(path)`         | List files and folders at a path      |
| `list_crons()`           | Read and return current user crontab  |
| `list_scheduled_tasks()` | List all in-app APScheduler tasks     |

### Risky (pause and ask user before executing)

| Tool                                            | Description                                           |
| ----------------------------------------------- | ----------------------------------------------------- |
| `write_file(path, content)`                     | Create or overwrite a file                            |
| `append_file(path, content)`                    | Append text to an existing file                       |
| `shell(command)`                                | Run any shell command                                 |
| `create_cron(name, schedule, command)`          | Add a named entry to user crontab                     |
| `delete_cron(name)`                             | Remove a named crontab entry                          |
| `create_scheduled_task(name, schedule, prompt)` | Schedule a recurring Gemma agent task via APScheduler |

---

## ReAct Loop

The agent uses text-based tool invocation since Gemma via LiteRT/MLX does not emit structured function-call JSON natively.

### System prompt injected for all agent requests

```
You are an autonomous agent. You have access to these tools:
  read_file(path), list_dir(path), write_file(path, content),
  append_file(path, content), shell(command), list_crons(),
  create_cron(name, schedule, command), delete_cron(name),
  list_scheduled_tasks(), create_scheduled_task(name, schedule, prompt)

To call a tool, output EXACTLY one line:
  TOOL: tool_name("arg1", "arg2")

To finish, output:
  DONE: <concise summary of what was accomplished>

Think step by step. Only call one tool per response.
```

### Loop execution (in `agent.py`)

1. Add system prompt + user message to conversation history
2. Call model → get response text
3. Parse response:
   - If contains `TOOL: ...` → extract tool name and args
   - If contains `DONE: ...` → end loop, return summary
   - Otherwise → treat as reasoning step, loop again
4. For `TOOL:` call:
   - If `risk_level == "safe"` → execute immediately, append `TOOL_RESULT: <output>` to history
   - If `risk_level == "risky"` → emit `confirm_request` SSE event, pause, wait for `/v1/agent/confirm/{task_id}`
5. On confirmation: if approved execute and continue; if denied append `TOOL_RESULT: denied by user` and continue
6. Maximum 20 iterations per agent run to prevent infinite loops

---

## Confirmation System

Each agent run is assigned a `task_id` (UUID) at start.

**Flow for risky tools:**

1. Agent emits SSE event: `{"type": "confirm_request", "task_id": "...", "tool": "shell", "args": {"command": "rm ..."}}`
2. Frontend renders confirmation modal showing exact tool call and args
3. User clicks Allow or Deny → `POST /v1/agent/confirm/{task_id}` with `{"approved": true|false}`
4. Agent resumes from where it paused

Pending confirmations stored in a module-level dict: `pending_confirmations: dict[str, asyncio.Event]`.

---

## SSE Streaming

`GET /v1/agent/stream/{task_id}` — returns an SSE stream for the duration of the agent run.

### Event types

```jsonl
{"type": "step", "tool": "read_file", "args": {"path": "~/notes.md"}, "result": "...contents...", "elapsed_ms": 120}
{"type": "confirm_request", "tool": "shell", "args": {"command": "rm ..."}}
{"type": "confirm_resolved", "approved": true}
{"type": "thinking", "text": "I should first list the directory..."}
{"type": "done", "message": "Summary written to ~/Desktop/todo-summary.md"}
{"type": "error", "message": "Tool execution failed: ..."}
```

The frontend hybrid trace UI reads this stream and renders:

- Collapsed: `⚙ N steps · Xs` with a single `DONE` summary line
- Expanded: each `step` event shown as `→ tool_name(args)` with its result

---

## Dual Scheduler

### In-App Scheduler (APScheduler)

- Uses `AsyncIOScheduler` (not `BackgroundScheduler`) to run inside FastAPI's asyncio event loop without a separate thread
- Task definitions loaded from `scheduler_tasks.json` on startup
- Each task is a cron-scheduled job that fires `run_agent_task(prompt, model_id)` — running a full ReAct agent loop internally
- Results appended to `scheduler_log.jsonl` (one JSON line per run with timestamp, task name, summary)
- CRUD exposed via `/v1/agent/schedule` endpoints

### System Crontab Manager

- `list_crons()` runs `crontab -l` and parses output
- `create_cron(name, schedule, command)` reads current crontab, appends a tagged comment `# gemma:<name>` + the cron entry, writes back via `crontab -`
- `delete_cron(name)` removes lines matching `# gemma:<name>` tag
- Uses the comment tag to distinguish agent-managed entries from pre-existing ones

---

## UI Changes

### 1. Agent Mode Toggle

Pill-style toggle above the chat input (`💬 Chat` / `🤖 Agent`). Agent mode routes the send button to `/api/agent` instead of `/api/chat` and opens the SSE stream on response.

### 2. Hybrid Trace

Rendered above the final assistant message bubble:

- **Collapsed (default):** `⚙ N steps · Xs ▼ expand`
- **Expanded:** each step shown as `→ tool_name(args)` indented block with its result; risky steps show approval status

### 3. Confirmation Modal

Inline card rendered inside the chat flow (not a browser alert/dialog):

- Shows tool name, exact args, and a plain-English description of the risk
- Two buttons: `✓ Allow` and `✕ Deny`
- Modal disappears and trace resumes once the user responds

### 4. Scheduled Tasks Panel

New collapsible section at the bottom of the existing sidebar, below conversation history:

- **In-App Tasks:** list of APScheduler tasks with name, schedule, prompt preview, active indicator; `+ Add` opens inline form
- **System Cron:** list of agent-managed crontab entries with name and schedule expression; `+ Add` opens inline form
- Both sections have a delete (trash) button per entry

---

## Error Handling

- Tool execution errors are caught, formatted as `TOOL_RESULT: ERROR: <message>`, and fed back into the loop so the model can recover or give up gracefully
- If the model exceeds 20 iterations, the run ends with `{"type": "error", "message": "Max iterations reached"}`
- If the bridge (model) is unreachable during a scheduled task, the error is written to `scheduler_log.jsonl` and the task is skipped (not retried)
- Crontab write failures are surfaced as tool errors (not silent)

---

## Out of Scope

- Streaming model output token-by-token within a single ReAct step (full response per step is sufficient)
- Multi-agent parallelism (one agent run at a time per session)
- Remote/network tool access (all tools are local-only)
- Authentication or sandboxing (this is a single-user local app)
