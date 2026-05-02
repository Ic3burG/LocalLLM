import pytest
from agent import estimate_tokens

def test_token_estimation():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"}
    ]
    tokens = estimate_tokens(messages)
    assert isinstance(tokens, int)
    assert tokens > 0
    
    # Optional: check specific heuristic value
    # system: len("You are a helpful assistant.") // 4 + 4 = 28 // 4 + 4 = 7 + 4 = 11
    # user: len("Hello, how are you?") // 4 + 4 = 19 // 4 + 4 = 4 + 4 = 8
    # Total: 19
    assert tokens == 19
