# Agent Tool Registry Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ~22 new tools to the agent registry across semantic recall, macOS automation, on-device audio/vision, and data/file fill-ins.

**Architecture:** Each tool is an `async def _name(...) -> str` in `agent_utils.py` returning `OK: …`/`ERROR: …`, registered with `register_tool(...)`, and listed in the `TOOLS AVAILABLE` system-prompt block. Heavy deps import lazily inside the function; blocking work runs via `run_in_executor`; risky tools auto-trigger the SSE confirm gate. `recall` adds a bridge HTTP endpoint to reach the in-memory `doc_store`.

**Tech Stack:** Python 3 / FastAPI, the `osascript` CLI for macOS automation, `mlx-whisper` / `mlx-vlm` for multimodal, Swift Vision framework for OCR, pytest + `unittest.mock` for tests.

**Sandbox note:** `validate_path()` confines file paths to the project root (`os.getcwd()`). All new file-touching tools inherit this boundary — do NOT loosen it in this plan.

**Conventions for every "add a tool" step:**

1. Add the `async def _tool(...)` near related tools in `agent_utils.py`.
2. Add a `register_tool(...)` line in the registration block (after line ~985).
3. Add one line to the `TOOLS AVAILABLE` block in `AGENT_SYSTEM_PROMPT` (before the `RULES:` line, ~1034).
4. Add the test to `tests/test_agent_tools.py`.

Run the suite with: `.venv/bin/python -m pytest tests/test_agent_tools.py -v`

---

## Phase 1 — Quick Wins

### Task 1: `recall` tool + `/v1/rag/search` bridge endpoint

**Files:**

- Modify: `gemma_bridge.py` (add endpoint near other `/v1/*` routes)
- Modify: `agent_utils.py` (add `_recall`, register, prompt line)
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Add the bridge endpoint**

In `gemma_bridge.py`, add:

```python
@app.post("/v1/rag/search")
async def rag_search(req: dict):
    query = req.get("query", "")
    top_k = int(req.get("top_k", 5))
    doc_ids = list(doc_store.keys())
    if not doc_ids:
        return {"results": "", "count": 0}
    chunks, _ = pdf_pipeline.retrieve_chunks(query, doc_ids, doc_store, top_k=top_k)
    return {
        "results": pdf_pipeline.build_numbered_document_context(chunks),
        "count": len(chunks),
    }
```

- [ ] **Step 2: Write the failing test**

```python
from agent_utils import _recall


@pytest.mark.asyncio
async def test_recall_returns_results():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": "[1] (a.pdf): hi", "count": 1}
    with patch("requests.post", return_value=mock_resp) as mock_post:
        out = await _recall("what is x")
    assert "[1]" in out
    assert mock_post.call_args.kwargs["json"]["query"] == "what is x"


@pytest.mark.asyncio
async def test_recall_empty():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": "", "count": 0}
    with patch("requests.post", return_value=mock_resp):
        out = await _recall("nothing")
    assert "No relevant" in out
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_recall_returns_results -v`
Expected: FAIL with `ImportError: cannot import name '_recall'`

- [ ] **Step 4: Implement `_recall`**

```python
async def _recall(query: str) -> str:
    try:
        import requests as _requests

        loop = asyncio.get_running_loop()

        def _post():
            return _requests.post(
                "http://localhost:9379/v1/rag/search",
                json={"query": query, "top_k": 5},
                timeout=30,
            )

        resp = await loop.run_in_executor(None, _post)
        data = resp.json()
        if data.get("count", 0) == 0:
            return "No relevant documents found in memory."
        return data["results"]
    except Exception as e:
        logger.error("recall failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("recall", "safe", "Semantic search over ingested documents", _recall)`

System prompt line:

```
  recall(query)                                  — semantic search over your ingested documents
```

