import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from agent import run_deep_thinking_pipeline


@pytest.mark.asyncio
async def test_run_deep_thinking_pipeline():
    # Setup
    q = asyncio.Queue()
    messages = [{"role": "user", "content": "What is 2+2?"}]
    model_id = "test-model"

    # Mock run_inference
    # Stage 1: Diversify -> returns 3 paths
    # Stage 2: Critique -> returns critique
    # Stage 3: Synthesize -> returns final answer
    mock_responses = [
        "Path A: Add them. Path B: Use a calculator. Path C: Ask a friend.",
        "Path A is simple. Path B is overkill. Path C is slow. Scores: A: 10, B: 5, C: 2",
        "The best way is to add them: 2+2=4."
    ]

    with patch("agent.run_inference", new_callable=AsyncMock) as mock_inf:
        mock_inf.side_effect = mock_responses

        # Run
        result = await run_deep_thinking_pipeline(q, messages, model_id)

        # Verify result
        assert result == "The best way is to add them: 2+2=4."

        # Verify calls
        assert mock_inf.call_count == 3
        
        # Verify SSE events
        events = []
        while not q.empty():
            events.append(json.loads(await q.get()))
        
        assert len(events) == 3
        assert events[0]["message"] == "Deep Thinking: Exploring 3 reasoning paths…"
        assert events[1]["message"] == "Deep Thinking: Critiquing strategies…"
        assert events[2]["message"] == "Deep Thinking: Synthesizing final plan…"

        # Verify prompts
        # Stage 1 prompt
        args, _ = mock_inf.call_args_list[0]
        assert "Generate 3 distinct, high-level strategies" in args[0][0]["content"]
        assert "What is 2+2?" in args[0][0]["content"]

        # Stage 2 prompt
        args, _ = mock_inf.call_args_list[1]
        assert "Act as a critical reviewer" in args[0][2]["content"]
        assert mock_responses[0] in args[0][1]["content"]

        # Stage 3 prompt
        args, _ = mock_inf.call_args_list[2]
        assert "synthesize the absolute best solution" in args[0][4]["content"]
        assert mock_responses[1] in args[0][3]["content"]
