# Advanced Tool Access Design — Gemma 4 Local AI Suite

**Date:** 2026-04-28  
**Status:** Approved

---

## Overview

Expand the Gemma 4 agent's capabilities by adding a suite of "Power User" tools. This expansion focuses on four key areas: Web Research (Google), Codebase Navigation, Git Integration, and System Utilities. These tools will enable the agent to fetch real-time information, understand large codebases, and interact more deeply with the host system.

---

## Tool Specifications

### 1. Web Research

- **`google_search(query: str)`**: Fetches the top 5-10 results from Google.
  - **Library**: `googlesearch-python`
  - **Returns**: A list of titles and URLs.
  - **Risk**: Safe.
- **`web_fetch(url: str)`**: Fetches and cleans the content of a specific webpage.
  - **Library**: `requests` + `beautifulsoup4`
  - **Returns**: Plain text content of the page (truncated if too long).
  - **Risk**: Safe.

### 2. Codebase Navigation

- **`grep_search(pattern: str, path: str = ".")`**: Recursively searches for a pattern in the specified directory.
  - **Implementation**: Python-based recursive search using `re` and `os.walk`.
  - **Returns**: Matching lines with file paths and line numbers.
  - **Risk**: Safe.

### 3. Git Integration

- **`git_status()`**: Returns the current status of the repository.
  - **Implementation**: Wrapper around `git status --short`.
  - **Risk**: Safe.
- **`git_log(limit: int = 5)`**: Returns the most recent commit messages.
  - **Implementation**: Wrapper around `git log -n {limit} --oneline`.
  - **Risk**: Safe.

### 4. System Utility

- **`clipboard_copy(text: str)`**: Copies text to the system clipboard.
  - **Library**: `pyperclip`
  - **Risk**: Safe.
- **`clipboard_paste()`**: Returns the current content of the system clipboard.
  - **Library**: `pyperclip`
  - **Risk**: Risky (requires user confirmation).

### 5. Advanced Logic

- **`python_interpreter(code: str)`**: Executes Python code in a controlled environment and returns stdout.
  - **Implementation**: `exec()` with captured `sys.stdout`.
  - **Risk**: Risky (requires user confirmation).

---

## Implementation Details

### Dependencies

The following packages will be added to `requirements.txt`:

- `googlesearch-python`
- `requests`
- `beautifulsoup4`
- `pyperclip`

### Agent Integration

1.  **Tool Registry**: New functions will be added to `TOOL_REGISTRY` in `agent.py`.
2.  **System Prompt**: The `AGENT_SYSTEM_PROMPT` in `agent.py` will be updated to include the new tool definitions.
3.  **Confirmation Gate**: The `clipboard_paste` and `python_interpreter` tools will be marked as `risky` to trigger the existing confirmation gate.

---

## Error Handling

- **Web**: Handle connection timeouts and SSL errors gracefully.
- **Python**: Capture and return tracebacks to the agent so it can self-correct code.
- **Search**: Handle rate limiting by the search engine.
