# Agent Tool Registry Expansion

Expand the agent's tool registry with ~22 new tools across five areas:
semantic recall, macOS personal automation, on-device audio, on-device
vision, and a set of smaller data/file fill-ins. Delivered as **one spec,
built in three phases** so each batch can be verified before the next.

---

## Shared Pattern

Every new tool follows the existing mold, so there are no new abstractions:

- `async def _name(...) -> str` returning `OK: …` / `ERROR: …`.
- Heavy dependencies are **imported lazily inside the function**, so a missing
  optional dep only breaks that one tool.
- File arguments go through `validate_path()`; risky actions call
  `log_audit()`.
- Blocking work is offloaded with `run_in_executor`.
- Each tool is wired up with **three edits**: the `async def`, a
  `register_tool(...)` line, and one entry in the `TOOLS AVAILABLE` block of
  the system prompt (the model only "sees" a tool that is listed there).

The risk gate is automatic: any tool registered as `risky` triggers an SSE
`confirm_request` and blocks for your approval (up to 300s) before running. No
extra plumbing — write/send/delete tools just set `risk="risky"`.

---

## Phase 1 — Quick Wins (zero or one new dependency)

- **`recall(query)`** — safe. Semantic search over already-ingested documents.
  Adds a bridge endpoint `/v1/rag/search` backed by
  `pdf_pipeline.retrieve_chunks`; the tool POSTs to it exactly like
  `generate_image` already does, avoiding a circular import.
- **`say(text)`** — safe. Text-to-speech via the macOS `say` command.
- **`screenshot(path?)`** — risky. Capture the screen via `screencapture`.
- **`move_file(src, dst)`** — risky. Move/rename via `shutil` (covers rename).
- **`delete_file(path)`** — risky. Sends the file to **Trash**, not a hard
  remove, so it stays recoverable.
- **`read_csv(path)`** — safe. Parse CSV to a tab-separated table (same output
  shape as `sqlite_query`).
- **`json_query(path_or_text, expr)`** — safe. jq-style dotted-path lookups
  over JSON without writing Python each time.
- **`read_ics(path)`** — safe. Parse events from a local `.ics` file.
- **`sqlite_exec(db_path, sql)`** — risky. Run non-SELECT statements
  (INSERT/UPDATE/DELETE/CREATE), expanding today's read-only boundary.

---

## Phase 2 — macOS Personal Automation (all via `osascript`)

- **`calendar_list(days=7)`** — safe. List upcoming events.
- **`calendar_create(title, start, end?, notes?)`** — risky. Create an event.
- **`reminders_list(list?)`** — safe. List reminders.
- **`reminders_create(text, due?)`** — risky. Add a reminder.
- **`notes_search(query)`** — safe. Search and read Apple Notes.
- **`notes_create(title, body)`** — risky. Create a note.
- **`messages_read(limit=20)`** — risky. Read recent iMessages (privacy
  sensitive, so gated even though it only reads).
- **`send_message(recipient, text)`** — risky. Send an iMessage.
- **`mail_compose(to, subject, body)`** — risky. Creates a **draft** — never
  auto-sends — so a human always hits send.

---

## Phase 3 — Multimodal (lean-native)

- **`transcribe(path)`** — safe. Speech-to-text via `mlx-whisper` (the one new
  darwin-only dependency this work adds).
- **`describe_image(path, prompt?)`** — safe. Vision description via
  `mlx-vlm`, which is **already shipped** in requirements.
- **`ocr_image(path)`** — safe. Text extraction via the macOS Vision framework
  through a small Swift helper (no new Python dep). If the helper fails, it
  falls back to `describe_image`.

---

## Cross-Cutting Concerns

### Security

All new file / DB / send / delete tools pass through `validate_path` +
`log_audit` and are registered `risky`, so they are auto-gated. Two extra
defense-in-depth choices: `delete_file` uses Trash, and `mail_compose` only
drafts.

### Testing

Unit tests stub the OS calls and assert argument validation and error
paths — no live Calendar, Messages, or model calls in CI. The osascript,
audio, and vision live paths are darwin-only and excluded from the CI lane,
mirroring how the existing `mlx` / GPU tests are already handled.

### CI Gate

`bash .git/hooks/pre-push` must exit 0 before any phase is called done, per the
project mandate. Each phase is verified green before the next begins.

---

## Known Design Risk

`ocr_image` relies on a tiny compiled Swift snippet against the Vision
framework. If that proves fiddly on this machine, the fallback is routing OCR
through `mlx-vlm` (the same model as `describe_image`). Vision-native is
attempted first because it is faster and lighter.
