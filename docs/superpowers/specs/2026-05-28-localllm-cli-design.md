# LocalLLM CLI — Design Spec

**Date:** 2026-05-28
**Status:** Approved, pending implementation plan
**Author:** Omar Davis (with Claude)

## 1. Summary

Add a Claude-Code-style terminal client (`localllm`) on top of the existing
LocalLLM bridge. The CLI owns the conversation session; the existing FastAPI
bridge (`gemma_bridge.py` + `agent.py`) remains the model+tool engine. A new
session-registry layer lets the web UI **discover and live-mirror** running
CLI sessions. Remote-control of CLI sessions from the web is deferred to v2,
but the plumbing (a small WebSocket server inside the CLI) is in place from
day 1 so v2 is a small, additive change.

## 2. Goals & non-goals

**Goals (v1 MVP):**

- Launch `localllm` in any directory, get a rich Textual TUI with streamed
  tokens, agentic ReAct, slash commands, and inline confirmation cards for
  risky tools.
- Tool calls (filesystem, shell, git) operate scoped to the CLI's launch
  directory — not the bridge's process cwd.
- **CLI is fully usable as a standalone tool.** Its only runtime dependency
  is the FastAPI bridge (`gemma_bridge.py`, port 9379). It does **not**
  require `gemma-web/server.js`, a browser, or any HTML to function. Web
  integration is one-way: the CLI publishes its existence to a bridge-side
  registry; nothing in the CLI consumes anything the web produces.
- Web UI gains a "Live CLI Sessions" sidebar section and a read-only mirror
  view; mirror reuses the existing agent-trace renderer.
- Zero regressions for the existing web chat / agent flow.

**Non-goals (v1):**

- Web → CLI remote control (sending messages, approving tools from browser).
  Server is registered but no callback path is exercised in MVP.
- Session resume across CLI restarts.
- Multi-session switcher inside one TUI process.
- A non-rich `--plain` fallback for piped or no-TTY use.
- Standalone binary distribution; the CLI is a console-script in the existing
  venv.

## 3. Architecture

```
┌──────────────────────────────────┐         ┌──────────────────────────────┐
│  Terminal: `localllm`            │         │  Browser: gemma-web          │
│  ─────────────────────────────   │         │  ──────────────────────────  │
│  Textual TUI                     │         │  index.html  (new sidebar:   │
│   • input, transcript, status,   │         │   "Live CLI Sessions")       │
│     confirm modal, trace panel   │         │  Mirror View (read-only)     │
│   • SSE consumer (agent stream)  │         │                              │
│   • aiohttp WS server  ◀─────────┼── v2 ───┤                              │
│     on 127.0.0.1:<random>        │         │                              │
└────────────┬─────────────────────┘         └────────────┬─────────────────┘
             │ HTTP POST /v1/agent/run                   │ GET /v1/cli/sessions
             │ GET  /v1/agent/stream/{task_id} (SSE)     │ GET /v1/cli/stream/{sid} (SSE)
             │ POST /v1/cli/register                     │
             │ POST /v1/cli/heartbeat                    │
             ▼                                           ▼
        ┌──────────────────────────────────────────────────────┐
        │  gemma_bridge.py (FastAPI, port 9379)                │
        │  ── existing, untouched ──                           │
        │  • /v1/chat/*,  /v1/agent/* (ReAct loop)             │
        │  • /v1/agent/confirm/{task_id}                       │
        │  ── new (this project) ──                            │
        │  • /v1/cli/register, /heartbeat, /sessions, DELETE   │
        │  • /v1/cli/stream/{sid}  ← SSE mirror for web        │
        │  • per-session cwd injection into agent task         │
        └──────────────────────────────────────────────────────┘
```

Three new code surfaces:

1. `localllm/` Python package — Textual app, SSE client, registry client,
   control-server stub, slash commands.