- [ ] **Step 5: Run tests + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k recall -v` → PASS

```bash
git add agent_utils.py gemma_bridge.py tests/test_agent_tools.py
git commit -m "feat(agent): add recall tool + /v1/rag/search endpoint"
```

---

### Task 2: `say` tool

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _say


@pytest.mark.asyncio
async def test_say_invokes_say_command():
    with patch("subprocess.run") as mock_run:
        out = await _say("hello there")
    assert out.startswith("OK")
    assert mock_run.call_args.args[0] == ["say", "hello there"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_say_invokes_say_command -v`
Expected: FAIL `ImportError: cannot import name '_say'`

- [ ] **Step 3: Implement**

```python
async def _say(text: str) -> str:
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(["say", text], check=True, capture_output=True),
        )
        return "OK: spoken"
    except Exception as e:
        logger.error("say failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("say", "safe", "Speak text aloud via macOS say", _say)`
Prompt line: `  say(text)                                      — speak text aloud through the speakers`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k say -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add say (text-to-speech) tool"
```

---

### Task 3: `screenshot` tool

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _screenshot


@pytest.mark.asyncio
async def test_screenshot_uses_screencapture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("subprocess.run") as mock_run:
        out = await _screenshot("shot.png")
    assert out.startswith("OK")
    assert mock_run.call_args.args[0][0] == "screencapture"
    assert mock_run.call_args.args[0][1] == "-x"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_screenshot_uses_screencapture -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _screenshot(path: str = "") -> str:
    log_audit(f"SCREENSHOT: {path}")
    try:
        if not path:
            path = f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
        p = validate_path(path, must_exist=False)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["screencapture", "-x", str(p)], check=True, capture_output=True
            ),
        )
        return f"OK: saved to {p}"
    except Exception as e:
        logger.error("screenshot failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("screenshot", "risky", "Capture the screen to a PNG file", _screenshot)`
Prompt line: `  screenshot(path)                               — capture the screen to a PNG (path optional)`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k screenshot -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add screenshot tool"
```

---

### Task 4: `move_file` tool

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _move_file


@pytest.mark.asyncio
async def test_move_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hi")
    out = await _move_file("a.txt", "b.txt")
    assert out.startswith("OK")
    assert (tmp_path / "b.txt").read_text() == "hi"
    assert not (tmp_path / "a.txt").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_move_file -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _move_file(src: str, dst: str) -> str:
    log_audit(f"MOVE_FILE: {src} -> {dst}")
    try:
        s = validate_path(src)
        d = validate_path(dst, must_exist=False)
        import shutil as _shutil

        _shutil.move(str(s), str(d))
        return f"OK: moved {s} -> {d}"
    except Exception as e:
        logger.error("move_file failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("move_file", "risky", "Move or rename a file", _move_file)`
Prompt line: `  move_file(src, dst)                            — move or rename a file`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k move_file -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add move_file tool"
```

---

### Task 5: `delete_file` tool (sends to Trash)

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _delete_file


@pytest.mark.asyncio
async def test_delete_file_uses_finder_trash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "junk.txt").write_text("x")
    with patch("subprocess.run") as mock_run:
        out = await _delete_file("junk.txt")
    assert out.startswith("OK")
    script = mock_run.call_args.args[0][2]
    assert "Finder" in script and "delete" in script
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_delete_file_uses_finder_trash -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _delete_file(path: str) -> str:
    log_audit(f"DELETE_FILE: {path}")
    try:
        p = validate_path(path)
        script = f'tell application "Finder" to delete POSIX file "{p}"'
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["osascript", "-e", script], check=True, capture_output=True
            ),
        )
        return f"OK: moved to Trash: {p}"
    except Exception as e:
        logger.error("delete_file failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("delete_file", "risky", "Move a file to the Trash", _delete_file)`
