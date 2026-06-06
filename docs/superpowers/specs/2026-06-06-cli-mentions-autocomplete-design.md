# LocalLLM CLI — `@` File Mentions & `/` Command Autocomplete

## Problem

The `localllm` TUI already knows its launch directory. `LocalLLMApp` captures
`self._cwd = Path(os.getcwd()).resolve()` (`app.py:72`), passes it to the bridge
on every run (`app.py:169`), and `agent_utils.validate_path` resolves relative
paths against it and sandboxes to it via `current_cwd_var` (`agent_utils.py:142`).
So at the plumbing level, "look at files in the directory I launched from" is
already wired.

The user-visible failure is different: **the model ignores file references.**
With a small local model, asking "summarize README.md" relies on the model
_choosing_ to call the `read_file` tool — which it often doesn't. The file never
reaches the context, so it feels like the CLI doesn't know where it is.

Two interaction affordances that make Claude Code usable are also missing:

- **No `@` file picker.** The input box (`widgets/input_box.py`) is a plain
  Textual `Input` with up/down history and nothing else. There is no way to
  browse or reference files by name.
- **No `/` command autocomplete.** Slash commands are parsed only _after_ Enter
  (`commands.py`); they are never suggested or completed as you type, so they
  aren't discoverable.

## Decision

Add two terminal affordances driven by a single custom completion menu, plus a
deterministic mention-expansion step:

1. **`@path` mentions are expanded client-side at submit time.** When a line
   contains `@some/file`, the CLI itself reads the file and inlines its contents
   in a `<file path="...">…</file>` block before sending to the bridge. The model
   _always_ sees the file — it no longer depends on the model deciding to call
   `read_file`. This is the direct fix for "the model ignored it."

2. **`@` triggers a recursive fuzzy file picker.** Typing `@` followed by a
   fragment searches the whole tree under the session cwd (skipping `.git`,
   `node_modules`, `.venv`, and friends), ranks matches, and shows them in a
   dropdown. Selecting one completes the `@token` to the full repo-relative path.

3. **`/` triggers a command autocomplete menu.** Typing `/` at the start of the
   line lists every slash command with its one-line summary, filtered as you
   type. Selecting one inserts the command.

All completion **logic is pure and lives outside Textual** (`completions.py`,
`mentions.py`) so it is unit-tested without a TTY; the Textual widget
(`completion_menu.py`) is a thin shell.

**Approach chosen: a custom overlay menu widget.** Rejected alternatives:
`textual-autocomplete` (new dependency to prove green across the Python 3.10–3.13
CI matrix; its whole-input completion model fights mid-line `@token` completion)
and Textual's built-in `Suggester` (single inline ghost-text suggestion, no
browsable list — defeats command discovery and multi-file matching). A hand-built
widget takes no new dependency and matches the existing pattern in
`widgets/model_picker.py` and `widgets/confirm_modal.py`.

## Goals

- `@file` deterministically puts file contents in front of the model, regardless
  of whether the model would have called `read_file`.
- `@` offers a recursive, fuzzy, ranked file picker scoped to the session cwd.
- `/` offers a discoverable, filtered command menu sourced from one command
  table (no drift between help text and the menu).
- A stray `@huge.log` can never silently corrupt output or detonate the local
  model's context: a per-file size cap truncates with a visible marker and a loud
  transcript warning.
- Completion and expansion logic is unit-testable in CI with no TTY and no
  network.
- No new runtime dependency; `requirements.txt` is unchanged.
- No existing behavior is removed (input history, slash dispatch, `/cwd`, the
  bridge-side `read_file` tool all keep working).

## Non-goals

- No `.gitignore` parsing in v1 — a curated ignore set is enough and predictable.
  (`.gitignore` support is a clean future extension behind the same function.)
- No `@` references to files **outside** the session cwd. The mental model is
  "files in the directory I launched from"; `/cwd <path>` already re-roots the
  session for anything else.
- No image/binary embedding via `@`. Binary files are detected and refused with a
  warning rather than inlined as garbage.
- No change to the bridge, `agent.py`, or `agent_utils.py`. This is a CLI-only
  feature; the existing cwd sandbox stays as the fallback for tool-driven reads.
