# Code Integrity & Health Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a multi-layered integrity suite (Smoke Test, Contract Tests, and Vitals Dashboard) to catch regressions and monitor performance.

**Architecture:** Add a connectivity CLI, a "real-world" contract test suite, and a telemetry endpoint for UI-based monitoring.

**Tech Stack:** Python (requests, psutil, mlx), JavaScript (Fetch, UI DOM).

---

### Task 1: API Connectivity Smoke Test

**Files:**
- Create: `scripts/smoke_test.py`

**Step 1: Create basic smoke test structure**
Write a script that pings localhost:3001 and localhost:9379.

**Step 2: Add Text & Vision roundtrip checks**
Implement actual API calls with minimal payloads to verify the full stack.

**Step 3: Verify script**
Run: `python3 scripts/smoke_test.py`
Expected: A summary table showing connectivity status.

---

### Task 2: Dependency Contract Tests

**Files:**
- Create: `tests/contracts/test_search_contract.py`
- Create: `tests/contracts/test_mlx_contract.py`

**Step 1: Write Search contract test**
Verify that the current search implementation returns valid results without mocking.

**Step 2: Write MLX contract test**
Verify that `mlx-vlm` can still load a model and generate a token.

**Step 3: Run contract tests**
Run: `PYTHONPATH=. ./.venv/bin/pytest tests/contracts -v`
Expected: PASS (if internet/GPU are available).

---

### Task 3: Performance Telemetry Endpoint

**Files:**
- Modify: `gemma_bridge.py`
- Modify: `gemma-web/server.js`

**Step 1: Add `/v1/stats` to Python Bridge**
Use `psutil` to collect RAM usage and `inference_engine` to track latency.

**Step 2: Proxy stats to Node.js**
Add `GET /api/stats` to `server.js`.

**Step 3: Verify endpoint**
Run: `curl http://localhost:3001/api/stats`
Expected: JSON object with RAM, VRAM, and Latency stats.

---

### Task 4: UI Vitals Dashboard

**Files:**
- Modify: `gemma-web/index.html`

**Step 1: Add "Vitals" tab to Settings modal**
Update the UI to include a new tab and display telemetry data.

**Step 2: Add "Run Health Check" button**
Wire the button to trigger the backend smoke test logic and display results.

**Step 3: Final verification**
Open UI, go to Settings > Vitals, verify data updates and checks pass.