2. `cli_sessions.py` in the bridge — in-memory registry with snapshot to
   `~/.localllm/sessions.json`, fanout queue, new FastAPI routes mounted on
   `gemma_bridge.py`.
3. `gemma-web/index.html` and `gemma-web/server.js` delta — sidebar section,
   mirror view, three proxy passthroughs.

## 4. CLI package layout (`localllm/`)

```
localllm/
  __init__.py
  cli.py              # entry point; args; bridge health check; launches App
  app.py              # Textual App: layout, key bindings, lifecycle
  widgets/
    transcript.py     # RichLog-based scrolling transcript (markdown + code)
    input_box.py      # multi-line Input with ↑/↓ history, submit on Enter
    status_bar.py     # footer: model, tools-used, tokens, cwd, session id
    confirm_modal.py  # ModalScreen for risky-tool approval
    trace_panel.py    # collapsible tool-call panel
  agent_client.py     # async HTTP+SSE client for /v1/agent/*
  registry_client.py  # POST /v1/cli/register, /heartbeat, deregister on exit
  control_server.py   # aiohttp WS on 127.0.0.1:random — MVP: no-op accept
  commands.py         # slash-command dispatcher
  config.py           # ~/.localllm/config.toml (bridge_url, model, theme)
  events.py           # typed dataclasses for SSE events
```

Each module has one clear purpose, a narrow public surface, and is
independently testable. Rationale per module:

| Module               | Purpose                                        | Why isolated                                               |
| -------------------- | ---------------------------------------------- | ---------------------------------------------------------- |
| `cli.py`             | Parse args, check bridge, hand off to `app.py` | Test "bridge down" without Textual                         |
| `agent_client.py`    | Speak the bridge protocol                      | Mockable; reusable if a non-Textual frontend is ever added |
| `events.py`          | One source of truth for event shapes           | Shared by client, widgets, tests                           |
| `widgets/*`          | Self-contained Textual widgets                 | Snapshot-testable individually                             |
| `registry_client.py` | Registration + heartbeat lifecycle             | Single retry policy in one place                           |
| `control_server.py`  | aiohttp WS server                              | v2 enablement; ships as no-op                              |

## 5. Bridge-side additions

### 5.1 Session registry endpoints

```
POST   /v1/cli/register      → registers a session, returns {ok: true}
POST   /v1/cli/heartbeat     → resets staleness clock
DELETE /v1/cli/sessions/{id} → graceful deregister
GET    /v1/cli/sessions      → list active sessions (for web sidebar)
GET    /v1/cli/stream/{id}   → SSE mirror of the session's agent events
```

Register payload:

```json
{
  "session_id": "cli-7f3a…",
  "pid": 48211,
  "cwd": "/Users/ojdavis/Projects/foo",
  "ws_url": "ws://127.0.0.1:54311/control",
  "model": "gemma-31b",
  "started_at": "2026-05-28T14:22:01Z",
  "tty": "ttys003",
  "host": "Omar-MBP"
}
```

Registry storage: `dict[session_id, SessionInfo]` in memory, snapshotted to
`~/.localllm/sessions.json` on every change. On bridge startup, the snapshot
is loaded and entries are treated as stale until a heartbeat arrives. Sessions
without a heartbeat for **30 s** are evicted.

### 5.2 SSE fanout

`cli_sessions.py` holds `dict[session_id, list[asyncio.Queue]]`. The existing
agent-event emit helper in `agent.py` gains one line:
`cli_sessions.fanout(session_id, event)`. Each web subscriber on
`/v1/cli/stream/{id}` reads from its own queue; backpressure is handled by
dropping the oldest event past a per-queue cap of 1000.

### 5.3 Per-session cwd (sandbox extension)

`/v1/agent/run` accepts two new optional fields:

```jsonc
{
  // existing fields …
  "cli_session_id": "cli-7f3a…",
  "cwd": "/Users/ojdavis/Projects/foo",
}
```

