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
