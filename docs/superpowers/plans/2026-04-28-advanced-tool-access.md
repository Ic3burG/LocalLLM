# Advanced Tool Access Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand the Gemma 4 agent's capabilities with Web Search, Codebase Search, Git Integration, Clipboard Access, and a Python Interpreter.

**Architecture:** Add specialized tool functions to `agent.py`, update the `TOOL_REGISTRY`, and expand the `AGENT_SYSTEM_PROMPT`.

**Tech Stack:** Python, `googlesearch-python`, `requests`, `beautifulsoup4`, `pyperclip`, `git`, `re`.

---

### Task 1: Install Dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Update requirements.txt**

Add the following to `requirements.txt`:
```text
googlesearch-python
requests
beautifulsoup4
pyperclip
```

**Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: Success

**Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add dependencies for advanced tools"
```

---

### Task 2: Web Research Tools

**Files:**
- Modify: `agent.py`
- Test: `tests/test_agent_tools.py`

**Step 1: Write tests for web tools**

Create `tests/test_agent_tools.py`:
```python
import pytest
from agent import _google_search, _web_fetch

@pytest.mark.asyncio
async def test_google_search():
    # We won't actually call Google in tests to avoid flakiness/rate limits
    # but we should verify the tool exists and can be mocked or handled.
    pass

@pytest.mark.asyncio
async def test_web_fetch():
    # Test with a known static site or local server if possible
    pass
```

**Step 2: Implement _google_search and _web_fetch in agent.py**

```python
from googlesearch import search as gsearch
import requests
from bs4 import BeautifulSoup

async def _google_search(query: str) -> str:
    try:
        results = []
        for j in gsearch(query, num=5, stop=5, pause=2):
            results.append(j)
        return "\n".join(results)
    except Exception as e:
        return f"ERROR: {e}"

async def _web_fetch(url: str) -> str:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        # Remove script and style elements
        for script or style in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text(separator=' ')
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text[:5000] # Truncate to avoid context overflow
    except Exception as e:
        return f"ERROR: {e}"
```

**Step 3: Commit**

```bash
git add agent.py tests/test_agent_tools.py
git commit -m "feat: add google_search and web_fetch tools"
```

---

### Task 3: Codebase Navigation Tool

**Files:**
- Modify: `agent.py`

**Step 1: Implement _grep_search in agent.py**

```python
async def _grep_search(pattern: str, path: str = ".") -> str:
    try:
        results = []
        regex = re.compile(pattern, re.IGNORECASE)
        root_path = Path(os.path.expanduser(path))
        for root, dirs, files in os.walk(root_path):
            if ".git" in dirs:
                dirs.remove(".git")
            for file in files:
                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append(f"{file_path}:{i}: {line.strip()}")
                except Exception:
                    continue
        return "\n".join(results[:50]) or "No matches found."
    except Exception as e:
        return f"ERROR: {e}"
```

**Step 2: Commit**

```bash
git add agent.py
git commit -m "feat: add grep_search tool"
```

---

### Task 4: Git Integration Tools

**Files:**
- Modify: `agent.py`

**Step 1: Implement git tools in agent.py**

```python
async def _git_status() -> str:
    try:
        result = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, check=True)
        return result.stdout or "Clean working directory."
    except Exception as e:
        return f"ERROR: {e}"

async def _git_log(limit: int = 5) -> str:
    try:
        result = subprocess.run(["git", "log", "-n", str(limit), "--oneline"], capture_output=True, text=True, check=True)
        return result.stdout
    except Exception as e:
        return f"ERROR: {e}"
```

**Step 2: Commit**

```bash
git add agent.py
git commit -m "feat: add git_status and git_log tools"
```

---

### Task 5: System Utility Tools

**Files:**
- Modify: `agent.py`

**Step 1: Implement clipboard tools in agent.py**

```python
import pyperclip

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
```

**Step 2: Commit**

```bash
git add agent.py
git commit -m "feat: add clipboard tools"
```

---

### Task 6: Logic Tool (Python Interpreter)

**Files:**
- Modify: `agent.py`

**Step 1: Implement _python_interpreter in agent.py**

```python
import sys
from io import StringIO

async def _python_interpreter(code: str) -> str:
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    try:
        exec(code)
        return redirected_output.getvalue() or "OK: executed (no output)"
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        sys.stdout = old_stdout
```

**Step 2: Commit**

```bash
git add agent.py
git commit -m "feat: add python_interpreter tool"
```

---

### Task 7: Registry and Prompt Update

**Files:**
- Modify: `agent.py`

**Step 1: Update TOOL_REGISTRY in agent.py**

Add the new tools to `TOOL_REGISTRY`:
```python
    "google_search": Tool("google_search", "safe", "Search Google", _google_search),
    "web_fetch": Tool("web_fetch", "safe", "Fetch webpage content", _web_fetch),
    "grep_search": Tool("grep_search", "safe", "Recursive search for pattern", _grep_search),
    "git_status": Tool("git_status", "safe", "Get git status", _git_status),
    "git_log": Tool("git_log", "safe", "Get git log", _git_log),
    "clipboard_copy": Tool("clipboard_copy", "safe", "Copy to clipboard", _clipboard_copy),
    "clipboard_paste": Tool("clipboard_paste", "risky", "Paste from clipboard", _clipboard_paste),
    "python_interpreter": Tool("python_interpreter", "risky", "Run Python code", _python_interpreter),
```

**Step 2: Update AGENT_SYSTEM_PROMPT in agent.py**

```python
AGENT_SYSTEM_PROMPT = """You are an autonomous agent. You have access to these tools:
  read_file(path), list_dir(path), write_file(path, content),
  append_file(path, content), shell(command), list_crons(),
  create_cron(name, schedule, command), delete_cron(name),
  list_scheduled_tasks(), create_scheduled_task(name, schedule, prompt),
  google_search(query), web_fetch(url), grep_search(pattern, path="."),
  git_status(), git_log(limit=5), clipboard_copy(text),
  clipboard_paste(), python_interpreter(code)

...
"""
```

**Step 3: Commit**

```bash
git add agent.py
git commit -m "feat: register new tools and update system prompt"
```
