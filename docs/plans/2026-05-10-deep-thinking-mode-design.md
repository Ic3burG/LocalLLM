# Deep Thinking Mode Design — Gemma 4 Local AI Suite

**Date:** 2026-05-10  
**Status:** Approved

---

## Overview

Implement a "Deep Thinking" mode that enhances model reasoning quality through a multi-stage pipeline combining Tree of Thought (ToT), Self-Correction, and Synthesis. This mode trades inference time for higher accuracy and robustness in complex problem-solving.

---

## Pipeline Architecture: "The Council of Three"

When Deep Thinking is enabled, the system executes three sequential inference passes before entering the standard ReAct agent loop or returning a final answer.

### Stage 1: Diversify (Tree of Thought)
- **Goal:** Explore multiple mental models for the problem.
- **Action:** Ask the model to generate 3 distinct, high-level strategies (Path A, B, and C).
- **Inference Call:** `run_inference` with a diversification prompt.

### Stage 2: Critique & Score (Self-Correction)
- **Goal:** Identify hidden flaws in the generated strategies.
- **Action:** Ask the model to act as a harsh critic for its own paths, identifying edge cases and assigning a robustness score.
- **Inference Call:** `run_inference` providing the output of Stage 1.

### Stage 3: Synthesize (Extended CoT)
- **Goal:** Merge the best elements into a single robust plan.
- **Action:** Generate a final "master reasoning" block that addresses the critiques from Stage 2.
- **Inference Call:** `run_inference` providing the full history of the "Council".

---

## System Integration

### Backend (`agent.py` & `gemma_bridge.py`)
- **API Change:** Add `deep_think: bool` to the `AgentRequest` pydantic model.
- **Logic:** Implement `run_deep_thinking_pipeline(messages, model_id)` in `agent.py`.
- **SSE Updates:** Push `type: "thinking"` events for each stage (e.g., "Deep Thinking: Exploring paths...", "Deep Thinking: Critiquing strategies...") to keep the user informed during the long wait.
- **Agent Loop:** The final synthesized reasoning is injected as the initial `thought` in the ReAct loop.

### Frontend (`index.html`)
- **Toggle UI:** Add a "Deep Think" toggle switch/icon next to the model selector.
- **State Management:** Include `deep_think` state in the chat request payload.
- **Visuals:** Enhance the existing thinking indicator to show specific sub-stages of deep thinking.

---

## Performance Considerations

- **Latency:** Deep Thinking will take ~3x longer than standard inference.
- **VRAM:** No extra VRAM usage, as calls are sequential on the existing MLX worker thread.
- **Context:** The synthesis pass will have a larger context due to previous reasoning steps; `summarize_history` will manage this if it exceeds limits.

---

## Success Criteria

1.  User can toggle Deep Thinking mode in the UI.
2.  The UI displays live progress updates for each of the 3 stages.
3.  The final answer/agent actions are guided by the synthesized "Council" results.
4.  Standard chat remains unaffected when the toggle is off.