- No fuzzy matching for `/` commands (prefix filtering only) — the command set is
  tiny and prefix matching is unambiguous.

## Design

### §1 Module layout

New files (all under the `localllm` package):

| Path                                  | Responsibility                                                      |
| ------------------------------------- | ------------------------------------------------------------------- |
| `localllm/completions.py`             | Pure candidate computation: `fuzzy_find_files`, `slash_candidates`. |
| `localllm/mentions.py`                | Pure `@path` → `<file>` expansion with sandbox + size cap.          |
| `localllm/widgets/completion_menu.py` | Thin Textual `OptionList` overlay driven by the input box.          |

Modified files:

| Path                            | Change                                                                                   |
| ------------------------------- | ---------------------------------------------------------------------------------------- |
| `localllm/widgets/input_box.py` | Detect triggers on change; show/filter/accept/dismiss the menu; key routing.             |
| `localllm/commands.py`          | Extract a `COMMANDS` data table (name + summary); `HELP_TEXT` and the menu read from it. |
| `localllm/app.py`               | Call `expand_mentions` in the submit worker; show `📎 attached` lines and warnings.      |

New tests: `tests/test_cli_completions.py`, `tests/test_cli_mentions.py`, and a
menu interaction case added to the existing TUI smoke coverage.

### §2 `completions.py` (pure)

```python
IGNORE_DIRS = {".git", "node_modules", ".venv", "__pycache__",
               ".pytest_cache", ".ruff_cache", "mlx_models", ".worktrees"}

def fuzzy_find_files(root: str | Path, query: str, *, limit: int = 20) -> list[str]:
    """Repo-relative paths under `root` matching `query`, best first.

    Walks the tree under root once, pruning IGNORE_DIRS. Ranks by a simple
    subsequence/substring score (exact-substring beats scattered subsequence;
    matches earlier in the basename beat matches deep in the path). Returns at
    most `limit` POSIX-style relative paths. Empty query → first `limit` files
    in a stable walk order."""

def slash_candidates(query: str) -> list[tuple[str, str]]:
    """(command, summary) pairs whose command starts with `query` (e.g. '/mo').
    Sourced from commands.COMMANDS. Bare '/' returns all commands."""
```

Ranking is intentionally simple (no external fuzzy lib): score each path,
sort by `(score, path)`, slice to `limit`. The walk is capped — it stops after
visiting a generous file ceiling (e.g. 20k entries) so a pathological tree can't
hang the keystroke handler.

### §3 `mentions.py` (pure)

```python
MAX_FILE_BYTES = 100_000  # 100 KB per @-mention

@dataclass
class Expansion:
    text: str               # prompt sent to bridge: original line (@tokens kept
                            # readable) + appended <file> blocks
    attached: list[tuple[str, int]]   # (relpath, bytes_sent)
    warnings: list[str]

def expand_mentions(text: str, cwd: str | Path, *, max_bytes=MAX_FILE_BYTES) -> Expansion:
    """Find @path tokens, read each file under cwd, append a <file> block.

    For each unique @token:
      - resolve against cwd; reject if outside cwd (sandbox) or missing →
        a warning, token left literal, nothing attached.
      - reject binary files (NUL byte in first 8 KB) → warning.
      - read up to max_bytes; if larger, truncate and append
        '\\n[truncated N bytes]' and add a warning.
    Returns the prompt = original text + '\\n\\n' + concatenated
    <file path="rel">…</file> blocks. The visible @token stays in `text` so the
    transcript still reads naturally."""
```

Token grammar: `@` followed by a run of non-whitespace path characters, not
preceded by another word character (so an email like `a@b.com` is not a
mention). Sandbox resolution mirrors `agent_utils.validate_path`: expand `~`,
join relative tokens to cwd, `resolve()`, and require the result is
`relative_to(cwd)`.

### §4 The completion menu widget

`CompletionMenu(OptionList)` floats above the input (Textual CSS `layer` /
`dock: bottom` above the `InputBox`). It is a dumb view:

- `show(items)` populates options and makes it visible; `hide()` clears focus
  state and hides it.
