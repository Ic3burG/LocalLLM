# LocalLLM CLI — `@` Mentions & `/` Autocomplete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `@file` picker that deterministically injects file contents into the prompt, and a `/command` autocomplete menu, to the `localllm` Textual TUI.

**Architecture:** Pure logic modules (`completions.py`, `mentions.py`) hold all behavior (fuzzy search, trigger parsing, `@`-expansion with sandbox + size cap) and are unit-tested with no TTY. A thin Textual overlay widget (`completion_menu.py`) renders candidates; `InputBox` drives it (refresh on `Input.Changed`, navigate/accept in `on_key`); `app.py` expands mentions in the submit worker.

**Tech Stack:** Python 3.10+ (CI matrix 3.10/3.13), Textual 8.x (already pinned), pytest with `asyncio_mode=auto`. **No new dependency.**

**Spec:** `docs/superpowers/specs/2026-06-06-cli-mentions-autocomplete-design.md`

---

## Project conventions (apply to every task)

- **Format on save.** The `pre-commit` hook runs `ruff format` + `prettier --write` on staged files. Just `git add` + `git commit`; the hook formats and re-verifies.
- **Pre-push gate.** Before declaring the feature done, run `bash .git/hooks/pre-push` and confirm exit 0 (this mirrors CI per `CLAUDE.md`). Never use `--no-verify`.
- **No bridge restart needed.** This feature is CLI-only — it does not touch `gemma_bridge.py`, `agent.py`, or `agent_utils.py`.
- **Test markers.** Pure-logic tests need no marker (run in default CI). TUI Pilot tests are marked `@pytest.mark.needs_tty`; these **do** run in CI (under `-m "not needs_gpu"`) headless via `App.run_test()` — verified against the existing `tests/test_tui_smoke.py`.
- **Run a single test:** `.venv/bin/python -m pytest tests/<file>::<name> -v`.
- **Run a `needs_tty` test:** add `-m "not needs_gpu"` (the `pytest.ini` default `-m "not needs_tty"` otherwise deselects it), e.g. `.venv/bin/python -m pytest tests/test_tui_completion.py -m "not needs_gpu" -q`.

---

## Files this plan creates or modifies

### New files

| Path                                  | Responsibility                                                                                               |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `localllm/completions.py`             | Pure: `IGNORE_DIRS`, `fuzzy_find_files`, `slash_candidates`, `Trigger`, `parse_trigger`, `apply_completion`. |
| `localllm/mentions.py`                | Pure: `MAX_FILE_BYTES`, `Expansion`, `expand_mentions`, `human_size`.                                        |
| `localllm/widgets/completion_menu.py` | Thin `OptionList` overlay; `show`/`hide`/`current_value`; posts `Picked`.                                    |
| `tests/test_cli_completions.py`       | Unit tests for `completions.py`.                                                                             |
| `tests/test_cli_mentions.py`          | Unit tests for `mentions.py`.                                                                                |
| `tests/test_tui_completion.py`        | Pilot interaction tests (`needs_tty`).                                                                       |

### Modified files

| Path                            | Change                                                                                                                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `localllm/commands.py`          | Add `COMMANDS` data table; derive `HELP_TEXT` from it (behavior of `dispatch` unchanged).                                                                                    |
| `localllm/widgets/input_box.py` | Add `cwd`, completion refresh on change, key routing (nav/accept/dismiss), `apply_value`.                                                                                    |
| `localllm/app.py`               | Compose `CompletionMenu`; `Screen` layers; `on_input_changed`/`on_completion_menu_picked`; expand mentions in `_process_submit`; hand cwd to the input box (mount + `/cwd`). |
| `tests/test_cli_commands.py`    | Add one test asserting `COMMANDS` drives `HELP_TEXT`.                                                                                                                        |

---

## Task 1: `COMMANDS` table in `commands.py`

Promote the slash-command list to data so the `/` menu and help text share one source.

**Files:**

- Modify: `localllm/commands.py`
- Test: `tests/test_cli_commands.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_cli_commands.py`:

```python
def test_commands_table_drives_help():
    from localllm.commands import COMMANDS, HELP_TEXT

    names = [name for name, _ in COMMANDS]
    assert "/help" in names
    assert "/quit" in names
    # Every command appears in the generated help text.
    for name in names:
        assert name in HELP_TEXT
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_commands.py::test_commands_table_drives_help -v`
Expected: FAIL — `ImportError: cannot import name 'COMMANDS'`.

- [ ] **Step 3: Implement the table**

In `localllm/commands.py`, replace the hardcoded `HELP_TEXT` block (lines 8–15) with:

```python
COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show this help."),
    ("/model", "Switch model. Bare /model opens a selectable list."),
    ("/clear", "Clear the transcript."),
    ("/tools", "List available tools (safe vs risky)."),
    ("/cwd", "Change session cwd (sandbox root)."),
    ("/reconnect", "Next prompt will retry the bridge probe."),
    ("/quit", "Exit the CLI."),
]


def _build_help() -> str:
    width = max(len(name) for name, _ in COMMANDS)
    lines = ["Slash commands:"]
    for name, summary in COMMANDS:
        lines.append(f"  {name:<{width}}  {summary}")
    return "\n".join(lines)


HELP_TEXT = _build_help()
```

Leave the rest of the file (`CommandResult`, `_tools_text`, `dispatch`) unchanged.

- [ ] **Step 4: Run the full commands test file, verify pass**

Run: `.venv/bin/python -m pytest tests/test_cli_commands.py -v`
Expected: PASS — the new test plus all 11 existing tests (they only assert substrings like `/help`, `usage`, `retry`, `unknown`, all still present).

- [ ] **Step 5: Commit**

```bash
git add localllm/commands.py tests/test_cli_commands.py
git commit -m "refactor(cli): data-driven COMMANDS table feeds help + (soon) autocomplete"
```

---

## Task 2: `slash_candidates` in `completions.py`

**Files:**

- Create: `localllm/completions.py`
- Test: `tests/test_cli_completions.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_completions.py`:

```python
from localllm.completions import slash_candidates


def test_slash_candidates_bare_returns_all():
    out = slash_candidates("/")
    names = [name for name, _ in out]
    assert "/help" in names
    assert len(names) >= 7


def test_slash_candidates_prefix_filters():
    out = slash_candidates("/mo")
    assert [name for name, _ in out] == ["/model"]


def test_slash_candidates_no_match():
    assert slash_candidates("/zzz") == []
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_completions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'localllm.completions'`.

- [ ] **Step 3: Implement**

Create `localllm/completions.py`:

```python
"""Pure completion logic for the TUI input box (no Textual imports)."""

from __future__ import annotations

from localllm.commands import COMMANDS


def slash_candidates(query: str) -> list[tuple[str, str]]:
    """(command, summary) pairs whose command starts with `query`.

    `query` includes the leading slash (e.g. "/mo"); bare "/" returns all.
    """
    return [(name, summary) for name, summary in COMMANDS if name.startswith(query)]
```

- [ ] **Step 4: Run it, verify pass**

Run: `.venv/bin/python -m pytest tests/test_cli_completions.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add localllm/completions.py tests/test_cli_completions.py
git commit -m "feat(cli): slash_candidates command-prefix completion"
```

---

## Task 3: `parse_trigger` + `apply_completion` in `completions.py`

Pure parsing of "what is the user completing right now" and "splice the chosen value in."

**Files:**

- Modify: `localllm/completions.py`
- Test: `tests/test_cli_completions.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_cli_completions.py`:

```python
from localllm.completions import Trigger, apply_completion, parse_trigger


def test_parse_command_trigger():
    t = parse_trigger("/mo", 3)
    assert t == Trigger(kind="command", query="/mo", start=0, end=3)


def test_parse_command_stops_after_space():
    # caret is in the argument, not the command token
    assert parse_trigger("/model gem", 10) is None


def test_parse_file_trigger():
    t = parse_trigger("read @ser", 9)
    assert t == Trigger(kind="file", query="ser", start=5, end=9)


def test_parse_email_is_not_a_file_trigger():
    assert parse_trigger("mail a@b.com", 12) is None


def test_parse_plain_text_is_none():
    assert parse_trigger("hello", 5) is None


def test_apply_command_completion():
    t = parse_trigger("/mo", 3)
    text, cursor = apply_completion("/mo", t, "/model")
    assert text == "/model "
    assert cursor == 7


def test_apply_file_completion():
    t = parse_trigger("read @ser", 9)
    text, cursor = apply_completion("read @ser", t, "@src/server.js")
    assert text == "read @src/server.js "
    assert cursor == len("read @src/server.js ")
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_cli_completions.py -k "parse or apply" -v`
Expected: FAIL — `ImportError: cannot import name 'Trigger'`.

