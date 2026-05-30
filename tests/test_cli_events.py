import json

import pytest

from localllm.events import (
    ConfirmRequestEvent,
    ConfirmResolvedEvent,
    DoneEvent,
    ErrorEvent,
    ImageEvent,
    SourcesEvent,
    StatusEvent,
    StepEvent,
    ThinkingEvent,
    parse_event,
)


@pytest.mark.parametrize(
    "raw,expected_type,expected_attrs",
    [
        (
            {"type": "status", "message": "Loading…"},
            StatusEvent,
            {"message": "Loading…"},
        ),
        (
            {"type": "thinking", "content": "Let me think"},
            ThinkingEvent,
            {"content": "Let me think"},
        ),
        (
            {
                "type": "step",
                "tool": "read_file",
                "args": {"0": "README.md"},
                "result": "hello",
                "elapsed_ms": 42,
            },
            StepEvent,
            {"tool": "read_file", "elapsed_ms": 42},
        ),
        (
            {
                "type": "confirm_request",
                "task_id": "t1",
                "tool": "shell",
                "args": {"0": "ls"},
            },
            ConfirmRequestEvent,
            {"task_id": "t1", "tool": "shell"},
        ),
        (
            {"type": "confirm_resolved", "approved": True},
            ConfirmResolvedEvent,
            {"approved": True},
        ),
        ({"type": "done", "message": "all done"}, DoneEvent, {"message": "all done"}),
        ({"type": "error", "message": "oops"}, ErrorEvent, {"message": "oops"}),
        (
            {"type": "sources", "items": [{"url": "https://x", "kind": "web"}]},
            SourcesEvent,
            {"items": [{"url": "https://x", "kind": "web"}]},
        ),
        (
            {
                "type": "image",
                "image_b64": "AAA",
                "width": 512,
                "height": 512,
                "steps": 4,
                "elapsed_ms": 100,
                "prompt": "cat",
                "size": "512x512",
            },
            ImageEvent,
            {"width": 512, "height": 512},
        ),
    ],
)
def test_parse_event_roundtrip(raw, expected_type, expected_attrs):
    event = parse_event(json.dumps(raw))
    assert isinstance(event, expected_type)
    for key, val in expected_attrs.items():
        assert getattr(event, key) == val


def test_parse_event_unknown_type_returns_none():
    assert parse_event(json.dumps({"type": "mystery"})) is None


def test_parse_event_malformed_json_returns_none():
    assert parse_event("not json") is None
