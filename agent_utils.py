import ast
import asyncio
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Security: The audit log is stored outside the sandbox so the agent cannot delete it.
AUDIT_LOG_PATH = os.environ.get(
    "AUDIT_LOG_PATH", str(Path(__file__).parent / "audit.log")
)


def log_audit(action: str):
    """Consistently log risky actions to the audit log."""
    try:
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {action}\n")
    except Exception as e:
        # If we can't write to the audit log, we should at least print to stderr
        print(f"CRITICAL: Failed to write to audit log: {e}", file=sys.stderr)


logger = logging.getLogger(__name__)


class TelemetryManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TelemetryManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.reset()
        self._initialized = True

    def reset(self):
        """Reset all stats. Useful for testing."""
        with self._lock:
            self.total_tasks = 0
            self.success_count = 0
            self.error_count = 0
            self.top_tools = {}
            self.recent = deque(maxlen=5)
            self.task_start_times = {}

    def record_start(self, task_id: str):
        with self._lock:
            self.total_tasks += 1
            self.task_start_times[task_id] = time.monotonic()
            # Cleanup stale tasks to prevent memory leakage (max 100 tracked start times)
            if len(self.task_start_times) > 100:
                oldest_task_id = next(iter(self.task_start_times))
                self.task_start_times.pop(oldest_task_id)

    def record_tool_use(self, tool_name: str):
        with self._lock:
            self.top_tools[tool_name] = self.top_tools.get(tool_name, 0) + 1

    def record_complete(self, task_id: str, status: str):
        """status should be 'success' or 'error'"""
        with self._lock:
            duration_ms = 0
            if task_id in self.task_start_times:
                duration_ms = int(
                    (time.monotonic() - self.task_start_times.pop(task_id)) * 1000
                )

            if status == "success":
                self.success_count += 1
            elif status == "error":
                self.error_count += 1

            self.recent.appendleft(
                {
                    "id": task_id,
                    "status": status,
                    "duration_ms": duration_ms,
                    "timestamp": datetime.now().isoformat(),
                }
            )

    def get_stats(self) -> dict:
        with self._lock:
            completed_tasks = self.success_count + self.error_count
            return {
                "total_tasks": self.total_tasks,
                "success_count": self.success_count,
                "error_count": self.error_count,
                "top_tools": self.top_tools.copy(),
                "recent": list(self.recent),
                "success_rate": self.success_count / completed_tasks
                if completed_tasks > 0
                else 0,
            }


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


async def _google_search(query: str) -> dict:
    from urllib.parse import urlparse

    from citations import trim_snippet

    try:
        from ddgs import DDGS

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None, lambda: DDGS().text(query, max_results=5)
        )
        if not results:
            return {"sources": [], "model_text": "No results found."}

        sources = []
        for r in results:
            url = r.get("href") or ""
            domain = urlparse(url).hostname or None
            sources.append(
                {
                    "kind": "web",
                    "title": r.get("title") or "Untitled",
                    "url": url or None,
                    "domain": domain,
                    "snippet": trim_snippet(r.get("body")),
                    "meta": {},
                }
            )
        return {"sources": sources, "model_text": ""}
    except Exception as e:
        logger.error("google_search failed: %s", e, extra={"query": query})
        return {"sources": [], "model_text": f"ERROR: {e}"}


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


async def _web_fetch(url: str) -> dict:
    from urllib.parse import urlparse

    from citations import trim_snippet

    try:
        validate_url(url)
        import requests
        from bs4 import BeautifulSoup

        loop = asyncio.get_running_loop()

        def _sync_fetch():
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title_tag = soup.find("title")
            title = (title_tag.get_text().strip() if title_tag else "") or url
            for tag in soup(["script", "style"]):
                tag.decompose()
            lines = [
                line.strip()
                for line in soup.get_text(separator="\n").splitlines()
                if line.strip()
            ]
            body = "\n".join(lines)[:5000]
            return title, body

        title, body = await loop.run_in_executor(None, _sync_fetch)
        domain = urlparse(url).hostname or None
        source = {
            "kind": "web",
            "title": title,
            "url": url,
            "domain": domain,
            "snippet": trim_snippet(body),
            "meta": {},
        }
        return {"sources": [source], "model_text": body}
    except Exception as e:
        logger.error("web_fetch failed: %s", e, extra={"url": url})
        return {"sources": [], "model_text": f"ERROR: {e}"}


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
        logger.error(
            "grep_search failed: %s", e, extra={"pattern": pattern, "path": path}
        )
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
        logger.error(
            "python_interpreter raised exception", extra={"code_preview": code[:200]}
        )
        return tb
    finally:
        sys.stdout = old_stdout

    output = new_stdout.getvalue()
    return output if output else "OK: executed"


async def _git_diff(path: str = ".") -> str:
    try:
        cmd = ["git", "diff", "HEAD"]
        if path != ".":
            cmd.append(path)
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip() if result.stdout.strip() else "No changes vs HEAD."
    except Exception as e:
        logger.error("git_diff failed: %s", e)
        return f"ERROR: {e}"


async def _find_file(pattern: str, path: str = ".") -> str:
    try:
        base_path = validate_path(path)
        skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
        matches = []
        for root, dirs, _ in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for p in Path(root).glob(pattern):
                if p.is_file():
                    matches.append(str(p))
                    if len(matches) >= 100:
                        return "\n".join(matches) + "\n(truncated at 100)"
        return "\n".join(matches) if matches else "No files found."
    except Exception as e:
        logger.error(
            "find_file failed: %s", e, extra={"pattern": pattern, "path": path}
        )
        return f"ERROR: {e}"