- [ ] **Step 3: Implement**

First, set the import block at the very top of `localllm/completions.py` to
exactly this (ruff selects `I`, so order matters — stdlib before first-party):

```python
from __future__ import annotations

from dataclasses import dataclass

from localllm.commands import COMMANDS
```

Then append these definitions to the end of the file (after `slash_candidates`):

```python
@dataclass(frozen=True)
class Trigger:
    kind: str  # "command" | "file"
    query: str  # command: "/mo" (slash included); file: "ser" (no @)
    start: int  # index where the replaced token begins
    end: int  # index where the replaced token ends (the caret)


def parse_trigger(text: str, cursor: int) -> Trigger | None:
    """Identify an active completion trigger at the caret, or None."""
    cursor = max(0, min(cursor, len(text)))
    before = text[:cursor]
    # Command mode: line starts with "/" and the caret is still in the first
    # token (no whitespace typed yet).
    if text.startswith("/") and not any(c.isspace() for c in before):
        return Trigger(kind="command", query=before, start=0, end=cursor)
    # File mode: the whitespace-delimited token ending at the caret starts "@".
    start = cursor
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    token = text[start:cursor]
    if token.startswith("@"):
        return Trigger(kind="file", query=token[1:], start=start, end=cursor)
    return None


def apply_completion(text: str, trigger: Trigger, replacement: str) -> tuple[str, int]:
    """Splice `replacement` over the trigger span; return (new_text, new_cursor).

    A trailing space is appended so the user can keep typing immediately.
    """
    new_text = text[: trigger.start] + replacement + " " + text[trigger.end :]
    new_cursor = trigger.start + len(replacement) + 1
    return new_text, new_cursor
```

(`a@b.com` → the token ending at the caret is `a@b.com`, which does not start
with `@`, so it is not a file trigger.)

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_cli_completions.py -v`
Expected: PASS (10 passed total in this file).

- [ ] **Step 5: Commit**

```bash
git add localllm/completions.py tests/test_cli_completions.py
git commit -m "feat(cli): parse_trigger + apply_completion caret logic"
```

---

## Task 4: `fuzzy_find_files` in `completions.py`

Recursive, ranked, ignore-pruned file search under the session cwd.

**Files:**

- Modify: `localllm/completions.py`
- Test: `tests/test_cli_completions.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_cli_completions.py`:

```python
from localllm.completions import fuzzy_find_files


def test_fuzzy_finds_by_fragment(tmp_path):
    (tmp_path / "gemma-web").mkdir()
    (tmp_path / "gemma-web" / "server.js").write_text("x")
    (tmp_path / "localllm").mkdir()
    (tmp_path / "localllm" / "control_server.py").write_text("x")
    (tmp_path / "readme.md").write_text("x")
    out = fuzzy_find_files(tmp_path, "server")
    assert "gemma-web/server.js" in out
    assert "localllm/control_server.py" in out
    assert "readme.md" not in out


def test_fuzzy_prunes_ignore_dirs(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "y.js").write_text("x")
    (tmp_path / "keep.py").write_text("x")
    assert fuzzy_find_files(tmp_path, "") == ["keep.py"]


def test_fuzzy_basename_match_ranks_first(tmp_path):
    (tmp_path / "server.py").write_text("x")
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "server_helpers.py").write_text("x")
    out = fuzzy_find_files(tmp_path, "server")
    assert out[0] == "server.py"


