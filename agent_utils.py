import asyncio
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyperclip
import requests
from bs4 import BeautifulSoup

@dataclass
class Tool:
    name: str
    risk: str  # "safe" or "risky"
    description: str
    fn: Any  # callable

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _read_file(path: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        return p.read_text()
    except Exception as e:
        return f"ERROR: {e}"


async def _list_dir(path: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        entries = [entry.name for entry in p.iterdir()]
        return "\n".join(entries)
    except Exception as e:
        return f"ERROR: {e}"


async def _list_crons() -> str:
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return "No crontab for this user."


async def _write_file(path: str, content: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"OK: wrote {len(content)} bytes"
    except Exception as e:
        return f"ERROR: {e}"


async def _append_file(path: str, content: str) -> str:
    try:
        p = Path(os.path.expanduser(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(content)
        return f"OK: appended {len(content)} bytes"
    except Exception as e:
        return f"ERROR: {e}"


async def _shell(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "ERROR: timed out"


async def _create_cron(name: str, schedule: str, command: str) -> str:
    try:
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError:
            existing = ""
        new_entry = f"# gemma:{name}\n{schedule} {command}\n"
        new_crontab = existing + new_entry
        subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            text=True,
            check=True,
        )
        return "OK: cron created"
    except Exception as e:
        return f"ERROR: {e}"


async def _delete_cron(name: str) -> str:
    try:
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError:
            existing = ""
        lines = existing.splitlines(keepends=True)
        tag = f"# gemma:{name}"
        new_lines = []
        i = 0
        found = False
        while i < len(lines):
            if lines[i].strip() == tag:
                found = True
                i += 1  # skip the tag line
                if i < len(lines):
                    i += 1  # skip the following cron line
            else:
                new_lines.append(lines[i])
                i += 1
        if not found:
            return "ERROR: not found"
        subprocess.run(
            ["crontab", "-"],
            input="".join(new_lines),
            text=True,
            check=True,
        )
        return "OK: cron deleted"
    except Exception as e:
        return f"ERROR: {e}"


async def _google_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = [r["href"] for r in ddgs.text(query, max_results=5)]
            return "\n".join(results)
    except Exception as e:
        return f"ERROR: {e}"


async def _web_fetch(url: str) -> str:
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script and style elements
        for script_or_style in soup(["script", "style"]):
            script_or_style.decompose()

        # Get text and clean up whitespace
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned_text = "\n".join(lines)

        return cleaned_text[:5000]
    except Exception as e:
        return f"ERROR: {e}"


async def _grep_search(pattern: str, path: str = ".") -> str:
    try:
        base_path = Path(os.path.expanduser(path))
        regex = re.compile(pattern)
        results = []

        def search_file(p: Path):
            try:
                with open(p, "r", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{p}:{i}: {line.strip()}")
                            if len(results) >= 50:
                                return True
            except Exception:
                pass
            return False

        if base_path.is_file():
            search_file(base_path)
        elif base_path.is_dir():
            for root, dirs, files in os.walk(base_path):
                if ".git" in dirs:
                    dirs.remove(".git")
                # Also skip other common large dirs if they are not explicitly requested
                for d in [".venv", "node_modules", "__pycache__", ".pytest_cache"]:
                    if d in dirs:
                        dirs.remove(d)
                for file in files:
                    if search_file(Path(root) / file):
                        return "\n".join(results)
        else:
            return f"ERROR: Path {path} not found"

        return "\n".join(results) if results else "No matches found."
    except Exception as e:
        return f"ERROR: {e}"


async def _git_status() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() if result.stdout.strip() else "Clean"
    except Exception as e:
        return f"ERROR: {e}"


async def _git_log(limit: int = 5) -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-n", str(limit), "--oneline"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


async def _clipboard_copy(text: str) -> str:
    try:
        pyperclip.copy(text)
        return "OK: copied to clipboard"
    except Exception as e:
        return f"ERROR: {e}"


async def _clipboard_paste() -> str:
    try:
        return pyperclip.paste()
    except Exception as e:
        return f"ERROR: {e}"


async def _python_interpreter(code: str) -> str:
    """Executes python code and returns captured stdout or traceback."""
    old_stdout = sys.stdout
    new_stdout = io.StringIO()
    sys.stdout = new_stdout
    try:
        # Execute in a clean global/local dict
        exec(code, {})
    except Exception:
        sys.stdout = old_stdout
        return traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    output = new_stdout.getvalue()
    return output if output else "OK: executed"

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Tool] = {
    "read_file": Tool("read_file", "safe", "Read file contents", _read_file),
    "list_dir": Tool("list_dir", "safe", "List directory", _list_dir),
    "grep_search": Tool("grep_search", "safe", "Grep search for a pattern in a path", _grep_search),
    "list_crons": Tool("list_crons", "safe", "List crontab", _list_crons),
    "write_file": Tool("write_file", "risky", "Write file", _write_file),
    "append_file": Tool("append_file", "risky", "Append to file", _append_file),
    "shell": Tool("shell", "risky", "Run shell command", _shell),
    "python_interpreter": Tool("python_interpreter", "risky", "Execute Python code", _python_interpreter),
    "create_cron": Tool("create_cron", "risky", "Create cron job", _create_cron),
    "delete_cron": Tool("delete_cron", "risky", "Delete cron job", _delete_cron),
    "git_status": Tool("git_status", "safe", "Get git status --short", _git_status),
    "git_log": Tool("git_log", "safe", "Get git log --oneline", _git_log),
    "clipboard_copy": Tool("clipboard_copy", "safe", "Copy text to system clipboard", _clipboard_copy),
    "clipboard_paste": Tool("clipboard_paste", "risky", "Paste text from system clipboard", _clipboard_paste),
    "google_search": Tool("google_search", "safe", "Search Google for a query", _google_search),
    "web_fetch": Tool("web_fetch", "safe", "Fetch and clean text from a URL", _web_fetch),
}

# Note: create_scheduled_task and list_scheduled_tasks are omitted from here 
# because they depend on the scheduler in agent.py. 
# We'll add them back to the registry in agent.py or keep them separate.

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are an autonomous agent. You have access to these tools:
  read_file(path), list_dir(path), grep_search(pattern, path), write_file(path, content),
  append_file(path, content), shell(command), python_interpreter(code), list_crons(),
  create_cron(name, schedule, command), delete_cron(name),
  list_scheduled_tasks(), create_scheduled_task(name, schedule, prompt),
  git_status(), git_log(limit), clipboard_copy(text), clipboard_paste(),
  google_search(query), web_fetch(url)

To call a tool, output EXACTLY one line:
  TOOL: tool_name("arg1", "arg2")

To finish, output:
  DONE: <concise summary of what was accomplished>

Think step by step. Only call one tool per response."""

def parse_model_output(text: str) -> tuple[str, str, list] | None:
    """Return (type, tool_or_message, args) or None if neither TOOL nor DONE found."""
    # Native Gemma format: <|tool_call>call:tool_name("arg")<tool_call|>
    native_match = re.search(r'<\|tool_call\>call:(\w+)\((.*?)\)<tool_call\|>', text, re.DOTALL)
    # Text-based format: TOOL: tool_name("arg")
    tool_match = re.search(r'TOOL:\s*(\w+)\((.*)\)\s*$', text, re.MULTILINE)
    done_match = re.search(r'DONE:\s*(.+)', text, re.MULTILINE)

    active_match = native_match or tool_match
    if active_match:
        tool_name = active_match.group(1)
        raw_args = active_match.group(2).strip()
        try:
            args = json.loads(f"[{raw_args}]") if raw_args else []
        except json.JSONDecodeError:
            # Heuristic: try splitting on comma+space for multi-arg tools
            parts = [p.strip().strip('"\'') for p in raw_args.split(', ')]
            args = parts if len(parts) > 1 else [raw_args]
        return ("tool", tool_name, args)
    if done_match:
        return ("done", done_match.group(1).strip(), [])
    return None
