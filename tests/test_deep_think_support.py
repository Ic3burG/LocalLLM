import pytest
from pydantic import ValidationError
from agent import AgentRequest, react_loop_sse
import inspect

def test_agent_request_deep_think_default():
    req = AgentRequest(prompt="hi")
    assert req.deep_think is False

def test_agent_request_deep_think_true():
    req = AgentRequest(prompt="hi", deep_think=True)
    assert req.deep_think is True

def test_react_loop_sse_signature():
    sig = inspect.signature(react_loop_sse)
    assert "deep_think" in sig.parameters
    assert sig.parameters["deep_think"].default is False
