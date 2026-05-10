# Design Spec: Longevity & Reliability Layer

This document details the design for maintaining session quality and process stability during long-running, complex tasks in the Gemma 4 Local Suite.

## 1. Rolling Context Compression (SessionOptimizer)

To prevent cognitive degradation and context-window-induced OOMs, the system will manage the chat history as a "Sliding Window" with periodic compression.

### 1.1 Token Monitoring

- **Module:** `agent.py` / `SessionOptimizer`
- **Logic:**
  - Before every inference call, estimate the total token count of the `messages` list (using a simple `len(str(msg)) // 4` heuristic or the actual tokenizer if available in the worker).
  - **Limits:**
    - Context Window: 32,768 tokens (Gemma 4 default).
    - Compression Trigger (Soft Limit): 16,000 tokens.
    - Safety Margin (Hard Limit): 28,000 tokens (beyond this, the oldest non-system messages are dropped without summary to prevent immediate crash).

### 1.2 Automated Summarization

- When the **Soft Limit** is hit:
  1.  The agent identifies the first 50% of the history (excluding the initial System Prompt).
  2.  An internal "Sub-task" is sent to the model: `"Summarize the key decisions, file modifications, and current project goals from the following history in 500 words or less."`
  3.  The summarized block is saved as a special `[PERSISTENT SESSION CONTEXT]` message.
  4.  The original 50% history is removed from the active queue.
  5.  The summary is inserted immediately after the initial System Prompt.

## 2. Inference Watchdog & Liveness Detection

To prevent the GPU worker from hanging or entering infinite loops, a supervisor thread will monitor process "liveness."

### 2.1 Heartbeat Mechanism

- **Module:** `inference_engine.py`
- **Implementation:**
  - The `generate` loop in the MLX worker will update a `last_activity_timestamp` global every time a new token is yielded (or every 5 seconds during thinking).
  - The worker will push a `{"type": "heartbeat"}` event to the SSE stream.

### 2.2 Watchdog Supervisor

- A daemon thread will run a loop every 10 seconds.
- **Timeout:** 180 seconds.
- **Recovery Action:**
  1.  If `current_time - last_activity_timestamp > 180s`:
      - Trigger a model interrupt (MLX `stop_generating` flag).
      - Send a `504 Gateway Timeout` (or SSE equivalent) to the client.
      - Log a CRITICAL error in `audit.log`.
      - Attempt to reload the model if the interrupt fails to clear the hang.

## 3. UI Feedback (Longevity Indicators)

- **Heartbeat Visual:** A small pulsars icon or "Thinking (Xs)..." text in the UI to confirm the backend is still responsive.
- **Compression Alert:** A non-intrusive toast notification: `"Session context compressed to maintain speed."`

## 4. Verification Plan

- **Longevity Test:** Use a script to feed the agent 20k tokens of "lore" and verify that a summary is triggered and the context remains coherent.
- **Watchdog Test:** Create a mock "Hanging Tool" that sleeps for 300 seconds and verify that the Watchdog interrupts it at 180s.

---

### Approval Request

Does this detailed design meet your expectations for session stability? If so, I will proceed to create the implementation plan.
