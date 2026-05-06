import logging
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Security: The audit log is stored outside the sandbox so the agent cannot delete it.
AUDIT_LOG_PATH = "/Users/ojdavis/Claude Code/Gemma4/audit.log"

def log_audit(action: str):
    """Consistently log risky actions to the audit log."""
    try:
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {action}\n")
    except Exception as e:
        # If we can't write to the audit log, we should at least print to stderr
        print(f"CRITICAL: Failed to write to audit log: {e}", file=sys.stderr)

logger = logging.getLogger(__name__)

@dataclass
class Tool:
    name: str
    risk: str  # "safe" or "risky"
    description: str
    fn: Any  # callable

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def validate_path(path_str: str, must_exist: bool = True) -> Path:
    # Resolve the project root (base) and the requested path (target)
    base = Path(os.getcwd()).resolve()
    target = Path(os.path.expanduser(path_str)).resolve()

    # Security Check: Ensure target is within base
    try:
        target.relative_to(base)
    except ValueError:
        raise PermissionError(f"Access denied: {path_str} is outside the sandbox.")

    if must_exist and not target.exists():
        raise FileNotFoundError(f"File not found: {path_str}")

    return target


async def _read_file(path: str) -> str:
    try:
        p = validate_path(path)
        return p.read_text()
    except Exception as e:
        logger.error("read_file failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _list_dir(path: str) -> str:
    try:
        p = validate_path(path)
        entries = [entry.name for entry in p.iterdir()]
        return "\n".join(entries)
    except Exception as e:
        logger.error("list_dir failed: %s", e, extra={"path": path})
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
    log_audit(f"WRITE_FILE: {path}")
    try:
        p = validate_path(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"OK: wrote {len(content)} bytes"
    except Exception as e:
        logger.error("write_file failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _append_file(path: str, content: str) -> str:
    log_audit(f"APPEND_FILE: {path}")
    try:
        p = validate_path(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(content)
        return f"OK: appended {len(content)} bytes"
    except Exception as e:
        logger.error("append_file failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _shell(command: str) -> str:
    log_audit(f"SHELL: {command}")
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
        logger.error("shell timed out", extra={"command": command})
        return "ERROR: timed out"


async def _create_cron(name: str, schedule: str, command: str) -> str:
    log_audit(f"CREATE_CRON: {name} ({schedule}) {command}")
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
        logger.error("create_cron failed: %s", e, extra={"name": name})
        return f"ERROR: {e}"


async def _delete_cron(name: str) -> str:
    log_audit(f"DELETE_CRON: {name}")
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
        logger.error("delete_cron failed: %s", e, extra={"name": name})
        return f"ERROR: {e}"


async def _get_current_datetime() -> str:
    now = datetime.now().astimezone()
    return now.strftime("%A, %Y-%m-%d %H:%M:%S %Z")


async def _google_search(query: str) -> str:
    try:
        from ddgs import DDGS
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, lambda: DDGS().text(query, max_results=5))
        lines = [f"{r['title']}\n{r['href']}\n{r.get('body', '')}" for r in results]
        return "\n\n".join(lines) if lines else "No results found."
    except Exception as e:
        logger.error("google_search failed: %s", e, extra={"query": query})
        return f"ERROR: {e}"


def validate_url(url: str):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https allowed, got: {parsed.scheme}")

    host = parsed.hostname
    if not host:
        raise ValueError("Invalid URL: No hostname found")

    # Block local/private IPs and names
    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"]
    # Add common local ranges if possible, but at least block these 4
    if host.lower() in blocked:
        raise PermissionError(f"SSRF detected: Access to {host} is blocked")


async def _web_fetch(url: str) -> str:
    try:
        validate_url(url)
        import requests
        from bs4 import BeautifulSoup
        loop = asyncio.get_running_loop()

        def _sync_fetch():
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
            return "\n".join(lines)[:5000]

        return await loop.run_in_executor(None, _sync_fetch)
    except Exception as e:
        logger.error("web_fetch failed: %s", e, extra={"url": url})
        return f"ERROR: {e}"


async def _grep_search(pattern: str, path: str = ".") -> str:
    try:
        base_path = validate_path(path)
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
        logger.error("grep_search failed: %s", e, extra={"pattern": pattern, "path": path})
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
        logger.error("git_status failed: %s", e)
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
        logger.error("git_log failed: %s", e)
        return f"ERROR: {e}"


async def _clipboard_copy(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        return "OK: copied to clipboard"
    except Exception as e:
        logger.error("clipboard_copy failed: %s", e)
        return f"ERROR: {e}"


async def _clipboard_paste() -> str:
    log_audit("CLIPBOARD_PASTE")
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception as e:
        logger.error("clipboard_paste failed: %s", e)
        return f"ERROR: {e}"


async def _python_interpreter(code: str) -> str:
    """Executes python code and returns captured stdout or traceback."""
    log_audit(f"PYTHON: {code}")
    old_stdout = sys.stdout
    new_stdout = io.StringIO()
    sys.stdout = new_stdout
    try:
        # Execute in a clean global/local dict
        exec(code, {})
    except Exception:
        sys.stdout = old_stdout
        tb = traceback.format_exc()
        logger.error("python_interpreter raised exception", extra={"code_preview": code[:200]})
        return tb
    finally:
        sys.stdout = old_stdout

    output = new_stdout.getvalue()
    return output if output else "OK: executed"

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Tool] = {}

def register_tool(name: str, risk: str, description: str, fn: Any) -> None:
    """Register a tool in the global TOOL_REGISTRY."""
    TOOL_REGISTRY[name] = Tool(name, risk, description, fn)

# Register default tools
register_tool("read_file", "safe", "Read file contents", _read_file)
register_tool("list_dir", "safe", "List directory", _list_dir)
register_tool("grep_search", "safe", "Grep search for a pattern in a path", _grep_search)
register_tool("list_crons", "safe", "List crontab", _list_crons)
register_tool("write_file", "risky", "Write file", _write_file)
register_tool("append_file", "risky", "Append to file", _append_file)
register_tool("shell", "risky", "Run shell command", _shell)
register_tool("python_interpreter", "risky", "Execute Python code", _python_interpreter)
register_tool("create_cron", "risky", "Create cron job", _create_cron)
register_tool("delete_cron", "risky", "Delete cron job", _delete_cron)
register_tool("git_status", "safe", "Get git status --short", _git_status)
register_tool("git_log", "safe", "Get git log --oneline", _git_log)
register_tool("clipboard_copy", "safe", "Copy text to system clipboard", _clipboard_copy)
register_tool("clipboard_paste", "risky", "Paste text from system clipboard", _clipboard_paste)
register_tool("google_search", "safe", "Search Google for a query", _google_search)
register_tool("web_fetch", "safe", "Fetch and clean text from a URL", _web_fetch)
register_tool("get_current_datetime", "safe", "Get the current local date, time, and timezone", _get_current_datetime)

# Note: create_scheduled_task and list_scheduled_tasks are omitted from here 
# because they depend on the scheduler in agent.py. 
# We'll add them back to the registry in agent.py or keep them separate.

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are an autonomous agent with access to the internet and local tools.

TOOLS AVAILABLE:
  google_search(query)          — search the web for real-time information
  web_fetch(url)                — fetch and read a webpage
  get_current_datetime()        — get the current date and time
  read_file(path)               — read a local file
  list_dir(path)                — list directory contents
  grep_search(pattern, path)    — search files for a pattern
  write_file(path, content)     — write a file
  append_file(path, content)    — append to a file
  shell(command)                — run a shell command
  python_interpreter(code)      — execute Python code
  git_status()                  — git status
  git_log(limit)                — git log
  clipboard_copy(text)          — copy to clipboard
  clipboard_paste()             — paste from clipboard
  list_crons()                  — list cron jobs
  create_cron(name, schedule, command)   — create a cron job
  delete_cron(name)             — delete a cron job
  list_scheduled_tasks()        — list in-app scheduled tasks
  create_scheduled_task(name, schedule, prompt) — create a scheduled task

RULES:
- For any real-time query (scores, news, weather, prices, current events): ALWAYS call google_search. Never say you lack internet access — you have it.
- To call a tool, output EXACTLY one line: TOOL: tool_name("arg1", "arg2")
- To finish, output: DONE: <your answer or summary>
- Think step by step. Only call one tool per response."""

def strip_thinking_blocks(text: str) -> str:
    """Strip all known thinking-block formats used by Gemma 4 and related models."""
    # Gemma 4 channel format — complete blocks (closing tag present)
    text = re.sub(r'<\|channel\|?>thought\n?.*?<\|?channel\|>', '', text, flags=re.DOTALL)
    # Gemma 4 channel format — truncated/unclosed blocks (output hit token limit mid-thought)
    text = re.sub(r'<\|channel\|?>thought\n?.*$', '', text, flags=re.DOTALL)
    # Generic XML-style thinking blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def parse_model_output(text: str) -> tuple[str, str, list] | None:
    """Return (type, tool_or_message, args) or None if neither TOOL nor DONE found."""
    # Strip all thinking block formats before parsing so that tool/done references
    # inside thinking blocks don't trigger real tool calls or false done signals.
    # The original text is preserved in the message history; only parsing uses clean_text.
    clean_text = strip_thinking_blocks(text)

    # Native Gemma format: <|tool_call>call:tool_name("arg")<tool_call|>
    native_match = re.search(r'<\|tool_call\>call:(\w+)\((.*?)\)<tool_call\|>', clean_text, re.DOTALL)
    # Text-based format: TOOL: tool_name("arg")
    tool_match = re.search(r'TOOL:\s*(\w+)\((.*)\)\s*$', clean_text, re.MULTILINE)
    done_match = re.search(r'DONE:\s*(.+)', clean_text, re.MULTILINE)

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
