"""Re-export of the shared event vocabulary.

The actual definitions live in the repo-root `event_types.py` so both the
bridge (which emits) and the CLI (which consumes) see the same shapes.
This module exists so CLI consumers can keep importing from
`localllm.events` without caring about where the spec lives."""

from event_types import (  # noqa: F401
    ConfirmRequestEvent,
    ConfirmResolvedEvent,
    DoneEvent,
    ErrorEvent,
    Event,
    ImageEvent,
    SourcesEvent,
    StatusEvent,
    StepEvent,
    ThinkingEvent,
    parse_event,
)
