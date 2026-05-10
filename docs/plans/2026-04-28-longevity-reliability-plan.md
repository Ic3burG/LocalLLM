# Longevity & Reliability Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement context window summarization and an inference watchdog to ensure stability during long sessions.

**Architecture:** Add a `SessionOptimizer` for rolling history compression and a background supervisor thread to detect and interrupt stalled GPU tasks.

**Tech Stack:** Python (FastAPI, mlx-vlm, threading).

---

### Task 1: Context Monitoring & Token Estimator

**Files:**

- Modify: `agent.py`

**Step 1: Write the failing test**

```python
def test_token_estimation():
    from agent import estimate_tokens
    messages = [{"role": "user", "content": "hello world"}]
    assert estimate_tokens(messages) > 0
```

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=. ./.venv/bin/pytest tests/test_longevity.py -v`
Expected: FAIL (Module not found or function not defined)

**Step 3: Implement `estimate_tokens` in `agent.py`**

```python
def estimate_tokens(messages: list) -> int:
    total = 0
    for m in messages:
        total += len(m.get("content", "")) // 4 + 4
    return total
```

**Step 4: Run test to verify it passes**
Run: `PYTHONPATH=. ./.venv/bin/pytest tests/test_longevity.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add agent.py tests/test_longevity.py
git commit -m "feat: add token estimation logic"
```

---

### Task 2: Rolling Context Summarization

**Files:**

- Modify: `agent.py`

**Step 1: Write the summarization trigger test**
Mock `run_inference` and verify that when tokens > Soft Limit, a summary request is sent.

**Step 2: Implement `SessionOptimizer` logic**
Integrate `summarize_history` into the `_react_loop_internal` in `agent.py`.

**Step 3: Verify summarization**
Run tests to ensure history is pruned correctly.

**Step 4: Commit**

```bash
git commit -m "feat: implement rolling context summarization"
```

---

### Task 3: Inference Watchdog & Heartbeats

**Files:**

- Modify: `inference_engine.py`

**Step 1: Add `last_activity` timestamp to worker**
Update the inference loop to set a global timestamp every yielded token.

**Step 2: Implement Watchdog thread**
Add a daemon thread that checks the timestamp and sets the MLX `stop` flag if > 180s.

**Step 3: Verify with mock hanging tool**
Add a test in `tests/test_longevity.py` that times out and returns an error.

**Step 4: Commit**

```bash
git commit -m "stab: add inference watchdog and heartbeat mechanism"
```