Prompt line: `  delete_file(path)                              — move a file to the Trash (recoverable)`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k delete_file -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add delete_file (Trash) tool"
```

---

### Task 6: `read_csv` tool

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _read_csv


@pytest.mark.asyncio
async def test_read_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "d.csv").write_text("a,b\n1,2\n3,4\n")
    out = await _read_csv("d.csv")
    assert "a\tb" in out
    assert "1\t2" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_read_csv -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _read_csv(path: str) -> str:
    try:
        p = validate_path(path)
        import csv

        with open(p, newline="") as f:
            rows = list(csv.reader(f))
        lines = ["\t".join(r) for r in rows[:200]]
        suffix = "\n(truncated at 200 rows)" if len(rows) > 200 else ""
        return "\n".join(lines) + suffix
    except Exception as e:
        logger.error("read_csv failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("read_csv", "safe", "Read a CSV file as a table", _read_csv)`
Prompt line: `  read_csv(path)                                 — read a CSV file as a tab-separated table`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k read_csv -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add read_csv tool"
```

---

### Task 7: `json_query` tool

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _json_query


@pytest.mark.asyncio
async def test_json_query_on_raw_text():
    out = await _json_query('{"users": [{"name": "Ada"}]}', "users[0].name")
    assert "Ada" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_json_query_on_raw_text -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _json_query(path_or_text: str, expr: str) -> str:
    try:
        try:
            p = validate_path(path_or_text)
            data = json.loads(p.read_text())
        except (FileNotFoundError, PermissionError, OSError):
            data = json.loads(path_or_text)
        cur = data
        for part in expr.replace("[", ".").replace("]", "").split("."):
            if part == "":
                continue
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        return json.dumps(cur, indent=2)
    except Exception as e:
        logger.error("json_query failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("json_query", "safe", "Query JSON with a dotted path", _json_query)`
Prompt line: `  json_query(path_or_text, expr)                 — extract a value from JSON, e.g. "users[0].name"`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k json_query -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add json_query tool"
```

---

### Task 8: `read_ics` tool

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _read_ics


@pytest.mark.asyncio
async def test_read_ics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "c.ics").write_text(
        "BEGIN:VEVENT\nSUMMARY:Standup\nDTSTART:20260601T090000\n"
        "DTEND:20260601T093000\nEND:VEVENT\n"
    )
    out = await _read_ics("c.ics")
    assert "Standup" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_read_ics -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _read_ics(path: str) -> str:
    try:
        p = validate_path(path)
        events, cur = [], {}
        for raw in p.read_text().splitlines():
            line = raw.strip()
            if line == "BEGIN:VEVENT":
                cur = {}
            elif line == "END:VEVENT":
                events.append(cur)
            elif ":" in line:
                key, _, val = line.partition(":")
                key = key.split(";")[0]
                if key in ("SUMMARY", "DTSTART", "DTEND", "LOCATION"):
                    cur[key] = val
        if not events:
            return "No events found."
        out = []
        for e in events:
            line = (
                f"{e.get('DTSTART', '?')} - {e.get('DTEND', '?')}: "
                f"{e.get('SUMMARY', '(no title)')}"
            )
            if e.get("LOCATION"):
                line += f" @ {e['LOCATION']}"
            out.append(line)
        return "\n".join(out)
    except Exception as e:
        logger.error("read_ics failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("read_ics", "safe", "Parse events from an .ics file", _read_ics)`
Prompt line: `  read_ics(path)                                 — list events from a local .ics calendar file`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k read_ics -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add read_ics tool"
```

---

### Task 9: `sqlite_exec` tool

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _sqlite_exec


@pytest.mark.asyncio
async def test_sqlite_exec_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import sqlite3

    out1 = await _sqlite_exec("t.db", "CREATE TABLE t (x INTEGER)")
    assert out1.startswith("OK")
    out2 = await _sqlite_exec("t.db", "INSERT INTO t VALUES (1)")
    assert out2.startswith("OK")
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    conn.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_sqlite_exec_writes -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _sqlite_exec(db_path: str, sql: str) -> str:
    log_audit(f"SQLITE_EXEC: {db_path} - {sql[:200]}")
    try:
        p = validate_path(db_path, must_exist=False)
        import sqlite3

        loop = asyncio.get_running_loop()

        def _run():
            conn = sqlite3.connect(str(p))
            try:
                cur = conn.execute(sql)
                conn.commit()
                return f"OK: {cur.rowcount} row(s) affected"
            finally:
                conn.close()

        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.error("sqlite_exec failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("sqlite_exec", "risky", "Run a write statement on a SQLite DB", _sqlite_exec)`