def test_fuzzy_respects_limit(tmp_path):
    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("x")
    assert len(fuzzy_find_files(tmp_path, "", limit=5)) == 5
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_cli_completions.py -k fuzzy -v`
Expected: FAIL — `ImportError: cannot import name 'fuzzy_find_files'`.

- [ ] **Step 3: Implement**

First, update the import block at the top of `localllm/completions.py` to add
`os` and `Path` (keep them ordered — stdlib group, then first-party):

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from localllm.commands import COMMANDS
```

Then append the search logic to the end of the file:

```python
IGNORE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "mlx_models",
    ".worktrees",
}

_MAX_ENTRIES = 20_000  # ceiling so a pathological tree can't hang a keystroke


def _is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def _score(query: str, relpath: str) -> int:
    """Higher is better; negative means "no match" (excluded)."""
    if not query:
        return 0
    path = relpath.lower()
    base = os.path.basename(path)
    if query in base:
        return 1000 - base.index(query)
    if query in path:
        return 500 - min(path.index(query), 499)
    if _is_subsequence(query, path):
        return 100
    return -1


def fuzzy_find_files(root: str | Path, query: str, *, limit: int = 20) -> list[str]:
    """POSIX-relative paths under `root` matching `query`, best first.

    Walks once, pruning IGNORE_DIRS. Empty query returns the shortest paths
    first (stable). Capped at `_MAX_ENTRIES` files scanned.
    """
    root = Path(root)
    q = query.lower()
    scored: list[tuple[int, str]] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for name in filenames:
            count += 1
            if count > _MAX_ENTRIES:
                break
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            score = _score(q, rel)
            if score >= 0:
                scored.append((score, rel))
        if count > _MAX_ENTRIES:
            break
    # Best score first; ties broken by shorter path then alphabetical.
    scored.sort(key=lambda t: (-t[0], len(t[1]), t[1]))
    return [rel for _, rel in scored[:limit]]
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_cli_completions.py -v`
Expected: PASS (14 passed total in this file).

- [ ] **Step 5: Commit**

```bash
git add localllm/completions.py tests/test_cli_completions.py
git commit -m "feat(cli): recursive fuzzy file search with ignore pruning"
```

---

## Task 5: `mentions.py` — deterministic `@file` expansion

**Files:**

- Create: `localllm/mentions.py`
- Test: `tests/test_cli_mentions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_mentions.py`:

```python
from localllm.mentions import MAX_FILE_BYTES, expand_mentions, human_size


def test_expands_single_file(tmp_path):
    (tmp_path / "a.txt").write_text("ALPHA")
    exp = expand_mentions("read @a.txt", tmp_path)
    assert "read @a.txt" in exp.text  # original line preserved
    assert '<file path="a.txt">' in exp.text
    assert "ALPHA" in exp.text
    assert exp.attached == [("a.txt", 5)]
    assert exp.warnings == []


def test_no_mentions_unchanged(tmp_path):
    exp = expand_mentions("just text", tmp_path)
    assert exp.text == "just text"
    assert exp.attached == []
    assert exp.warnings == []


def test_missing_file_warns(tmp_path):
    exp = expand_mentions("see @nope.txt", tmp_path)
    assert exp.text == "see @nope.txt"
    assert exp.attached == []
    assert any("not found" in w for w in exp.warnings)


def test_outside_cwd_rejected(tmp_path):
    (tmp_path.parent / "secret.txt").write_text("S")
    exp = expand_mentions("grab @../secret.txt", tmp_path)
    assert exp.attached == []
    assert any("outside" in w for w in exp.warnings)


def test_binary_refused(tmp_path):
    (tmp_path / "b.bin").write_bytes(b"\x00\x01\x02")
    exp = expand_mentions("x @b.bin", tmp_path)
    assert exp.attached == []
    assert any("binary" in w for w in exp.warnings)


def test_truncates_large_file(tmp_path):
    (tmp_path / "big.txt").write_text("y" * (MAX_FILE_BYTES + 100))
    exp = expand_mentions("@big.txt", tmp_path)
    assert "[truncated 100 bytes]" in exp.text
    assert exp.attached == [("big.txt", MAX_FILE_BYTES)]
    assert any("truncated" in w for w in exp.warnings)


def test_email_is_not_a_mention(tmp_path):
    exp = expand_mentions("ping a@b.com please", tmp_path)
    assert exp.text == "ping a@b.com please"
    assert exp.attached == []


def test_dedupes_repeated_mention(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    exp = expand_mentions("@a.txt and @a.txt", tmp_path)
    assert exp.attached == [("a.txt", 1)]


def test_human_size():
    assert human_size(500) == "500 B"
    assert human_size(1536).endswith("KB")
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_cli_mentions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'localllm.mentions'`.

