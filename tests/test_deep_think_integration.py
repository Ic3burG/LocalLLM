import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from agent import react_loop_sse, sse_queues


@pytest.mark.asyncio
async def test_react_loop_sse_with_deep_think():
    task_id = "test-task"
    q = asyncio.Queue()
    sse_queues[task_id] = q
    messages = [
        {"role": "system", "content": "You are an assistant."},
        {"role": "user", "content": "What is 2+2?"},
    ]
    model_id = "test-model"

    # Mock run_deep_thinking_pipeline
    mock_reasoning = "2+2 is 4 because of math."

    # Mock run_inference for the main loop
    # We want it to finish quickly
    mock_response = "DONE: The answer is 4."

    with (
        patch("agent.run_deep_thinking_pipeline", new_callable=AsyncMock) as mock_dt,
        patch("agent.run_inference", new_callable=AsyncMock) as mock_inf,
    ):
        mock_dt.return_value = mock_reasoning
        mock_inf.return_value = mock_response

        # Run
        await react_loop_sse(task_id, messages, model_id, deep_think=True)

        # Verify run_deep_thinking_pipeline was called
        mock_dt.assert_called_once()

        # Verify message injection
        assert any(
            "<thought>\n2+2 is 4 because of math.\n</thought>" in m["content"]
            for m in messages
            if m["role"] == "user"
        )

        # Verify SSE events
        events = []
        while not q.empty():
            item = await q.get()
            if item is None:
                break
            events.append(json.loads(item))

        # Check for thinking event
        thinking_events = [e for e in events if e["type"] == "thinking"]
        assert len(thinking_events) >= 1
        assert thinking_events[0]["content"] == mock_reasoning

        # Check for done event
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert "The answer is 4" in done_events[0]["message"]
