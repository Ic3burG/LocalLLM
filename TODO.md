# UI Vitals Dashboard Tasks

- [x] Task 1: Update scripts/smoke_test.py for JSON output
- [x] Task 2: Update gemma-web/server.js with new endpoint
- [x] Task 3: Redesign index.html Settings Modal to Tabbed Interface
- [x] Task 4: Implement Vitals Polling and Integrity Check Logic

---

# Tool Backlog

Tools to add to the agent in a future session.

## Medium Priority

- [x] `http_request(method, url, headers, body)` — risky — POST/PUT/DELETE with custom headers; unlocks GitHub API, Notion, etc. `web_fetch` is GET-only.
- [x] `notify(title, message)` — safe — macOS system notification via `osascript`; useful for alerting on long-running task completion.
- [x] `system_info()` — safe — CPU/memory/disk via `psutil` (already a dependency); useful for monitoring and self-diagnostics.

## Lower Priority

- [x] `sqlite_query(db_path, sql)` — risky — run read-only SQL against a local SQLite database.
- [x] `diff_files(path_a, path_b)` — safe — unified diff of two files; useful when the model is comparing or rewriting content.