- [ ] **Step 3: Implement**

Create `localllm/mentions.py`:

```python
"""Pure @-mention expansion: turn `@path` into an inlined <file> block."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 100_000  # 100 KB per @-mention

# @ at start-of-string or after whitespace, then a run of non-space chars.
# The lookbehind keeps emails like a@b.com from matching.
_MENTION_RE = re.compile(r"(?:(?<=\s)|^)@(\S+)")
_TRAILING = ".,;:!?)]}"  # punctuation stripped before resolving a path


@dataclass
class Expansion:
    text: str  # prompt for the bridge: original line + appended <file> blocks
    attached: list[tuple[str, int]] = field(default_factory=list)  # (rel, bytes)
    warnings: list[str] = field(default_factory=list)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def expand_mentions(text: str, cwd: str | Path, *, max_bytes: int = MAX_FILE_BYTES) -> Expansion:
    cwd_resolved = Path(os.path.expanduser(str(cwd))).resolve()
    exp = Expansion(text=text)
    blocks: list[str] = []
    seen: set[str] = set()

    for match in _MENTION_RE.finditer(text):
        rel = match.group(1).rstrip(_TRAILING)
        if not rel or rel in seen:
            continue
        seen.add(rel)

        candidate = Path(os.path.expanduser(rel))
        target = (
            candidate.resolve()
            if candidate.is_absolute()
            else (cwd_resolved / candidate).resolve()
        )
        try:
            target.relative_to(cwd_resolved)
        except ValueError:
            exp.warnings.append(f"skipped @{rel} (outside the session directory)")
            continue
        if not target.is_file():
            exp.warnings.append(f"skipped @{rel} (not found)")
            continue
        try:
            data = target.read_bytes()
        except OSError as e:
            exp.warnings.append(f"skipped @{rel} ({e.__class__.__name__})")
            continue
        if b"\x00" in data[:8192]:
            exp.warnings.append(f"skipped @{rel} (binary file)")
            continue

        truncated = len(data) > max_bytes
        sent = data[:max_bytes]
        content = sent.decode("utf-8", errors="replace")
        if truncated:
            dropped = len(data) - max_bytes
            content += f"\n[truncated {dropped} bytes]"
            exp.warnings.append(
                f"truncated @{rel} to {human_size(max_bytes)} "
                f"({human_size(dropped)} dropped)"
            )
        blocks.append(f'<file path="{rel}">\n{content}\n</file>')
        exp.attached.append((rel, len(sent)))

    if blocks:
        exp.text = text + "\n\n" + "\n\n".join(blocks)
    return exp
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_cli_mentions.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add localllm/mentions.py tests/test_cli_mentions.py
git commit -m "feat(cli): @-mention expansion with sandbox, binary guard, size cap"
```

---

## Task 6: `CompletionMenu` widget + `InputBox` wiring + app menu wiring

This task makes the menu appear and accept candidates. It is covered by Pilot
tests (the menu needs an `App` context to mount).

**Files:**

- Create: `localllm/widgets/completion_menu.py`
- Modify: `localllm/widgets/input_box.py`
- Modify: `localllm/app.py`
- Test: `tests/test_tui_completion.py`

- [ ] **Step 1: Write the failing Pilot tests**

Create `tests/test_tui_completion.py`:

```python
import pytest

from localllm.app import LocalLLMApp
from localllm.widgets.completion_menu import CompletionMenu
from localllm.widgets.input_box import InputBox

pytestmark = pytest.mark.needs_tty


async def test_slash_opens_command_menu():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(InputBox).focus()
        await pilot.press("/")
        await pilot.pause()
        menu = app.query_one(CompletionMenu)
        assert menu.display is True
        assert menu.option_count > 0


async def test_command_menu_filters_and_accepts():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(InputBox).focus()
        await pilot.press("/")
        await pilot.press("m")  # "/m" -> only "/model"
        await pilot.pause()
        await pilot.press("enter")  # accept (must NOT submit)
        await pilot.pause()
        assert app.query_one(InputBox).value.startswith("/model")
        assert app.query_one(CompletionMenu).display is False


async def test_at_opens_file_menu(tmp_path):
    (tmp_path / "alpha.py").write_text("x")
    (tmp_path / "beta.txt").write_text("y")
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        inp = app.query_one(InputBox)
        inp.cwd = str(tmp_path)
        inp.focus()
        await pilot.press("@")
        await pilot.pause()
        menu = app.query_one(CompletionMenu)
        assert menu.display is True
        assert menu.option_count == 2
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_tui_completion.py -m "not needs_gpu" -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'localllm.widgets.completion_menu'`.

- [ ] **Step 3a: Create the menu widget**

Create `localllm/widgets/completion_menu.py`:

```python
"""Floating autocomplete menu for the input box (commands + @files)."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class CompletionMenu(OptionList):
    """Overlay list of candidates. Driven entirely by InputBox; never focused."""

    DEFAULT_CSS = """
    CompletionMenu {
        layer: overlay;
        dock: bottom;
        offset: 0 -4;
        width: 100%;
        height: auto;
        max-height: 10;
        background: $panel;
        border: tall $accent;
        display: none;
    }
    """

    class Picked(Message):
        """A candidate was chosen (mouse click)."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._values: list[str] = []

    def show(self, items: list[tuple[str, str]]) -> None:
        """items: (replacement_value, display_label)."""
        self._values = [value for value, _ in items]
        self.clear_options()
        self.add_options([Option(label) for _, label in items])
        if items:
            self.highlighted = 0
        self.display = True

    def hide(self) -> None:
        self._values = []
        self.display = False

    def current_value(self) -> str | None:
        i = self.highlighted
        if i is not None and 0 <= i < len(self._values):
            return self._values[i]
        return None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if 0 <= event.option_index < len(self._values):
            self.post_message(self.Picked(self._values[event.option_index]))
```

- [ ] **Step 3b: Rewrite the input box**

Replace the entire contents of `localllm/widgets/input_box.py` with:

```python
"""Single-line input with up/down history and @/ completion menu."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input

from localllm.completions import (
    apply_completion,
    fuzzy_find_files,
    parse_trigger,
    slash_candidates,
)
from localllm.widgets.completion_menu import CompletionMenu


class InputBox(Input):
    BINDINGS = [
        Binding("up", "history_prev", "Prev", show=False),
        Binding("down", "history_next", "Next", show=False),
    ]

    def __init__(self, cwd: str = ".", **kwargs) -> None:
        super().__init__(placeholder="› type a message, /help, or @file", **kwargs)
        self._history: list[str] = []
        self._cursor: int | None = None
        self.cwd = cwd
        self._trigger = None

    # --- history (unchanged behavior) -------------------------------------
    def push_history(self, line: str) -> None:
        if line and (not self._history or self._history[-1] != line):
            self._history.append(line)
        self._cursor = None

    def action_history_prev(self) -> None:
        if not self._history:
            return
        self._cursor = (
            len(self._history) - 1 if self._cursor is None else max(0, self._cursor - 1)
        )
        self.value = self._history[self._cursor]

    def action_history_next(self) -> None:
        if self._cursor is None:
            return
        self._cursor += 1
        if self._cursor >= len(self._history):
            self._cursor = None
            self.value = ""
        else:
            self.value = self._history[self._cursor]

    # --- completion menu ---------------------------------------------------
    def _menu(self) -> CompletionMenu | None:
        try:
            return self.app.query_one(CompletionMenu)
        except Exception:  # noqa: BLE001  (menu not mounted yet)
            return None

    def update_completions(self) -> None:
        """Recompute the menu from the current text + caret. Called on change."""
        menu = self._menu()
        if menu is None:
            return
        trig = parse_trigger(self.value, self.cursor_position)
        self._trigger = trig
        if trig is None:
            menu.hide()
            return
        if trig.kind == "command":
            items = [
                (name, f"{name}  {summary}")
                for name, summary in slash_candidates(trig.query)
            ]
        else:
            items = [("@" + rel, rel) for rel in fuzzy_find_files(self.cwd, trig.query)]
        if items:
            menu.show(items)
        else:
            menu.hide()

    def apply_value(self, value: str) -> None:
        """Splice the chosen completion into the text."""
        if self._trigger is None:
            return
        text, cursor = apply_completion(self.value, self._trigger, value)
        self.value = text
        self.cursor_position = cursor
        menu = self._menu()
        if menu is not None:
            menu.hide()

    async def on_key(self, event) -> None:
        # Only intercept navigation keys while the menu is open; otherwise let
        # Input's normal bindings (history, submit, focus) run untouched.
        menu = self._menu()
        if menu is None or not menu.display:
            return
        if event.key == "down":
            menu.action_cursor_down()
            event.prevent_default()
            event.stop()
        elif event.key == "up":
            menu.action_cursor_up()
            event.prevent_default()
            event.stop()
        elif event.key in ("enter", "tab"):
            value = menu.current_value()
            if value is not None:
                self.apply_value(value)
            event.prevent_default()
            event.stop()
        elif event.key == "escape":
            menu.hide()
            event.prevent_default()
            event.stop()
```