Prompt line: `  sqlite_exec(db_path, sql)                      — run INSERT/UPDATE/DELETE/CREATE on a SQLite DB`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k sqlite_exec -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add sqlite_exec tool"
```

- [ ] **Step 5: Phase 1 gate**

Run: `bash .git/hooks/pre-push`
Expected: exits 0. If red, fix before Phase 2.

---

## Phase 2 — macOS Personal Automation

### Task 10: `_osascript` helper + `calendar_list` + `calendar_create`

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
from agent_utils import _calendar_list, _calendar_create


@pytest.mark.asyncio
async def test_calendar_list_runs_osascript():
    mock_res = MagicMock(stdout="Standup - date\n")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _calendar_list(3)
    assert "Standup" in out
    assert mock_run.call_args.args[0][0] == "osascript"


@pytest.mark.asyncio
async def test_calendar_create_builds_event():
    mock_res = MagicMock(stdout="")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _calendar_create("Lunch", "6/1/2026 12:00:00")
    assert out.startswith("OK")
    assert "make new event" in mock_run.call_args.args[0][2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k "calendar" -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement helper + tools**

```python
async def _osascript(script: str) -> str:
    loop = asyncio.get_running_loop()

    def _run():
        r = subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return r.stdout.strip()

    return await loop.run_in_executor(None, _run)


async def _calendar_list(days: int = 7) -> str:
    try:
        script = f"""
        set output to ""
        set startD to current date
        set endD to startD + ({int(days)} * days)
        tell application "Calendar"
            repeat with c in calendars
                repeat with e in (every event of c whose start date is greater than or equal to startD and start date is less than or equal to endD)
                    set output to output & (summary of e) & " - " & (start date of e as string) & linefeed
                end repeat
            end repeat
        end tell
        return output
        """
        out = await _osascript(script)
        return out or "No upcoming events."
    except Exception as e:
        logger.error("calendar_list failed: %s", e)
        return f"ERROR: {e}"


async def _calendar_create(
    title: str, start: str, end: str = "", notes: str = ""
) -> str:
    log_audit(f"CALENDAR_CREATE: {title} @ {start}")
    try:
        props = [f'summary:"{title}"', f'start date:(date "{start}")']
        props.append(f'end date:(date "{end or start}")')
        if notes:
            props.append(f'description:"{notes}"')
        script = f"""
        tell application "Calendar"
            tell calendar 1
                make new event with properties {{{", ".join(props)}}}
            end tell
        end tell
        """
        await _osascript(script)
        return f"OK: created event '{title}'"
    except Exception as e:
        logger.error("calendar_create failed: %s", e)
        return f"ERROR: {e}"
