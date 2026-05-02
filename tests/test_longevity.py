import pytest
from agent import estimate_tokens

@pytest.mark.parametrize("messages, expected", [
    ([{"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello, how are you?"}], 19),
    ([], 0),
    ([{"role": "user"}], 4),
    ([{"role": "user", "content": None}], 4),
    ([{"role": "user", "content": ""}], 4),
])
def test_token_estimation_robustness(messages, expected):
    assert estimate_tokens(messages) == expected

@pytest.mark.asyncio
async def test_summarize_history_trigger():
    from unittest.mock import patch, AsyncMock
    import agent
    
    # Mock inference_engine.run_inference
    # Note: we need to mock it where it's imported in agent.py or the module itself
    with patch("inference_engine.run_inference", new_callable=AsyncMock) as mock_inference:
        mock_inference.return_value = "Summary of the conversation."
        
        system_prompt = {"role": "system", "content": "You are a helpful assistant."}
        # Create enough messages to exceed 16000 tokens
        # Each message adds ~2500 tokens
        large_content = "x" * 10000 
        messages = [system_prompt] + [{"role": "user", "content": large_content}] * 8
        
        # Verify it triggers
        assert agent.estimate_tokens(messages) > 16000
        
        new_messages = await agent.summarize_history(messages)
        
        # Verify summarization occurred and merged
        assert len(new_messages) < len(messages)
        assert new_messages[0]["role"] == "system"
        assert system_prompt["content"] in new_messages[0]["content"]
        assert "[PERSISTENT SESSION CONTEXT: Summary of the conversation.]" in new_messages[0]["content"]
        assert mock_inference.called

@pytest.mark.asyncio
async def test_summarize_history_hard_limit():
    from unittest.mock import patch, AsyncMock
    import agent
    
    with patch("inference_engine.run_inference", new_callable=AsyncMock) as mock_inference:
        mock_inference.return_value = "Short summary."
        
        system_prompt = {"role": "system", "content": "System prompt."}
        # Create many large messages to exceed HARD_LIMIT even after summarization
        large_content = "y" * 10000 
        # 12 messages * 2500 tokens = 30000 tokens (exceeds 28000 HARD_LIMIT)
        messages = [system_prompt] + [{"role": "user", "content": large_content}] * 12
        
        new_messages = await agent.summarize_history(messages)
        
        # Verify tokens are under HARD_LIMIT
        assert agent.estimate_tokens(new_messages) <= 28000
        # Verify system prompt is still there
        assert new_messages[0]["role"] == "system"
        assert "System prompt." in new_messages[0]["content"]
        # Verify some messages were dropped
        # 12 messages -> summarized half (6) -> 6 keep + 1 system = 7
        # 7 * 2500 = 17500 < 28000. 
        # Wait, if midpoint is 6, we keep 6. 6 * 2500 = 15000. 
        # Let's use larger messages to force drop even after summary.
        
        large_content_v2 = "z" * 20000 # ~5000 tokens per message
        # 10 messages * 5000 = 50000
        messages_v2 = [system_prompt] + [{"role": "user", "content": large_content_v2}] * 10
        
        # summarization will summarize 5, keep 5.
        # 5 * 5000 = 25000. 25000 + system (~10) = 25010. 
        # This is under HARD_LIMIT (28000).
        
        # Let's use 12 messages.
        # summarize 6, keep 6. 6 * 5000 = 30000.
        # 30000 > 28000. Should drop at least one more message.
        messages_v3 = [system_prompt] + [{"role": "user", "content": large_content_v2}] * 12
        
        new_messages_v3 = await agent.summarize_history(messages_v3)
        assert agent.estimate_tokens(new_messages_v3) <= 28000
        assert new_messages_v3[0]["role"] == "system"
        # Since we kept 6 (30000 tokens) and HARD_LIMIT is 28000, 
        # it should have dropped one more message, leaving 5 non-system messages.
        assert len(new_messages_v3) <= 6 # 1 system + 5 user

@pytest.mark.asyncio
async def test_inference_watchdog_mechanism():
    import inference_engine
    from unittest.mock import patch, MagicMock
    import time

    # 1. Test that _stop_inference.set() stops handle_mlx_vlm_request loop
    with patch("inference_engine._mlx_vlm_stream_generate") as mock_stream, \
         patch("inference_engine.get_mlx_vlm_model", return_value=(MagicMock(), MagicMock())):
        
        # Mock a generator that yields tokens
        def mock_gen(*args, **kwargs):
            yield "a"
            yield "b"
            yield "c"
        mock_stream.side_effect = mock_gen
        
        # Pre-set the stop event
        inference_engine._stop_inference.set()
        
        result = inference_engine.handle_mlx_vlm_request("gemma4-e4b", [{"role": "user", "content": "test"}])
        # It should break immediately before appending any tokens
        assert result["choices"][0]["message"]["content"] == ""
        # Ensure it was cleared for next run in _inference_worker finally block
        # (Actually handle_mlx_vlm_request doesn't clear it, _inference_worker does)
        inference_engine._stop_inference.clear()

    # 2. Test that activity updates
    with patch("inference_engine._mlx_vlm_stream_generate") as mock_stream, \
         patch("inference_engine.get_mlx_vlm_model", return_value=(MagicMock(), MagicMock())):
        
        mock_stream.side_effect = lambda *args, **kwargs: ["token1"]
        
        old_activity = inference_engine._last_inference_activity
        time.sleep(0.1) # Ensure time moves
        inference_engine.handle_mlx_vlm_request("gemma4-e4b", [{"role": "user", "content": "test"}])
        
        assert inference_engine._last_inference_activity > old_activity