When `cwd` is present, `agent.py` threads it into the tool-execution context.
`agent_utils.validate_path` is extended to consult a per-call allowlist that
includes `cwd` and its subtree, **in addition to** the existing global
allowlist. The change is purely additive — never weakens rejection logic. Web
UI calls omit the fields and retain legacy behavior.

### 5.4 v2 control hook (not built in MVP)

For v2: `POST /v1/cli/sessions/{id}/control` on the bridge will forward to the
CLI's `ws_url`. Handlers in `control_server.py` will inject a user message or
approval into the running agent task. MVP ships the WS server with an
accept-and-discard handler so the v2 work is a one-file change.

## 6. Web UI changes (`gemma-web/`)

Purely additive — no existing feature is removed or restyled.

### 6.1 Sidebar — "Live CLI Sessions"

New collapsible section between **Scheduled Tasks** and the pinned
**All Chats** button, polling `GET /v1/cli/sessions` every 5 s. Each row shows
session id (short), basename of cwd, model, age, message count, and a status
dot (green = active task, gray = idle). Click → swap main pane into Mirror
View.

### 6.2 Mirror View

- Opens SSE to `GET /v1/cli/stream/{session_id}`.
- Feeds events to the existing `renderAgentEvent()` function (reuses
  tool-call cards, confirm cards, syntax highlighting).
- Read-only banner at top: `Mirroring cli-7f3a — <cwd> — input disabled
(CLI owns input)`.
- Input box visibly disabled with tooltip "Remote control coming in v2."
- "Detach" button returns to normal chat.

### 6.3 server.js proxy

Three pass-through routes added; the existing SSE-aware stream handler is
reused:

```
GET    /v1/cli/sessions          → bridge
GET    /v1/cli/stream/:sid       → bridge (SSE)
```

(Confirmations continue via the existing `/v1/agent/confirm/*` proxy.)

## 7. Error handling

| Failure                                | Behavior                                                                                                                                                                        |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bridge not running at launch           | `cli.py` GETs `/v1/health` w/ 2 s timeout; on fail print `launchctl kickstart -k gui/$UID/com.gemini.litert`, exit 2                                                            |
| Bridge dies mid-task                   | Status bar amber, transcript shows `⚠ bridge disconnected, retrying…`; exp. backoff 1→2→4→8 s for 30 s; then `/reconnect` / `/quit`                                             |
| Model emits malformed `TOOL:`          | Existing `agent.py` parser handles; bridge emits `error` SSE event; CLI renders inline                                                                                          |
| User dismisses confirm modal (Esc)     | Treated as Deny; POST `{"allow": false}` to existing endpoint                                                                                                                   |
| CLI killed -9                          | Bridge evicts via heartbeat timeout within 30 s                                                                                                                                 |
| WS port collision                      | aiohttp binds to port 0 (kernel-assigned); cannot collide                                                                                                                       |
| Two CLIs in same cwd writing same file | Pre-existing concern; document, don't solve                                                                                                                                     |
| Sandbox bypass attempt                 | `validate_path` is the single chokepoint; per-session allowlist is additive                                                                                                     |
| Heartbeat blip                         | 3× retry w/ 1 s backoff before declaring bridge down                                                                                                                            |
| `/v1/cli/register` returns 404/5xx     | Log warning, continue. CLI is still fully functional standalone; it just won't appear in the web sidebar. Preserves CLI/web independence and forward-compat with older bridges. |
| `~/.localllm/` missing                 | `config.py` creates w/ `0700` perms on first run                                                                                                                                |
| No TTY (piped invocation)              | Detect `not sys.stdout.isatty()`; exit 3 with message                                                                                                                           |

## 8. Testing

### 8.1 Unit (fast, no terminal, no bridge)

- `tests/test_cli_events.py` — round-trip SSE event shapes through `events.py`.
- `tests/test_cli_agent_client.py` — `agent_client.py` against a stub aiohttp
  server emitting canned SSE.