```

Register:

```python
register_tool("calendar_list", "safe", "List upcoming Calendar events", _calendar_list)
register_tool(
    "calendar_create", "risky", "Create a Calendar event", _calendar_create
)
```

Prompt lines:

```
  calendar_list(days)                            — list upcoming Calendar events (default 7 days)
  calendar_create(title, start, end, notes)      — create a Calendar event; dates like "6/1/2026 12:00:00"
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k calendar -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add osascript helper + calendar tools"
```

---

### Task 11: `reminders_list` + `reminders_create`

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
from agent_utils import _reminders_list, _reminders_create


@pytest.mark.asyncio
async def test_reminders_list():
    mock_res = MagicMock(stdout="Buy milk\n")
    with patch("subprocess.run", return_value=mock_res):
        out = await _reminders_list()
    assert "Buy milk" in out


@pytest.mark.asyncio
async def test_reminders_create():
    mock_res = MagicMock(stdout="")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _reminders_create("Call mom")
    assert out.startswith("OK")
    assert "make new reminder" in mock_run.call_args.args[0][2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k reminders -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _reminders_list(list_name: str = "") -> str:
    try:
        target = f'list "{list_name}"' if list_name else "default list"
        script = f"""
        tell application "Reminders"
            set output to ""
            repeat with r in (reminders of {target} whose completed is false)
                set output to output & (name of r) & linefeed
            end repeat
            return output
        end tell
        """
        out = await _osascript(script)
        return out or "No open reminders."
    except Exception as e:
        logger.error("reminders_list failed: %s", e)
        return f"ERROR: {e}"


async def _reminders_create(text: str, due: str = "") -> str:
    log_audit(f"REMINDERS_CREATE: {text}")
    try:
        props = [f'name:"{text}"']
        if due:
            props.append(f'due date:(date "{due}")')
        script = f"""
        tell application "Reminders"
            make new reminder with properties {{{", ".join(props)}}}
        end tell
        """
        await _osascript(script)
        return f"OK: added reminder '{text}'"
    except Exception as e:
        logger.error("reminders_create failed: %s", e)
        return f"ERROR: {e}"
```

Register:

```python
register_tool("reminders_list", "safe", "List open reminders", _reminders_list)
register_tool("reminders_create", "risky", "Create a reminder", _reminders_create)
```

Prompt lines:

```
  reminders_list(list)                           — list open reminders (list name optional)
  reminders_create(text, due)                    — add a reminder; due like "6/1/2026 09:00:00"
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k reminders -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add reminders tools"
```

---

### Task 12: `notes_search` + `notes_create`

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
from agent_utils import _notes_search, _notes_create


@pytest.mark.asyncio
async def test_notes_search():
    mock_res = MagicMock(stdout="Grocery list\n")
    with patch("subprocess.run", return_value=mock_res):
        out = await _notes_search("grocery")
    assert "Grocery" in out


@pytest.mark.asyncio
async def test_notes_create():
    mock_res = MagicMock(stdout="")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _notes_create("Ideas", "body text")
    assert out.startswith("OK")
    assert "make new note" in mock_run.call_args.args[0][2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k notes -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _notes_search(query: str) -> str:
    try:
        script = f"""
        tell application "Notes"
            set output to ""
            repeat with n in (notes whose name contains "{query}")
                set output to output & (name of n) & linefeed & (plaintext of n) & linefeed & "---" & linefeed
            end repeat
            return output
        end tell
        """
        out = await _osascript(script)
        return out or "No matching notes."
    except Exception as e:
        logger.error("notes_search failed: %s", e)
        return f"ERROR: {e}"


async def _notes_create(title: str, body: str) -> str:
    log_audit(f"NOTES_CREATE: {title}")
    try:
        html_body = f"<div><b>{title}</b></div><div>{body}</div>"
        script = f"""
        tell application "Notes"
            make new note at folder "Notes" with properties {{body:"{html_body}"}}
        end tell
        """
        await _osascript(script)
        return f"OK: created note '{title}'"
    except Exception as e:
        logger.error("notes_create failed: %s", e)
        return f"ERROR: {e}"
```

Register:

```python
register_tool("notes_search", "safe", "Search Apple Notes", _notes_search)
register_tool("notes_create", "risky", "Create an Apple Note", _notes_create)
```

Prompt lines:

```
  notes_search(query)                            — search Apple Notes by title and read matches
  notes_create(title, body)                      — create a new Apple Note
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k notes -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add notes tools"
```

---

### Task 13: `messages_read` + `send_message`

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
from agent_utils import _messages_read, _send_message


@pytest.mark.asyncio
async def test_messages_read_queries_db():
    with patch("agent_utils._messages_db_rows", return_value=[("Alice", "hi")]):
        out = await _messages_read(5)
    assert "Alice" in out and "hi" in out


@pytest.mark.asyncio
async def test_send_message_builds_script():
    mock_res = MagicMock(stdout="")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _send_message("+15551234567", "yo")
    assert out.startswith("OK")
    assert "send" in mock_run.call_args.args[0][2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k "messages or send_message" -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

Reading iMessages via AppleScript is unreliable, so read directly from the
local `chat.db` (read-only). A small helper isolates the DB query so tests can
patch it without a real database.

```python
def _messages_db_rows(limit: int) -> list[tuple[str, str]]:
    import sqlite3

    db = os.path.expanduser("~/Library/Messages/chat.db")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT h.id, m.text FROM message m "
            "JOIN handle h ON m.handle_id = h.ROWID "
            "WHERE m.text IS NOT NULL ORDER BY m.date DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()
    finally:
        conn.close()


async def _messages_read(limit: int = 20) -> str:
    log_audit(f"MESSAGES_READ: limit={limit}")
    try:
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, _messages_db_rows, int(limit))
        if not rows:
            return "No messages found."
        return "\n".join(f"{sender}: {text}" for sender, text in rows)
    except Exception as e:
        logger.error("messages_read failed: %s", e)
        return f"ERROR: {e}"


