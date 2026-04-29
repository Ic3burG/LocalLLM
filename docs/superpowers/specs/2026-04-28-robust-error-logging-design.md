# Robust Error Logging Design

**Date:** 2026-04-28  
**Status:** Approved

## Problem

The app silently fails in several layers. Errors in the ReAct loop (unparseable model output, unknown tool names, tool exceptions, max iterations, confirmation timeouts) produce no log output. The Python logging setup has no file handler, so logs only reach stdout. `agent.py` uses `print()` instead of the logging module. The Node.js proxy logs only `error.message`, losing upstream response bodies. There is no way to trace a single agent task across layers.

## Goal

End-to-end structured logging that is easy to debug by humans (readable stdout) and LLMs (JSON lines file). Every log line emitted during an agent task carries a `task_id` field automatically, enabling per-task filtering with `jq` or grep.

## Architecture

### New module: `logging_config.py`

Single `setup_logging(log_file, max_bytes, backup_count)` function called once at startup in `gemma_bridge.py`. Attaches two handlers to the root logger:

- `RotatingFileHandler` → `app.log` (10 MB max, 5 backups), JSON lines format
- `StreamHandler(stdout)` → human-readable prefix format

Exports one `ContextVar`:

```python
task_id_var: ContextVar[str] = ContextVar("task_id", default="")
```

A `JsonLinesFormatter` reads `task_id_var` at format time and injects it into every log record. No function signatures change.

**JSON line format:**
```json
{"ts": "2026-04-28T10:23:45Z", "level": "INFO", "logger": "agent", "task_id": "abc-123", "msg": "tool call", "tool": "shell", "elapsed_ms": 45}
```

**Stdout format:**
```
2026-04-28 10:23:45 INFO  [agent] [task:abc-123] tool call tool=shell elapsed_ms=45
```

### `task_id` propagation

- `react_loop_sse` receives `task_id` from the route — calls `task_id_var.set(task_id)` before the loop
- `_react_loop_internal` (scheduler path) generates a short UUID and sets the same var
- `ContextVar` is async-safe: every `await` inside those coroutines inherits the correct value automatically

### FastAPI request middleware

Added to `gemma_bridge.py`. Logs every HTTP request (method, path) and response (status code, duration ms) as structured JSON lines. Uses the `task_id` from the request path for agent routes; generates a `request_id` for all others.

### Events newly logged (currently silent)

| File | Event | Previous behavior |
|---|---|---|
| `agent.py` | Unparseable model output | Silent — loop continues |
| `agent.py` | Unknown tool name | Silent — error string appended to messages |
| `agent.py` | Tool execution exception | `result = f"ERROR: {e}"`, nothing logged |
| `agent.py` | Max iterations reached | Returns string, nothing logged |
| `agent.py` | Confirm timeout (300 s) | Silent — `approved = False` |
| `agent_utils.py` | Tool function exceptions | Return `f"ERROR: {e}"`, no log |
| `inference_engine.py` | Per-call timing | Not tracked |
| `gemma_bridge.py` | Every HTTP request/response | No middleware |

### Node.js layer (`server.js`)

A `log(level, msg, fields)` helper appends JSON lines to `server.log` using `fs.appendFileSync`. No new npm dependency. Every route logs:

- **Request in:** method, path, body size
- **Upstream success:** status code, duration ms
- **Upstream error:** full `error.message` + upstream response status (previously only `error.message`)

## Files Changed

| File | Change |
|---|---|
| `logging_config.py` | **New** — `setup_logging()`, `JsonLinesFormatter`, `task_id_var` |
| `gemma_bridge.py` | Swap `basicConfig` → `setup_logging()`, add request/response middleware |
| `agent.py` | Add `logger`, set `task_id_var`, log 5 previously-silent events |
| `agent_utils.py` | Add `logger.error()` in tool exception handlers |
| `inference_engine.py` | Add per-call timing logs |
| `gemma-web/server.js` | Add `log()` helper, structured logs on every route |

## Out of Scope

- Log aggregation / remote shipping (Datadog, Loki, etc.)
- Per-concern log file splitting (`inference.log`, `agent.log`)
- `pino` or other npm structured logging libraries
- Changes to `audit.log` (separate security concern, keep as-is)
