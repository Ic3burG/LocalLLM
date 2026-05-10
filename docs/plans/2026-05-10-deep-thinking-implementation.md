# Deep Thinking Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a multi-stage "Deep Thinking" pipeline (Diversify, Critique, Synthesize) triggered by a UI toggle.

**Architecture:** A pre-reasoning stage is added to the agent loop. It runs three sequential inference passes to explore, critique, and synthesize strategies, injecting the final result as the initial "thought" for the ReAct loop.

**Tech Stack:** Python (FastAPI, asyncio), JavaScript (Tailwind CSS, EventSource).

---

### Task 1: Update API Models and Backend Setup

**Files:**

- Modify: `agent.py`
- Modify: `gemma_bridge.py`

**Step 1: Add `deep_think` to `AgentRequest` in `agent.py`**
Modify `AgentRequest` Pydantic model.

```python
class AgentRequest(BaseModel):
    prompt: str | None = None
    messages: list[dict] | None = None
    model_id: str = "gemma4-e4b"
    deep_think: bool = False
```

**Step 2: Update `run_agent` and `chat_stream` to pass `deep_think`**
Update endpoints in `agent.py` and `gemma_bridge.py` to pass the new flag to `react_loop_sse`.

**Step 3: Commit**

```bash
git add agent.py gemma_bridge.py
git commit -m "feat: add deep_think flag to API request models"
```

---

### Task 2: Implement Deep Thinking Logic in `agent.py`

**Files:**

- Modify: `agent.py`

**Step 1: Create `run_deep_thinking_pipeline` function**
This function will handle the 3-stage inference process and emit SSE status updates.

```python
async def run_deep_thinking_pipeline(q: asyncio.Queue, messages: list, model_id: str) -> str:
    # Stage 1: Diversify
    await q.put(json.dumps({"type": "status", "message": "Deep Thinking: Exploring 3 reasoning paths…"}))
    diversify_prompt = "Generate 3 distinct, high-level strategies to solve this problem. Label them Path A, Path B, and Path C."
    # ... logic to call run_inference ...

    # Stage 2: Critique
    await q.put(json.dumps({"type": "status", "message": "Deep Thinking: Critiquing strategies…"}))
    critique_prompt = "Act as a critical reviewer. For each Path (A, B, C), identify one major logical flaw or edge case. Score each 1-10."
    # ... logic ...

    # Stage 3: Synthesize
    await q.put(json.dumps({"type": "status", "message": "Deep Thinking: Synthesizing final plan…"}))
    synth_prompt = "Based on the original problem and your critique, synthesize the absolute best solution. Address the flaws identified."
    # ... logic ...

    return final_reasoning
```

**Step 2: Integrate into `react_loop_sse`**
Call `run_deep_thinking_pipeline` at the start of the loop if `deep_think` is True.

**Step 3: Commit**

```bash
git add agent.py
git commit -m "feat: implement multi-stage deep thinking pipeline in agent.py"
```

---

### Task 3: Update Frontend UI

**Files:**

- Modify: `gemma-web/index.html`

**Step 1: Add "Deep Think" toggle**
Place it next to the model selector in the header.

```html
<label class="inline-flex items-center cursor-pointer ml-4">
  <input type="checkbox" id="deep-think-toggle" class="sr-only peer" />
  <div
    class="relative w-7 h-4 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"
  ></div>
  <span class="ms-2 text-[10px] font-medium text-gray-500">Deep Think</span>
</label>
```

**Step 2: Update request payload**
Modify the `fetch` call in the `chatForm` submit handler to include `deep_think: document.getElementById('deep-think-toggle').checked`.

**Step 3: Commit**

```bash
git add gemma-web/index.html
git commit -m "ui: add deep think toggle and update api request"
```

---

### Task 4: Verification and Testing

**Step 1: Verify standard chat**
Ensure chat works correctly with Deep Think OFF.

**Step 2: Verify Deep Thinking**
Toggle Deep Think ON. Verify the UI shows the "Exploring paths", "Critiquing", and "Synthesizing" status messages sequentially.

**Step 3: Verify output quality**
Confirm that the final answer reflects the synthesis of the critiques.