async def _send_message(recipient: str, text: str) -> str:
    log_audit(f"SEND_MESSAGE: to={recipient}")
    try:
        script = f"""
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{recipient}" of targetService
            send "{text}" to targetBuddy
        end tell
        """
        await _osascript(script)
        return f"OK: message sent to {recipient}"
    except Exception as e:
        logger.error("send_message failed: %s", e)
        return f"ERROR: {e}"
```

Register:

```python
register_tool("messages_read", "risky", "Read recent iMessages", _messages_read)
register_tool("send_message", "risky", "Send an iMessage", _send_message)
```

Prompt lines:

```
  messages_read(limit)                           — read your most recent iMessages
  send_message(recipient, text)                  — send an iMessage to a phone/email
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k "messages or send_message" -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add messages_read + send_message tools"
```

---

### Task 14: `mail_compose` (draft only)

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _mail_compose


@pytest.mark.asyncio
async def test_mail_compose_creates_draft():
    mock_res = MagicMock(stdout="")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        out = await _mail_compose("a@b.com", "Hi", "Body")
    assert out.startswith("OK")
    script = mock_run.call_args.args[0][2]
    assert "make new outgoing message" in script
    assert " send " not in script  # draft only, never auto-send
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_mail_compose_creates_draft -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _mail_compose(to: str, subject: str, body: str) -> str:
    log_audit(f"MAIL_COMPOSE: to={to} subject={subject}")
    try:
        script = f"""
        tell application "Mail"
            set msg to make new outgoing message with properties {{subject:"{subject}", content:"{body}", visible:true}}
            tell msg
                make new to recipient at end of to recipients with properties {{address:"{to}"}}
            end tell
        end tell
        """
        await _osascript(script)
        return f"OK: drafted email to {to} (review and send manually)"
    except Exception as e:
        logger.error("mail_compose failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("mail_compose", "risky", "Draft an email (no auto-send)", _mail_compose)`
Prompt line: `  mail_compose(to, subject, body)                — draft an email in Mail (you review and send)`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k mail_compose -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add mail_compose tool"
```

- [ ] **Step 5: Phase 2 gate**

Run: `bash .git/hooks/pre-push`
Expected: exits 0. Fix before Phase 3.

---

## Phase 3 — Multimodal (lean-native)

### Task 15: add `mlx-whisper` dep + `transcribe`

**Files:** Modify `requirements.txt`, `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Add dependency**

In `requirements.txt`, after the `mflux; sys_platform == "darwin"` line, add:

```
mlx-whisper; sys_platform == "darwin"
```

Then install: `.venv/bin/pip install "mlx-whisper; sys_platform == 'darwin'"`

- [ ] **Step 2: Write the failing test**

The test patches `mlx_whisper.transcribe` via `sys.modules` so it runs on any
platform/CI without the real package.