- [ ] **Step 3c: Wire the app (compose, layers, handlers, cwd)**

In `localllm/app.py`:

(1) Imports — change the textual.widgets import and add two local imports:

```python
from textual.widgets import Footer, Header, Input
```

and, alongside the other `from localllm.widgets...` lines:

```python
from localllm.mentions import expand_mentions, human_size
from localllm.widgets.completion_menu import CompletionMenu
```

(2) CSS — add a layers declaration to the `Screen` rule:

```python
    Screen {
        layout: vertical;
        layers: base overlay;
    }
```

(3) `compose` — add the menu between the transcript and the input:

```python
        with Vertical():
            yield Transcript(id="transcript")
            yield CompletionMenu(id="completion")
            yield InputBox(id="input")
```

(4) `on_mount` — hand the session cwd to the input box. After
`self.query_one(InputBox).focus()` add:

```python
        self.query_one(InputBox).cwd = self._cwd
```

(5) New handlers — add these two methods to `LocalLLMApp` (e.g. right after
`on_input_submitted`):

```python
    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one(InputBox).update_completions()

    def on_completion_menu_picked(self, event: CompletionMenu.Picked) -> None:
        self.query_one(InputBox).apply_value(event.value)
```

- [ ] **Step 4: Run the Pilot tests, verify pass**

Run: `.venv/bin/python -m pytest tests/test_tui_completion.py -m "not needs_gpu" -q`
Expected: PASS (3 passed). Also run the existing smoke suite to confirm no
regression: `.venv/bin/python -m pytest tests/test_tui_smoke.py -m "not needs_gpu" -q` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add localllm/widgets/completion_menu.py localllm/widgets/input_box.py localllm/app.py tests/test_tui_completion.py
git commit -m "feat(cli): @file + /command autocomplete menu in the TUI input"
```

---

## Task 7: Inject `@`-mentions on submit

Wire `expand_mentions` into the submit worker so picked files reach the model.

**Files:**

- Modify: `localllm/app.py`
- Test: `tests/test_tui_completion.py`

- [ ] **Step 1: Add the failing test**

Append this test function to `tests/test_tui_completion.py` (no new imports
needed — `pilot.pause(delay)` waits for the worker):

```python
async def test_submit_injects_mentioned_file(tmp_path, monkeypatch):
    (tmp_path / "note.txt").write_text("hello-from-file")
    captured = {}

    async def fake_stream(self, *, prompt, model_id, cwd, cli_session_id):
        captured["prompt"] = prompt
        return
        yield  # pragma: no cover  -- makes this an async generator

    monkeypatch.setattr("localllm.agent_client.AgentClient.run_and_stream", fake_stream)

    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")
    async with app.run_test() as pilot:
        await pilot.pause()
        app._cwd = str(tmp_path)
        inp = app.query_one(InputBox)
        app.post_message(InputBox.Submitted(inp, "read @note.txt"))
        await pilot.pause()
        await pilot.pause(0.3)
        assert "hello-from-file" in captured["prompt"]
        assert '<file path="note.txt">' in captured["prompt"]
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_tui_completion.py::test_submit_injects_mentioned_file -m "not needs_gpu" -q`
Expected: FAIL — `AssertionError`. The submit path currently sends the raw
`text`, so `captured["prompt"]` is `"read @note.txt"` with no `<file>` block; the
content assertion fails.

- [ ] **Step 3: Implement the expansion in `_process_submit`**

In `localllm/app.py`, inside `_process_submit`, replace this block:

```python
        transcript.write_user(text)
        status.state = "thinking"
        trace = self.query_one(TracePanel)
        trace.reset()
        trace.active = True

        try:
            async for ev in self._client.run_and_stream(
                prompt=text,
                model_id=self._model_id,
                cwd=self._cwd,
                cli_session_id=self._session_id,
            ):