- `tests/test_cli_commands.py` — `/help`, `/model`, `/clear`, `/tools`,
  `/cwd`, `/quit` dispatch correctly.
- `tests/test_cli_registry_client.py` — register/heartbeat/deregister with
  retry coverage.
- `tests/test_cli_sessions_registry.py` — bridge-side registry: add/evict/
  snapshot/load, 30 s staleness, fanout to N subscribers.

### 8.2 Bridge integration (FastAPI `TestClient`)

- `tests/test_cli_endpoints.py` — exercise all `/v1/cli/*` routes.
- `tests/test_agent_with_cwd.py` — POST `/v1/agent/run` with `cwd`; verify
  `read_file("README.md")` resolves relative to supplied cwd.
- `tests/test_cli_stream_fanout.py` — register session, start agent run,
  subscribe to mirror, assert events on both streams.

### 8.3 Textual smoke (one test, excluded from CI)

- `tests/test_tui_smoke.py` (`@pytest.mark.needs_tty`) — Textual
  `App.run_test()`: pump fake SSE, send keystrokes, assert transcript content
  and confirm-modal behavior.

CI continues to run `pytest -m "not needs_gpu" --ignore=tests/contracts/test_mlx_contract.py`
per CLAUDE.md; `needs_tty` is added to the excluded set.

### 8.4 Manual verification (Definition of Done)

- [ ] `localllm` launches in `~/Projects/LocalLLM`; status bar shows correct
      cwd + model.
- [ ] "read the README" → tool-call cards render; response streams.
- [ ] Ask agent to `shell("ls")` → confirm modal; Allow runs, Deny refuses.
- [ ] `curl http://127.0.0.1:9379/v1/cli/sessions` shows the session.
- [ ] Web sidebar shows the session; click → mirror streams same content.
- [ ] Ctrl-C in CLI → session disappears from web within 30 s.
- [ ] `bash .git/hooks/pre-push` exits 0.

## 9. Build sequence

Each step is independently shippable, independently CI-greenable, and leaves
the web UI working.

1. **Foundation** — `localllm/` skeleton, `pyproject.toml` entry point,
   `events.py`, `agent_client.py` + unit tests.
2. **TUI shell** — `app.py`, `transcript`, `input_box`, `status_bar`. End
   state: chat with model, streamed tokens, no tools.
3. **ReAct & confirmations** — `confirm_modal`, `trace_panel`. End state:
   agent-mode parity with web UI.
4. **Sandbox plumbing** — `/v1/agent/run` accepts `cwd`; `validate_path`
   extension + tests. End state: CLI tools operate in launch dir.
5. **Session registry** — bridge `cli_sessions.py`, register/heartbeat/list/
   delete; CLI `registry_client.py` + no-op `control_server.py`. End state:
   `curl /v1/cli/sessions` shows live CLIs.
6. **Web mirror** — `/v1/cli/stream/{id}` fanout, sidebar section, mirror
   view, server.js proxy. End state: end-to-end demo working.
7. **Polish** — `/model`, `/clear`, `/tools`, `/cwd` slash commands;
   reconnect logic; config file; docs update.

## 10. Open questions / deferred

- **v2 remote control protocol**: shape of `POST /v1/cli/sessions/{id}/control`
  payload (probably `{kind: "message"|"confirm", body: …}`); turn-taking when
  CLI user is typing simultaneously. Decide during v2 design.
- **Multi-session switcher in TUI**: nice-to-have, intentionally out of v1.
- **Authentication for `/v1/cli/*`**: bridge currently binds to 127.0.0.1 only;
  no auth in MVP. Reconsider if/when bridge is ever exposed beyond localhost.
- **`--plain` fallback**: skipped per earlier decision. Revisit only if a real
  use case appears (e.g., running CLI over SSH without a real TTY).