async def _edit_file(path: str, old_str: str, new_str: str) -> str:
    log_audit(f"EDIT_FILE: {path}")
    try:
        p = validate_path(path)
        content = p.read_text()
        if old_str not in content:
            return "ERROR: old_str not found in file"
        updated = content.replace(old_str, new_str, 1)
        p.write_text(updated)
        return "OK: replaced 1 occurrence"
    except Exception as e:
        logger.error("edit_file failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _read_pdf(path: str) -> str:
    try:
        p = validate_path(path)
        from pdf_pipeline import extract_text_from_pdf

        loop = asyncio.get_running_loop()
        file_bytes = p.read_bytes()
        pages = await loop.run_in_executor(None, extract_text_from_pdf, file_bytes)
        if not pages:
            return "No text extracted from PDF."
        parts = [f"[Page {num}]\n{text}" for num, text in pages]
        result = "\n\n".join(parts)
        return result[:10000] if len(result) > 10000 else result
    except Exception as e:
        logger.error("read_pdf failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _write_pdf(path: str, content: str) -> str:
    log_audit(f"WRITE_PDF: {path}")
    try:
        p = validate_path(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        from fpdf import FPDF

        loop = asyncio.get_running_loop()

        def _sync_write():
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            for line in content.splitlines():
                pdf.multi_cell(w=pdf.epw, h=10, text=line)
            pdf.output(str(p))
            return f"OK: wrote PDF to {path}"

        return await loop.run_in_executor(None, _sync_write)
    except Exception as e:
        logger.error("write_pdf failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _read_word(path: str) -> str:
    try:
        p = validate_path(path)
        from office_pipeline import extract_text_from_word, format_office_read_output

        loop = asyncio.get_running_loop()
        file_bytes = p.read_bytes()
        sections, metadata = await loop.run_in_executor(
            None, extract_text_from_word, file_bytes
        )
        return format_office_read_output(sections, metadata, "word")
    except Exception as e:
        logger.error("read_word failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _read_excel(path: str) -> str:
    try:
        p = validate_path(path)
        from office_pipeline import extract_text_from_excel, format_office_read_output

        loop = asyncio.get_running_loop()
        file_bytes = p.read_bytes()
        sheets, metadata = await loop.run_in_executor(
            None, extract_text_from_excel, file_bytes
        )
        return format_office_read_output(sheets, metadata, "excel")
    except Exception as e:
        logger.error("read_excel failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _write_word(path: str, spec: str) -> str:
    log_audit(f"WRITE_WORD: {path}")
    try:
        p = validate_path(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        spec_dict = _json.loads(spec) if isinstance(spec, str) else spec
        loop = asyncio.get_running_loop()
        from office_pipeline import write_word_document

        def _sync():
            write_word_document(p, spec_dict)
            return f"OK: wrote Word document to {path}"

        return await loop.run_in_executor(None, _sync)
    except Exception as e:
        logger.error("write_word failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _write_excel(path: str, spec: str) -> str:
    log_audit(f"WRITE_EXCEL: {path}")
    try:
        p = validate_path(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        import json as _json

        spec_dict = _json.loads(spec) if isinstance(spec, str) else spec
        loop = asyncio.get_running_loop()
        from office_pipeline import write_excel_document

        def _sync():
            write_excel_document(p, spec_dict)
            return f"OK: wrote Excel file to {path}"

        return await loop.run_in_executor(None, _sync)
    except Exception as e:
        logger.error("write_excel failed: %s", e, extra={"path": path})
        return f"ERROR: {e}"


async def _http_request(
    method: str, url: str, headers: str = "{}", body: str = ""
) -> str:
    log_audit(f"HTTP_REQUEST: {method.upper()} {url}")
    try:
        validate_url(url)
        import json as _json

        import requests

        loop = asyncio.get_running_loop()
        parsed_headers = _json.loads(headers) if headers.strip() else {}

        def _sync_request():
            resp = requests.request(
                method.upper(),
                url,
                headers=parsed_headers,
                data=body.encode() if body else None,
                timeout=15,
            )
            text = resp.text[:5000]
            return f"Status: {resp.status_code}\n{text}"

        return await loop.run_in_executor(None, _sync_request)
    except Exception as e:
        logger.error("http_request failed: %s", e, extra={"method": method, "url": url})
        return f"ERROR: {e}"


async def _notify(title: str, message: str) -> str:
    try:
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        return "OK: notification sent"
    except Exception as e:
        logger.error("notify failed: %s", e)
        return f"ERROR: {e}"


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


async def _move_file(src: str, dst: str) -> str:
    log_audit(f"MOVE_FILE: {src} -> {dst}")
    try:
        s = validate_path(src)
        d = validate_path(dst, must_exist=False)
        import shutil as _shutil

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _shutil.move, str(s), str(d))
        return f"OK: moved {s} -> {d}"
    except Exception as e:
        logger.error("move_file failed: %s", e)
        return f"ERROR: {e}"


# Screenshot tool gets a scoped sandbox exception: in addition to the project
# root it accepts standard user folders, since screenshots inherently belong
# outside the project. Default destination is ~/Downloads with macOS-native
# naming.
# User folders accepted by tools that operate on user-supplied media (images,
# audio) which typically live outside the project — keeps the strict project
# sandbox for everything else.
_USER_FILE_ROOTS = ("Downloads", "Desktop", "Pictures")
_SCREENSHOT_EXTRA_ROOTS = _USER_FILE_ROOTS  # screenshot also writes into these
_SCREENSHOT_IMG_EXTS = {".png", ".jpg", ".jpeg"}
_SCREENSHOT_PLACEHOLDERS = {"", "path", "default", "none", "null"}


# Bareword names the model parrots from system-prompt templates instead of
# substituting a real value, e.g. describe_image(path, prompt) → path="path".
# Media-reading tools reject these with a helpful hint so the failure mode is
# self-explanatory rather than an opaque "File not found: path".
_MEDIA_PATH_PLACEHOLDERS = {
    "path",
    "image",
    "file",
    "audio",
    "video",
    "media",
    "default",
    "none",
    "null",
}


def _is_placeholder_path(value) -> bool:
    """True if ``value`` looks like a parroted prompt placeholder
    (``"path"``, ``"<audio>"``, etc.) rather than a real file path."""
    if not isinstance(value, str):
        return False
    return value.strip().strip("<>").lower() in _MEDIA_PATH_PLACEHOLDERS


def _validate_user_file_path(path: str, must_exist: bool = True) -> Path:
    """Like ``validate_path`` but additionally accepts paths under the standard
    user folders (``~/Downloads``, ``~/Desktop``, ``~/Pictures``). Used by tools
    that read media files the user keeps outside the project.
    """
    target = Path(os.path.expanduser(path)).resolve()
    allowed = [Path(os.getcwd()).resolve()] + [
        (Path.home() / sub).resolve() for sub in _USER_FILE_ROOTS
    ]
    for root in allowed:
        try:
            target.relative_to(root)
            break
        except ValueError:
            continue
    else:
        raise PermissionError(
            f"Access denied: {path} is outside the allowed folders "
            "(project dir, ~/Downloads, ~/Desktop, ~/Pictures)."
        )
    if must_exist and not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return target


def _resolve_screenshot_path(path: str) -> Path:
    """Pick the actual file path for a screenshot call.

    Rules, in order:
      1. Empty / placeholder ("path", "default", …) → ~/Downloads/Screenshot
         YYYY-MM-DD at HH.MM.SS.png (macOS-native pattern).
      2. Missing/non-image extension → append .png.
      3. Bare basename → ~/Downloads/<name>.
      4. Otherwise the path must resolve under the project sandbox OR one of
         ~/Downloads, ~/Desktop, ~/Pictures.
    """
    if not path or path.strip().lower() in _SCREENSHOT_PLACEHOLDERS:
        name = datetime.now().strftime("Screenshot %Y-%m-%d at %H.%M.%S.png")
        return Path.home() / "Downloads" / name

    p = Path(os.path.expanduser(path.strip()))
    if p.suffix.lower() not in _SCREENSHOT_IMG_EXTS:
        p = p.with_suffix(".png")
    if str(p.parent) == ".":
        return Path.home() / "Downloads" / p.name

    target = p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
    allowed = [Path(os.getcwd()).resolve()] + [
        (Path.home() / sub).resolve() for sub in _SCREENSHOT_EXTRA_ROOTS
    ]
    for root in allowed:
        try:
            target.relative_to(root)
            return target
        except ValueError:
            continue
    raise PermissionError(
        f"Access denied: {path} is outside the screenshot allowlist "
        "(project dir, ~/Downloads, ~/Desktop, ~/Pictures)."
    )


async def _screenshot(path: str = "") -> str:
    log_audit(f"SCREENSHOT: {path}")
    try:
        target = _resolve_screenshot_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()

        def _run():
            try:
                subprocess.run(
                    ["screencapture", "-x", str(target)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or "").strip()
                blob = (stderr + " " + str(e)).lower()
                if "not authorized" in blob or "permission" in blob:
                    raise RuntimeError(
                        "screencapture is not authorized for Screen Recording. "
                        "Grant Screen Recording to the bridge's Python in System "
                        "Settings → Privacy & Security → Screen Recording, then "
                        "restart the bridge."
                    ) from e
                raise RuntimeError(stderr or str(e)) from e
            # Strip the TCC access-list xattr the launchd-managed bridge stamps
            # onto files it creates, so the screenshot opens like a normal user
            # file (matches native Cmd-Shift-3 behaviour). Best-effort.
            try:
                subprocess.run(
                    ["xattr", "-d", "com.apple.macl", str(target)],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass

        await loop.run_in_executor(None, _run)
        return f"OK: saved to {target}"
    except Exception as e:
        logger.error("screenshot failed: %s", e)
        return f"ERROR: {e}"


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


async def _system_info() -> str:
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return (
            f"CPU: {cpu}%\n"
            f"RAM: {mem.used / 1e9:.1f} GB used / {mem.total / 1e9:.1f} GB total ({mem.percent}%)\n"
            f"Disk: {disk.used / 1e9:.1f} GB used / {disk.total / 1e9:.1f} GB total ({disk.percent}%)"
        )
    except Exception as e:
        logger.error("system_info failed: %s", e)
        return f"ERROR: {e}"


async def _sqlite_query(db_path: str, sql: str) -> str:
    log_audit(f"SQLITE_QUERY: {db_path} — {sql[:200]}")
    try:
        p = validate_path(db_path)
        # Enforce read-only: only SELECT statements permitted
        if not sql.strip().upper().startswith("SELECT"):
            return "ERROR: only SELECT queries are allowed"
        import sqlite3

        loop = asyncio.get_running_loop()

        def _sync_query():
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                cur = conn.execute(sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchmany(200)
                lines = ["\t".join(cols)] + [
                    "\t".join(str(v) for v in row) for row in rows
                ]
                suffix = "\n(truncated at 200 rows)" if len(rows) == 200 else ""
                return "\n".join(lines) + suffix
            finally:
                conn.close()

        return await loop.run_in_executor(None, _sync_query)
    except Exception as e:
        logger.error("sqlite_query failed: %s", e, extra={"db_path": db_path})
        return f"ERROR: {e}"


async def _diff_files(path_a: str, path_b: str) -> str:
    try:
        a = validate_path(path_a)
        b = validate_path(path_b)
        import difflib

        lines_a = a.read_text().splitlines(keepends=True)
        lines_b = b.read_text().splitlines(keepends=True)
        diff = list(
            difflib.unified_diff(lines_a, lines_b, fromfile=str(a), tofile=str(b))
        )
        if not diff:
            return "Files are identical."
        result = "".join(diff)
        return result[:8000] if len(result) > 8000 else result
    except Exception as e:
        logger.error(
            "diff_files failed: %s", e, extra={"path_a": path_a, "path_b": path_b}
        )
        return f"ERROR: {e}"


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
                return (
                    "OK: done"
                    if cur.rowcount == -1
                    else f"OK: {cur.rowcount} row(s) affected"
                )
            finally:
                conn.close()

        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.error("sqlite_exec failed: %s", e)
        return f"ERROR: {e}"


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


async def _generate_image(prompt: str, size: str = "512x512", steps: int = 4) -> str:
    log_audit(f"GENERATE_IMAGE: prompt={prompt!r} size={size} steps={steps}")
    try:
        import requests as _requests

        loop = asyncio.get_running_loop()
        payload = {"prompt": prompt, "size": size, "steps": int(steps)}

        def _sync_post():
            return _requests.post(
                "http://localhost:9379/v1/image/generate",
                json=payload,
                timeout=125,
            )

        resp = await loop.run_in_executor(None, _sync_post)
        data = resp.json()

        if resp.status_code != 200 or "error" in data:
            error = data.get("error", "generation_failed")
            return f"ERROR: Image generation failed — {error}"

        return json.dumps(
            {
                "__image__": True,
                "image_b64": data["image_b64"],
                "width": data["width"],
                "height": data["height"],
                "steps": data["steps"],
                "elapsed_ms": data["elapsed_ms"],
                "prompt": prompt,
                "size": size,
            }
        )
    except Exception as e:
        logger.error("_generate_image failed: %s", e)
        return f"ERROR: {e}"


def _as_str(value: str) -> str:
    """Escape a value for safe embedding in an AppleScript string literal."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


async def _osascript(script: str) -> str:
    loop = asyncio.get_running_loop()

    def _run():
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
            return r.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(e.stderr.strip() or str(e)) from e

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
        props = [f'summary:"{_as_str(title)}"', f'start date:(date "{_as_str(start)}")']
        props.append(f'end date:(date "{_as_str(end or start)}")')
        if notes:
            props.append(f'description:"{_as_str(notes)}"')
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


async def _reminders_list(list_name: str = "") -> str:
    try:
        target = f'list "{_as_str(list_name)}"' if list_name else "default list"
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
        props = [f'name:"{_as_str(text)}"']
        if due:
            props.append(f'due date:(date "{_as_str(due)}")')
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


async def _notes_search(query: str) -> str:
    try:
        script = f"""
        tell application "Notes"
            set output to ""
            repeat with n in (notes whose name contains "{_as_str(query)}")
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
        t = _as_str(title)
        b = _as_str(body)
        html_body = f"<div><b>{t}</b></div><div>{b}</div>"
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
        if "unable to open database" in str(e).lower():
            return (
                "ERROR: cannot open the Messages database. macOS blocks it "
                "until the bridge has Full Disk Access — grant it under System "
                "Settings → Privacy & Security → Full Disk Access (add the "
                "bridge's Python/launchd process), then restart the bridge."
            )
        return f"ERROR: {e}"


async def _send_message(recipient: str, text: str) -> str:
    log_audit(f"SEND_MESSAGE: to={recipient}")
    try:
        script = f"""
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{_as_str(recipient)}" of targetService
            send "{_as_str(text)}" to targetBuddy
        end tell
        """
        await _osascript(script)
        return f"OK: message sent to {recipient}"
    except Exception as e:
        logger.error("send_message failed: %s", e)
        return f"ERROR: {e}"


async def _mail_compose(to: str, subject: str, body: str) -> str:
    log_audit(f"MAIL_COMPOSE: to={to} subject={subject}")
    try:
        script = f"""
        tell application "Mail"
            set msg to make new outgoing message with properties {{subject:"{_as_str(subject)}", content:"{_as_str(body)}", visible:true}}
            tell msg
                make new to recipient at end of to recipients with properties {{address:"{_as_str(to)}"}}
            end tell
        end tell
        """
        await _osascript(script)
        return f"OK: drafted email to {to} (review and send manually)"
    except Exception as e:
        logger.error("mail_compose failed: %s", e)
        return f"ERROR: {e}"


async def _search_contacts(query: str) -> str:
    try:
        script = f"""
        tell application "Contacts"
            set output to ""
            repeat with p in (people whose name contains "{_as_str(query)}")
                set rec to name of p
                repeat with e in emails of p
                    set rec to rec & " | email: " & (value of e)
                end repeat
                repeat with ph in phones of p
                    set rec to rec & " | phone: " & (value of ph)
                end repeat
                try
                    set b to birth date of p
                    if class of b is date then
                        set bstr to (year of b as string) & "-" & ¬
                            text -2 thru -1 of ("0" & ((month of b) as integer)) & "-" & ¬
                            text -2 thru -1 of ("0" & (day of b))
                        set rec to rec & " | birthday: " & bstr
                    end if
                end try
                try
                    set org to organization of p
                    if org is not missing value and org is not "" then
                        set rec to rec & " | org: " & org
                    end if
                end try
                try
                    set nt to note of p
                    if nt is not missing value and nt is not "" then
                        set rec to rec & " | note: " & nt
                    end if
                end try
                set output to output & rec & linefeed
            end repeat
            return output
        end tell
        """
        out = await _osascript(script)
        return out or "No matching contacts."
    except Exception as e:
        logger.error("search_contacts failed: %s", e)
        return f"ERROR: {e}"


async def _birthdays_upcoming(days: int = 30) -> str:
    """List Contacts whose birthday falls within the next `days` days.

    The macOS Birthdays calendar is auto-generated from Contacts and is not
    reliably enumerable via AppleScript's `every event of c`, so we walk
    Contacts directly and compute the next occurrence in Python.
    """
    try:
        window = max(1, int(days))
        script = """
        tell application "Contacts"
            set output to ""
            repeat with p in people
                try
                    set b to birth date of p
                    if class of b is date then
                        set m to (month of b) as integer
                        set d to day of b
                        set y to year of b
                        set output to output & (name of p) & "\t" & ¬
                            (m as string) & "\t" & (d as string) & "\t" & (y as string) & linefeed
                    end if
                end try
            end repeat
            return output
        end tell
        """
        raw = await _osascript(script)
        if not raw.strip():
            return "No contacts with birthdays found."

        from datetime import date, timedelta

        today = date.today()
        end = today + timedelta(days=window)
        hits: list[tuple[date, str, int | None]] = []
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name, m_s, d_s, y_s = parts[0], parts[1], parts[2], parts[3]
            try:
                m, d = int(m_s), int(d_s)
                birth_year: int | None = int(y_s) if y_s.strip() else None
            except ValueError:
                continue
            # Roll this year's birthday forward if it already passed.
            try:
                next_bd = date(today.year, m, d)
            except ValueError:
                # Feb 29 on a non-leap year — fall back to Feb 28.
                if m == 2 and d == 29:
                    next_bd = date(today.year, 2, 28)
                else:
                    continue
            if next_bd < today:
                try:
                    next_bd = date(today.year + 1, m, d)
                except ValueError:
                    next_bd = date(today.year + 1, 2, 28)
            if today <= next_bd <= end:
                age_turning = (
                    next_bd.year - birth_year
                    if birth_year and birth_year > 1900
                    else None
                )
                hits.append((next_bd, name, age_turning))

        if not hits:
            return f"No upcoming birthdays in the next {window} day(s)."

        hits.sort(key=lambda x: (x[0], x[1]))
        lines = []
        for bd, name, age in hits:
            extra = f" (turns {age})" if age else ""
            lines.append(f"{bd.isoformat()} — {name}{extra}")
        return "\n".join(lines)
    except Exception as e:
        logger.error("birthdays_upcoming failed: %s", e)
        return f"ERROR: {e}"


async def _contacts_create(name: str, phone: str = "", email: str = "") -> str:
    log_audit(f"CONTACTS_CREATE: {name}")
    try:
        first, _, last = name.partition(" ")
        lines = [
            'tell application "Contacts"',
            f'set p to make new person with properties {{first name:"{_as_str(first)}", '
            f'last name:"{_as_str(last)}"}}',
        ]
        if email:
            lines.append(
                "make new email at end of emails of p with properties "
                f'{{value:"{_as_str(email)}"}}'
            )
        if phone:
            lines.append(
                "make new phone at end of phones of p with properties "
                f'{{value:"{_as_str(phone)}"}}'
            )
        lines.append("save")
        lines.append("end tell")
        await _osascript("\n".join(lines))
        return f"OK: created contact '{name}'"
    except Exception as e:
        logger.error("contacts_create failed: %s", e)
        return f"ERROR: {e}"


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
        if resp.status_code != 200:
            return f"ERROR: RAG search failed — {resp.status_code}"
        data = resp.json()
        if data.get("count", 0) == 0:
            return "No relevant documents found in memory."
        return data.get("results", "")
    except Exception as e:
        logger.error("recall failed: %s", e)
        return f"ERROR: {e}"


def _parse_cli_output(stdout: str, stderr: str) -> str:
    """Return pretty-printed JSON if stdout is valid JSON, otherwise raw combined output."""
    try:
        parsed = json.loads(stdout)
        return json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, ValueError):
        return (stdout + stderr).strip()


async def _gh_run(args: str) -> str:
    log_audit(f"GH_RUN: {args}")
    try:
        import shlex

        result = subprocess.run(
            ["gh"] + shlex.split(args),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = _parse_cli_output(result.stdout, result.stderr)
        return output[:6000] if len(output) > 6000 else output
    except subprocess.TimeoutExpired:
        logger.error("gh_run timed out", extra={"args": args})
        return "ERROR: timed out after 60s"
    except FileNotFoundError:
        return "ERROR: gh not found — install with: brew install gh"
    except Exception as e:
        logger.error("gh_run failed: %s", e, extra={"args": args})
        return f"ERROR: {e}"


async def _aws_run(args: str) -> str:
    log_audit(f"AWS_RUN: {args}")
    try:
        import shlex

        result = subprocess.run(
            ["aws"] + shlex.split(args),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = _parse_cli_output(result.stdout, result.stderr)
        return output[:6000] if len(output) > 6000 else output
    except subprocess.TimeoutExpired:
        logger.error("aws_run timed out", extra={"args": args})
        return "ERROR: timed out after 120s"
    except FileNotFoundError:
        return "ERROR: aws not found — install with: brew install awscli"
    except Exception as e:
        logger.error("aws_run failed: %s", e, extra={"args": args})
        return f"ERROR: {e}"


async def _hf_run(args: str) -> str:
    log_audit(f"HF_RUN: {args}")
    try:
        import shlex

        result = subprocess.run(
            ["huggingface-cli"] + shlex.split(args),
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = _parse_cli_output(result.stdout, result.stderr)
        return output[:6000] if len(output) > 6000 else output
    except subprocess.TimeoutExpired:
        logger.error("hf_run timed out", extra={"args": args})
        return "ERROR: timed out after 300s — for large downloads use shell() instead"
    except FileNotFoundError:
        return "ERROR: huggingface-cli not found — install with: pip install huggingface_hub[cli]"
    except Exception as e:
        logger.error("hf_run failed: %s", e, extra={"args": args})
        return f"ERROR: {e}"


async def _transcribe(path: str) -> str:
    if _is_placeholder_path(path):
        return (
            "ERROR: please pass an actual audio file path, e.g. "
            'transcribe("/Users/you/Downloads/clip.wav").'
        )
    try:
        p = _validate_user_file_path(path)
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


async def _describe_image(
    path: str, prompt: str = "Describe this image in detail."
) -> str:
    if _is_placeholder_path(path):
        return (
            "ERROR: please pass an actual image file path, e.g. "
            'describe_image("/Users/you/Downloads/foo.png", "what is this?").'
        )
    try:
        p = _validate_user_file_path(path)
        import mlx_vlm

        loop = asyncio.get_running_loop()

        def _run():
            model, processor = mlx_vlm.load("mlx-community/llava-1.5-7b-4bit")
            formatted = mlx_vlm.apply_chat_template(
                processor, model.config, prompt, num_images=1
            )
            result = mlx_vlm.generate(model, processor, formatted, image=str(p))
            return result.text.strip()

        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.error("describe_image failed: %s", e)
        return f"ERROR: {e}"


async def _ocr_image(path: str) -> str:
    if _is_placeholder_path(path):
        return (
            "ERROR: please pass an actual image file path, e.g. "
            'ocr_image("/Users/you/Downloads/foo.png").'
        )
    try:
        p = _validate_user_file_path(path)
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
        stderr = getattr(e, "stderr", None)
        logger.warning(
            "ocr_image native failed (stderr=%s), falling back to VLM: %s", stderr, e
        )
        return await _describe_image(
            path, prompt="Transcribe all text visible in this image."
        )


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
register_tool(
    "grep_search", "safe", "Grep search for a pattern in a path", _grep_search
)
register_tool("list_crons", "safe", "List crontab", _list_crons)
register_tool("write_file", "risky", "Write file", _write_file)
register_tool("append_file", "risky", "Append to file", _append_file)
register_tool("shell", "risky", "Run shell command", _shell)
register_tool("python_interpreter", "risky", "Execute Python code", _python_interpreter)
register_tool("create_cron", "risky", "Create cron job", _create_cron)
register_tool("delete_cron", "risky", "Delete cron job", _delete_cron)
register_tool("git_status", "safe", "Get git status --short", _git_status)
register_tool("git_log", "safe", "Get git log --oneline", _git_log)
register_tool(
    "clipboard_copy", "safe", "Copy text to system clipboard", _clipboard_copy
)
register_tool(
    "clipboard_paste", "risky", "Paste text from system clipboard", _clipboard_paste
)
register_tool("google_search", "safe", "Search Google for a query", _google_search)
register_tool("web_fetch", "safe", "Fetch and clean text from a URL", _web_fetch)
register_tool(
    "get_current_datetime",
    "safe",
    "Get the current local date, time, and timezone",
    _get_current_datetime,
)
register_tool("git_diff", "safe", "Show git diff vs HEAD", _git_diff)
register_tool("find_file", "safe", "Find files by name/glob pattern", _find_file)
register_tool(
    "edit_file",
    "risky",
    "Replace a specific string in a file (first occurrence)",
    _edit_file,
)
register_tool("read_pdf", "safe", "Extract text from a PDF file", _read_pdf)
register_tool("write_pdf", "risky", "Create a PDF file from text content", _write_pdf)
register_tool(
    "read_word",
    "safe",
    "Extract text and annotations from a Word (.docx) file",
    _read_word,
)
register_tool(
    "read_excel",
    "safe",
    "Extract text and annotations from an Excel (.xlsx) file",
    _read_excel,
)
register_tool(
    "write_word", "risky", "Create a Word (.docx) file from a JSON spec", _write_word
)
register_tool(
    "write_excel",
    "risky",
    "Create an Excel (.xlsx) file from a JSON spec",
    _write_excel,
)
register_tool(
    "http_request", "risky", "Make an HTTP request (GET/POST/PUT/DELETE)", _http_request
)
register_tool("notify", "safe", "Send a macOS system notification", _notify)
register_tool("say", "safe", "Speak text aloud via macOS say", _say)
register_tool("screenshot", "risky", "Capture the screen to a PNG file", _screenshot)
register_tool("move_file", "risky", "Move or rename a file", _move_file)
register_tool("delete_file", "risky", "Move a file to the Trash", _delete_file)
register_tool("read_csv", "safe", "Read a CSV file as a table", _read_csv)
register_tool("json_query", "safe", "Query JSON with a dotted path", _json_query)
register_tool("read_ics", "safe", "Parse events from an .ics file", _read_ics)
register_tool(
    "sqlite_exec", "risky", "Run a write statement on a SQLite DB", _sqlite_exec
)
register_tool("system_info", "safe", "Get CPU, RAM, and disk usage", _system_info)
register_tool(
    "sqlite_query",
    "risky",
    "Run a SELECT query against a local SQLite database",
    _sqlite_query,
)
register_tool("diff_files", "safe", "Show a unified diff of two files", _diff_files)
register_tool(
    "generate_image",
    "risky",
    "Generate an image on-device using FLUX.1-schnell via mflux",
    _generate_image,
)
register_tool(
    "recall",
    "safe",
    "Semantic search over ingested documents",
    _recall,
)
register_tool("gh_run", "risky", "Run a GitHub CLI command (gh)", _gh_run)
register_tool("aws_run", "risky", "Run an AWS CLI command (aws)", _aws_run)
register_tool(
    "hf_run", "risky", "Run a Hugging Face CLI command (huggingface-cli)", _hf_run
)
register_tool("calendar_list", "safe", "List upcoming Calendar events", _calendar_list)
register_tool("calendar_create", "risky", "Create a Calendar event", _calendar_create)
register_tool("reminders_list", "safe", "List open reminders", _reminders_list)
register_tool("reminders_create", "risky", "Create a reminder", _reminders_create)
register_tool("notes_search", "safe", "Search Apple Notes", _notes_search)
register_tool("notes_create", "risky", "Create an Apple Note", _notes_create)
register_tool("messages_read", "risky", "Read recent iMessages", _messages_read)
register_tool("send_message", "risky", "Send an iMessage", _send_message)
register_tool("mail_compose", "risky", "Draft an email (no auto-send)", _mail_compose)
register_tool("search_contacts", "safe", "Search Contacts by name", _search_contacts)
register_tool("contacts_create", "risky", "Create a contact", _contacts_create)
register_tool(
    "birthdays_upcoming",
    "safe",
    "List Contacts birthdays in the next N days",
    _birthdays_upcoming,
)
register_tool("transcribe", "safe", "Transcribe an audio file to text", _transcribe)
register_tool("describe_image", "safe", "Describe an image on-device", _describe_image)
register_tool("ocr_image", "safe", "Extract text from an image (OCR)", _ocr_image)

# Note: create_scheduled_task and list_scheduled_tasks are omitted from here
# because they depend on the scheduler in agent.py.
# We'll add them back to the registry in agent.py or keep them separate.

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are an autonomous agent with access to the internet and local tools.

TOOLS AVAILABLE:
  google_search(query)                           — search the web for real-time information
  web_fetch(url)                                 — fetch and read a webpage
  get_current_datetime()                         — get the current date and time
  read_file(path)                                — read a local file
  list_dir(path)                                 — list directory contents
  grep_search(pattern, path)                     — search files for a pattern
  write_file(path, content)                      — write a file
  append_file(path, content)                     — append to a file
  shell(command)                                 — run a shell command
  python_interpreter(code)                       — execute Python code
  git_status()                                   — git status
  git_log(limit)                                 — git log
  git_diff(path)                                 — show changes vs HEAD (optional path)
  find_file(pattern, path)                       — find files by name/glob (e.g. "*.py")
  edit_file(path, old_str, new_str)              — replace first occurrence of old_str in file
  read_pdf(path)                                 — extract text from a local PDF file
  write_pdf(path, content)                       — create a PDF file from text content
  read_word(path)                               — extract text, comments, tracked changes, footnotes, and metadata from a Word (.docx) file
  read_excel(path)                              — extract cell values, formulas, notes, and threaded comments from an Excel (.xlsx) file
  write_word(path, spec)                        — create a Word file from a JSON spec dict (sections with headings, paragraphs, tables, footnotes)
  write_excel(path, spec)                       — create an Excel file from a JSON spec dict (sheets, cells, merges, charts)
  http_request(method, url, headers, body)       — make an HTTP request; headers is JSON string
  notify(title, message)                         — send a macOS system notification
  say(text)                                      — speak text aloud through the speakers
  screenshot()                                   — capture the screen; call with no args to save to ~/Downloads with macOS naming, or screenshot("/path/to/file.png") for a specific path
  move_file(src, dst)                            — move or rename a file
  delete_file(path)                              — move a file to the Trash (recoverable)
  read_csv(path)                                 — read a CSV file as a tab-separated table
  json_query(path_or_text, expr)                 — extract a value from JSON, e.g. "users[0].name"
  read_ics(path)                                 — list events from a local .ics calendar file
  sqlite_exec(db_path, sql)                      — run INSERT/UPDATE/DELETE/CREATE on a SQLite DB
  system_info()                                  — get CPU, RAM, and disk usage
  sqlite_query(db_path, sql)                     — run a SELECT query on a local SQLite DB
  diff_files(path_a, path_b)                     — show a unified diff of two files
  generate_image(prompt, size, steps)            — generate an image on-device; size: "512x512"|"768x768"|"512x768"; steps 1-12 (default 4)
  gh_run(args)                                   — run a GitHub CLI command, e.g. "pr list --limit 10"
  aws_run(args)                                  — run an AWS CLI command, e.g. "s3 ls s3://my-bucket"
  hf_run(args)                                   — run a Hugging Face CLI command, e.g. "download org/model"
  clipboard_copy(text)                           — copy to clipboard
  clipboard_paste()                              — paste from clipboard
  list_crons()                                   — list cron jobs
  create_cron(name, schedule, command)           — create a cron job
  delete_cron(name)                              — delete a cron job
  list_scheduled_tasks()                         — list in-app scheduled tasks
  create_scheduled_task(name, schedule, prompt)  — create a scheduled task
  recall(query)                                  — semantic search over your ingested documents
  calendar_list(days)                            — list upcoming Calendar events (default 7 days)
  calendar_create(title, start, end, notes)      — create a Calendar event; dates like "6/1/2026 12:00:00"
  reminders_list(list)                           — list open reminders (list name optional)
  reminders_create(text, due)                    — add a reminder; due like "6/1/2026 09:00:00"
  notes_search(query)                            — search Apple Notes by title and read matches
  notes_create(title, body)                      — create a new Apple Note
  messages_read(limit)                           — read your most recent iMessages
  send_message(recipient, text)                  — send an iMessage to a phone/email
  mail_compose(to, subject, body)                — draft an email in Mail (you review and send)
  search_contacts(query)                         — find people in Contacts (name, phone, email, birthday, org, note)
  contacts_create(name, phone, email)            — create a new contact
  birthdays_upcoming(days)                       — list contacts with birthdays in the next N days (default 30)
  transcribe("/Users/you/Downloads/clip.wav")    — transcribe an audio file to text on-device; pass a real path
  describe_image("/Users/you/Downloads/foo.png", "what is this?") — describe/answer questions about an image on-device; pass a real path
  ocr_image("/Users/you/Downloads/foo.png")      — extract text from an image via OCR; pass a real path

RULES:
1. For any real-time query (news, weather, scores, prices, current events): call google_search. You have internet access.
2. Call exactly ONE tool per response, on its own line:
   TOOL: tool_name("arg1", "arg2")
3. After receiving a tool result, decide: do you need another tool, or can you answer now?
4. If a tool returns an error, try a different approach once. If it fails again, tell the user what went wrong.
5. When you have enough information to answer, output:
   DONE: <your answer>
   Write your DONE answer as a complete, standalone response — as if the user never saw the intermediate tool calls.
6. Never invent tool results. Never assume you know a tool's output before calling it.

CITATIONS:
- TOOL_RESULTs are numbered like [1], [2], [3]. These indices are stable
  across the whole conversation turn.
- When you state a fact from a tool result, append the matching index in
  square brackets at the end of the claim. Multiple sources: [1][3].
- Do NOT invent or renumber citations. Only cite indices that appeared
  in a TOOL_RESULT above.
- In your final DONE: answer, keep the [N] markers inline.

EXAMPLE:
User: What's the score of last night's Lakers game?
TOOL: google_search("Lakers score last night")
TOOL_RESULT:
[1] ESPN — NBA Scores (espn.com)
    Lakers 112, Celtics 108. Final score from last night's game.
DONE: The Lakers beat the Celtics 112–108 last night [1]."""


def strip_thinking_blocks(text: str) -> str:
    """Strip all known thinking-block formats used by Gemma 4 and related models."""
    # Gemma 4 channel format — complete blocks (closing tag present)
    text = re.sub(
        r"<\|channel\|?>thought\n?.*?<\|?channel\|>", "", text, flags=re.DOTALL
    )
    # Gemma 4 channel format — truncated/unclosed blocks (output hit token limit mid-thought)
    text = re.sub(r"<\|channel\|?>thought\n?.*$", "", text, flags=re.DOTALL)
    # Generic XML-style thinking blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _arg_literal(node: ast.AST) -> Any:
    """Best-effort convert an AST arg node to a Python value.

    Falls back to the raw source (or bare name) for non-literal values like an
    unquoted word, e.g. send_message(recipient=mom) -> "mom".
    """
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        if isinstance(node, ast.Name):
            return node.id
        try:
            return ast.unparse(node)
        except Exception:
            return ""


def _parse_tool_args(raw_args: str) -> tuple[list, dict]:
    """Parse a tool-call argument string into (positional, keyword) arguments.

    Handles the model's natural call styles: quoted positional args, numeric
    literals, and keyword=value pairs (e.g. calendar_list(days=1),
    notes_create(title="A", body="B")). Parsing the args as a Python call
    expression (via ast, never executed) also correctly handles quotes
    containing commas, single quotes, etc.
    """
    raw_args = raw_args.strip()
    if not raw_args:
        return [], {}
    try:
        call = ast.parse(f"_f({raw_args})", mode="eval").body
        if isinstance(call, ast.Call):
            args = [_arg_literal(a) for a in call.args]
            kwargs = {kw.arg: _arg_literal(kw.value) for kw in call.keywords if kw.arg}
            return args, kwargs
    except (SyntaxError, ValueError):
        pass
    # Fallback for non-parseable args: comma-split, detect key=value.
    args, kwargs = [], {}
    for part in raw_args.split(", "):
        part = part.strip()
        m = re.match(r"^(\w+)=(.*)$", part)
        if m:
            kwargs[m.group(1)] = m.group(2).strip().strip("\"'")
        else:
            args.append(part.strip("\"'"))
    return args, kwargs


def parse_model_output(text: str) -> tuple[str, str, list, dict] | None:
    """Return (type, tool_or_message, args, kwargs) or None if neither TOOL nor
    DONE found."""
    # Strip all thinking block formats before parsing so that tool/done references
    # inside thinking blocks don't trigger real tool calls or false done signals.
    # The original text is preserved in the message history; only parsing uses clean_text.
    clean_text = strip_thinking_blocks(text)

    # Native Gemma format: <|tool_call>call:tool_name("arg")<tool_call|>
    native_match = re.search(
        r"<\|tool_call\>call:(\w+)\((.*?)\)<tool_call\|>", clean_text, re.DOTALL
    )
    # Text-based format: TOOL: tool_name("arg")
    tool_match = re.search(r"TOOL:\s*(\w+)\((.*)\)\s*$", clean_text, re.MULTILINE)
    done_match = re.search(r"DONE:\s*(.+)", clean_text, re.MULTILINE)

    active_match = native_match or tool_match
    if active_match:
        tool_name = active_match.group(1)
        args, kwargs = _parse_tool_args(active_match.group(2))
        return ("tool", tool_name, args, kwargs)
    if done_match:
        return ("done", done_match.group(1).strip(), [], {})
    return None