```

with:

```python
        exp = expand_mentions(text, self._cwd)
        transcript.write_user(text)
        for rel, n in exp.attached:
            transcript.write_status(f"📎 attached: {rel} ({human_size(n)})")
        for warning in exp.warnings:
            transcript.write_error(warning)
        status.state = "thinking"
        trace = self.query_one(TracePanel)
        trace.reset()
        trace.active = True

        try:
            async for ev in self._client.run_and_stream(
                prompt=exp.text,
                model_id=self._model_id,
                cwd=self._cwd,
                cli_session_id=self._session_id,
            ):
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_tui_completion.py -m "not needs_gpu" -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add localllm/app.py tests/test_tui_completion.py
git commit -m "feat(cli): inject @-mentioned file contents into the prompt on submit"
```

---

## Task 8: Keep `/cwd` in sync + full pre-push gate

Make `/cwd` re-target the file picker, then verify the whole feature against CI.

**Files:**

- Modify: `localllm/app.py`

- [ ] **Step 1: Update `/cwd` handling**

In `localllm/app.py`, in `_handle_command`, the `set_cwd` branch:

```python
        elif result.kind == "set_cwd":
            self._cwd = result.value
            status.cwd = result.value
            transcript.write_status(f"cwd → {result.value}")
```

becomes:

```python
        elif result.kind == "set_cwd":
            self._cwd = result.value
            status.cwd = result.value
            self.query_one(InputBox).cwd = result.value
            transcript.write_status(f"cwd → {result.value}")
```

- [ ] **Step 2: Run the CLI test suites**

Run: `.venv/bin/python -m pytest tests/test_cli_completions.py tests/test_cli_mentions.py tests/test_cli_commands.py tests/test_tui_completion.py tests/test_tui_smoke.py -m "not needs_gpu" -q`
Expected: PASS (all green).

- [ ] **Step 3: Run the full pre-push gate (the Definition of Done)**

Run: `bash .git/hooks/pre-push`
Expected: exit 0 — ruff check, ruff format --check, prettier --check, and the
full pytest run (`-m "not needs_gpu"`) all pass.

If anything fails, fix it and re-run before continuing. Do not skip with
`--no-verify`.

- [ ] **Step 4: Commit**

```bash
git add localllm/app.py
git commit -m "feat(cli): /cwd re-targets the @file picker to the new root"
```

- [ ] **Step 5 (optional): Log the session**

If wrapping up, add a short `PROGRESS.md` entry describing the `@`/`/`
autocomplete feature and commit it, per project habit.

---

## Manual smoke (after the plan)

With the bridge running, from any project directory:

```bash
localllm
```

- Type `/` → command menu appears; arrow + Enter inserts a command.
- Type `summarize @` → file menu appears; fuzzy-type a fragment, Enter completes
  the path; submit and confirm a `📎 attached: …` line shows and the model
  actually uses the file.
- Try `@app.log` (or any >100 KB file) → confirm the truncation warning.
- Try `@../something` → confirm the "outside the session directory" warning.

```

```