```python
from agent_utils import _transcribe


@pytest.mark.asyncio
async def test_transcribe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    fake = MagicMock()
    fake.transcribe.return_value = {"text": "  hello world  "}
    with patch.dict("sys.modules", {"mlx_whisper": fake}):
        out = await _transcribe("a.wav")
    assert out == "hello world"
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_transcribe -v`
Expected: FAIL `ImportError`

- [ ] **Step 4: Implement**

```python
async def _transcribe(path: str) -> str:
    try:
        p = validate_path(path)
        import mlx_whisper

        loop = asyncio.get_running_loop()

        def _run():
            result = mlx_whisper.transcribe(
                str(p), path_or_hf_repo="mlx-community/whisper-base-mlx"
            )
            return result["text"].strip()

        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.error("transcribe failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("transcribe", "safe", "Transcribe an audio file to text", _transcribe)`
Prompt line: `  transcribe(path)                               — transcribe an audio file to text (on-device)`

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k transcribe -v` → PASS

```bash
git add agent_utils.py requirements.txt tests/test_agent_tools.py
git commit -m "feat(agent): add transcribe tool (mlx-whisper)"
```

---

### Task 16: `describe_image`

**Files:** Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

**Note:** the `mlx_vlm` public API has shifted across releases. Before
implementing, confirm the installed API with
`.venv/bin/python -c "import mlx_vlm; print(dir(mlx_vlm))"` and check whether
`image_pipeline.py` already wraps it. The code below targets the
`load`/`generate` API; adjust call names to match the installed version if
they differ.

- [ ] **Step 1: Write the failing test**

```python
from agent_utils import _describe_image


@pytest.mark.asyncio
async def test_describe_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "p.png").write_bytes(b"\x89PNG")
    fake = MagicMock()
    fake.load.return_value = ("model", "processor")
    fake.generate.return_value = "a cat on a mat"
    with patch.dict("sys.modules", {"mlx_vlm": fake}):
        out = await _describe_image("p.png")
    assert "cat" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py::test_describe_image -v`
Expected: FAIL `ImportError`

- [ ] **Step 3: Implement**

```python
async def _describe_image(
    path: str, prompt: str = "Describe this image in detail."
) -> str:
    try:
        p = validate_path(path)
        import mlx_vlm

        loop = asyncio.get_running_loop()

        def _run():
            model, processor = mlx_vlm.load("mlx-community/llava-1.5-7b-4bit")
            return mlx_vlm.generate(
                model, processor, prompt, [str(p)], verbose=False
            )

        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.error("describe_image failed: %s", e)
        return f"ERROR: {e}"
```

Register: `register_tool("describe_image", "safe", "Describe an image on-device", _describe_image)`
Prompt line: `  describe_image(path, prompt)                   — describe/answer questions about an image (on-device)`

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k describe_image -v` → PASS

```bash
git add agent_utils.py tests/test_agent_tools.py
git commit -m "feat(agent): add describe_image tool (mlx-vlm)"
```

---

### Task 17: `ocr_image` (Vision framework via Swift helper)

**Files:** Create `scripts/ocr_vision.swift`; Modify `agent_utils.py`; Test `tests/test_agent_tools.py`

- [ ] **Step 1: Create the Swift helper**

Create `scripts/ocr_vision.swift`:

```swift
import Vision
import AppKit
import Foundation

let args = CommandLine.arguments
guard args.count > 1,
      let image = NSImage(contentsOfFile: args[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
else {
    FileHandle.standardError.write("ERROR: cannot load image\n".data(using: .utf8)!)
    exit(1)
}

let request = VNRecognizeTextRequest { req, _ in
    let observations = req.results as? [VNRecognizedTextObservation] ?? []
    let text = observations
        .compactMap { $0.topCandidates(1).first?.string }
        .joined(separator: "\n")
    print(text)
}
request.recognitionLevel = .accurate

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try? handler.perform([request])
```

- [ ] **Step 2: Write the failing tests**

