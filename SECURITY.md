# Gemma 4 Security & Integrity Documentation

This document outlines the security architecture, hardening measures, and integrity verification protocols for the local Gemma 4 project.

## 🛡️ Security Architecture

### 1. Path Sandboxing
To prevent path traversal attacks, all file-system tools (`read_file`, `write_file`, `list_dir`, `append_file`) are confined to the project root.
- **Implementation:** `validate_path(path_str)` in `agent_utils.py` uses `pathlib.Path.relative_to` to ensure no tool can escape the sandbox.
- **Tests:** `tests/test_audit.py` verifies that attempts to access `/etc/passwd` or sibling directories are blocked.

### 2. SSRF Protection
The `web_fetch` tool is restricted from accessing internal or sensitive network resources.
- **Implementation:** `validate_url(url)` blocks requests to `localhost`, `127.0.0.1`, private IP ranges (RFC 1918), and cloud metadata IPs.

### 3. API Hardening
- **Network Binding:** The Python Bridge (`gemma_bridge.py`) binds strictly to `127.0.0.1`, preventing external access to the local model server.
- **CORS:** `allow_origins` is restricted specifically to `http://localhost:3001`.
- **Validation:** All inputs to risky tools (shell, file write) require explicit user confirmation via the UI's **Confirmation Gate**.

### 4. Audit Logging
All risky tool executions (e.g., `shell`, `write_file`) are logged to a protected `audit.log`.
- **Location:** The audit log is stored one level above the project sandbox to prevent the agent from modifying or deleting its own activity history.

## 🧪 Integrity Verification

### 1. Connectivity Smoke Tests
A standalone utility, `scripts/smoke_test.py`, provides end-to-end verification of the full stack.
- **Run Command:** `python3 scripts/smoke_test.py`
- **Coverage:** Node.js proxy health, Python Bridge availability, and Text/Vision model inference.

### 2. Dependency Contract Tests
Located in `tests/contracts/`, these tests verify that upstream libraries (MLX, DuckDuckGo, Pillow) maintain a stable API.
- **Run Command:** `PYTHONPATH=. ./.venv/bin/pytest tests/contracts`
- **Purpose:** Catch "silent" breakage caused by `pip install --upgrade`.

### 3. Vitals Monitoring
The **Settings > Vitals** dashboard provides real-time observability into the system's resource consumption.
- **Process RAM:** Resident Set Size (RSS) of the bridge.
- **GPU VRAM:** Active memory allocated to MLX Metal.
- **Latency:** Rolling average of inference time (ms/token).

## ⚠️ Known Constraints & Risks
- **Shell Tool:** The `shell` tool is powerful; only "Allow" commands you have reviewed in the confirmation card.
- **VRAM OOM:** While an LRU cache is implemented, loading multiple large models (26B/31B) simultaneously may still hit VRAM limits on systems with < 64GB RAM.