- It exposes the highlighted value; it does not read the input or mutate text.
- It posts a `CompletionMenu.Selected(value)` message on Enter/Tab/click.

The `InputBox` owns all coordination so key handling stays in one place.

### §5 Input box behavior

On every `Input.Changed`, `InputBox` computes the active trigger from the text
and caret position:

- text starts with `/` and caret is within the first token → **command mode**:
  `slash_candidates(token)`.
- the token under the caret starts with `@` → **file mode**:
  `fuzzy_find_files(cwd, token_after_at)`.
- otherwise → hide the menu.

While the menu is open, ↑/↓ move the highlight, **Tab/Enter accept**, **Esc**
dismisses (and a second Esc/Enter behaves normally). History (↑/↓) is suppressed
only while the menu is open, so existing history navigation is preserved when it
is closed. Accepting a candidate splices it into the text:

- command: replace the leading token with the chosen command + trailing space.
- file: replace the `@token` under the caret with `@<relpath>` + trailing space.

The widget needs the session cwd; `app.py` passes it in (and updates it when
`/cwd` changes) so file search always targets the live root.

### §6 Submit path (`app.py`)

In `_process_submit`, before the slash-command dispatch and bridge round-trip,
run:

```python
exp = expand_mentions(text, self._cwd)
for rel, n in exp.attached:
    transcript.write_status(f"📎 attached: {rel} ({_human(n)})")
for w in exp.warnings:
    transcript.write_error(w)   # e.g. "skipped @x.png (binary)" / "truncated …"
prompt = exp.text  # text + injected <file> blocks
```

`transcript.write_user(text)` still shows the **original** typed line (with the
readable `@path`), while the bridge receives `exp.text` (with the inlined file
blocks). Slash commands are detected on the original `text` and short-circuit
before expansion, so `/`-lines are never file-expanded.

### §7 Command table (`commands.py`)

Replace the hardcoded `HELP_TEXT` + dispatch duplication with:

```python
COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show this help."),
    ("/model", "Switch model. Bare /model opens a list."),
    ("/clear", "Clear the transcript."),
    ("/tools", "List available tools (safe vs risky)."),
    ("/cwd", "Change session cwd (sandbox root)."),
    ("/reconnect", "Next prompt will retry the bridge."),
    ("/quit", "Exit the CLI."),
]
```

`HELP_TEXT` is generated from `COMMANDS`; `slash_candidates` reads it; `dispatch`
is unchanged in behavior. One source of truth, no drift.

### §8 Error handling

- Missing / out-of-sandbox / binary `@file`: warning in the transcript, token
  left literal, no attachment, no crash.
- Oversized file: truncated with an inline `[truncated N bytes]` marker plus a
  warning — never silently dropped.
- Any exception inside the menu/keystroke path is caught and logged to
  `~/.localllm/cli.log` (same defensive posture as `_process_submit`); the TUI
  stays alive.

### §9 Testing

- `test_cli_completions.py` — fuzzy ranking order, IGNORE_DIRS pruning, result
  cap, empty-query behavior; `slash_candidates` prefix filtering and bare `/`.
- `test_cli_mentions.py` — single/multiple mentions, content inlined verbatim,
  size-cap truncation + marker, missing file → warning, binary refused,
  `@../outside` rejected, `a@b.com` not treated as a mention.
- TUI smoke (`run_test()` Pilot) — type `/`, assert the menu opens with commands;
  type `@`, assert it lists cwd files; accept one and assert the text splices.

All pure-logic tests run in default CI (no marker, no TTY, no network). Done =
green `bash .git/hooks/pre-push`.

## File-by-file summary

- **New:** `localllm/completions.py`, `localllm/mentions.py`,
  `localllm/widgets/completion_menu.py`,
  `tests/test_cli_completions.py`, `tests/test_cli_mentions.py`.
- **Modified:** `localllm/widgets/input_box.py` (trigger detection + menu
  coordination), `localllm/commands.py` (`COMMANDS` table), `localllm/app.py`
  (mention expansion + cwd hand-off to the input box), TUI smoke test.
- **Untouched:** `gemma_bridge.py`, `agent.py`, `agent_utils.py`,
  `requirements.txt`.