The first test patches the OCR subprocess so it runs on CI. The second forces
the subprocess to fail and asserts the tool falls back to `_describe_image`,
which is patched.

```python
from agent_utils import _ocr_image


@pytest.mark.asyncio
async def test_ocr_image_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "p.png").write_bytes(b"\x89PNG")
    mock_res = MagicMock(stdout="INVOICE 42", returncode=0)
    with patch("subprocess.run", return_value=mock_res):
        out = await _ocr_image("p.png")
    assert "INVOICE 42" in out


@pytest.mark.asyncio
async def test_ocr_image_falls_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "p.png").write_bytes(b"\x89PNG")
    with patch("subprocess.run", side_effect=Exception("swift missing")):
        with patch(
            "agent_utils._describe_image",
            new=AsyncMock(return_value="fallback text"),
        ):
            out = await _ocr_image("p.png")
    assert "fallback" in out
```

Add `AsyncMock` to the imports at the top of the test file:
`from unittest.mock import AsyncMock, MagicMock, patch`

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k ocr_image -v`
Expected: FAIL `ImportError`

- [ ] **Step 4: Implement**

```python
async def _ocr_image(path: str) -> str:
    try:
        p = validate_path(path)
        helper = Path(__file__).parent / "scripts" / "ocr_vision.swift"
        loop = asyncio.get_running_loop()

        def _run():
            r = subprocess.run(
                ["swift", str(helper), str(p)],
                check=True,
                capture_output=True,
                text=True,
            )
            return r.stdout.strip()

        text = await loop.run_in_executor(None, _run)
        return text or "(no text found)"
    except Exception as e:
        logger.warning("ocr_image native failed, falling back to VLM: %s", e)
        return await _describe_image(
            path, prompt="Transcribe all text visible in this image."
        )
```

Register: `register_tool("ocr_image", "safe", "Extract text from an image (OCR)", _ocr_image)`
Prompt line: `  ocr_image(path)                                — extract text from an image via OCR`

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/python -m pytest tests/test_agent_tools.py -k ocr_image -v` → PASS

```bash
git add agent_utils.py scripts/ocr_vision.swift tests/test_agent_tools.py
git commit -m "feat(agent): add ocr_image tool (Vision framework + VLM fallback)"
```

---

### Task 18: Final gate + PROGRESS log

**Files:** Modify `PROGRESS.md`

- [ ] **Step 1: Update PROGRESS.md**

Add a new session entry to `PROGRESS.md` summarizing the tool expansion (the
~22 new tools by phase, the new `/v1/rag/search` endpoint, the new
`mlx-whisper` dependency, and the `scripts/ocr_vision.swift` helper). Follow
the existing session-entry format already in the file.

- [ ] **Step 2: Full CI gate**

Run: `bash .git/hooks/pre-push`
Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: log agent tool registry expansion"
```

- [ ] **Step 4: Manual smoke test (on the Mac, outside CI)**

Restart the bridge so it serves the new endpoint and tools (per the runtime
note, it is a launchd service):

```bash
launchctl kickstart -k gui/$(id -u)/com.gemini.litert
```

Then exercise a few tools through the agent UI: `say("test")`,
`screenshot()`, `calendar_list(7)`, and `recall("…")` after ingesting a doc.
Confirm risky tools surface the confirm prompt before running.

---

## Self-Review Notes

- **Spec coverage:** all 22 tools from the design map to Tasks 1–17; security (Trash delete, draft-only mail, risky gating), testing (mocked OS/HTTP), and CI gate are covered in cross-cutting steps and the per-phase gates.
- **Sandbox:** every file-path tool uses `validate_path`, preserving the project-root boundary.
- **Type consistency:** `_osascript` (Task 10) is reused by Tasks 10–14; `_describe_image` (Task 16) is reused by `_ocr_image` (Task 17) — both defined before use in task order.
- **Known risk:** AppleScript string interpolation does not escape embedded quotes; a title/body containing a `"` will break the script. Acceptable for v1; a future hardening pass can escape inputs.
