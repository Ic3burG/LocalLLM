"""Single source of truth for the agent SSE event vocabulary.

Both the bridge (agent.py) and the CLI (localllm/events.py) import from here.
The web frontend (gemma-web/index.html) consumes these by name — its
renderer is documented to mirror this module.

Each event type has:
- A frozen dataclass for typed parsing (CLI side).
- A `mk_<type>(...)` builder that returns the canonical dict shape
  (bridge side). Builders are the only place dict field names live, so
  renames stay coherent across the wire.
- parse_event(json_str) turns an SSE payload into a typed event, or None
  when the type is unknown / the payload is malformed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Union

logger = logging.getLogger(__name__)


# ----- dataclasses (typed consumer side) -----------------------------------


@dataclass(frozen=True)
class StatusEvent:
    message: str


@dataclass(frozen=True)
class ThinkingEvent:
    content: str


@dataclass(frozen=True)
class StepEvent:
    tool: str
    args: dict[str, Any]
    result: Any
    elapsed_ms: int


@dataclass(frozen=True)
class ConfirmRequestEvent:
    task_id: str
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ConfirmResolvedEvent:
    approved: bool


@dataclass(frozen=True)
class DoneEvent:
    message: str


@dataclass(frozen=True)
class ErrorEvent:
    message: str


@dataclass(frozen=True)
class SourcesEvent:
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ImageEvent:
    image_b64: str
    width: int
    height: int
    steps: int
    elapsed_ms: int
    prompt: str
    size: str


Event = Union[
    StatusEvent,
    ThinkingEvent,
    StepEvent,
    ConfirmRequestEvent,
    ConfirmResolvedEvent,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    ImageEvent,
]


# ----- builder functions (producer side) -----------------------------------
#
# Bridge call sites use these to construct event dicts instead of raw {...}
# literals. That keeps field names in exactly one place; a rename here
# propagates to every emitter without manual touch.


def mk_status(message: str) -> dict[str, Any]:
    return {"type": "status", "message": message}


def mk_thinking(content: str) -> dict[str, Any]:
    return {"type": "thinking", "content": content}


def mk_step(
    tool: str, args: dict[str, Any], result: Any, elapsed_ms: int
) -> dict[str, Any]:
    return {
        "type": "step",
        "tool": tool,
        "args": args,
        "result": result,
        "elapsed_ms": elapsed_ms,
    }


def mk_confirm_request(task_id: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "confirm_request",
        "task_id": task_id,
        "tool": tool,
        "args": args,
    }


def mk_confirm_resolved(approved: bool) -> dict[str, Any]:
    return {"type": "confirm_resolved", "approved": bool(approved)}


def mk_done(message: str) -> dict[str, Any]:
    return {"type": "done", "message": message}


def mk_error(message: str) -> dict[str, Any]:
    return {"type": "error", "message": message}


def mk_sources(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "sources", "items": items}


def mk_image(
    image_b64: str,
    width: int,
    height: int,
    steps: int,
    elapsed_ms: int,
    prompt: str,
    size: str,
) -> dict[str, Any]:
    return {
        "type": "image",
        "image_b64": image_b64,
        "width": width,
        "height": height,
        "steps": steps,
        "elapsed_ms": elapsed_ms,
        "prompt": prompt,
        "size": size,
    }


# ----- parse_event ---------------------------------------------------------


def parse_event(raw: str) -> Event | None:
    """Parse a raw JSON SSE payload into a typed event, or None if unrecognized."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("malformed event JSON: %r", raw)
        return None
    kind = data.get("type")
    if kind == "status":
        return StatusEvent(message=data.get("message", ""))
    if kind == "thinking":
        return ThinkingEvent(content=data.get("content", ""))
    if kind == "step":
        return StepEvent(
            tool=data.get("tool", ""),
            args=data.get("args") or {},
            result=data.get("result"),
            elapsed_ms=int(data.get("elapsed_ms", 0)),
        )
    if kind == "confirm_request":
        return ConfirmRequestEvent(
            task_id=data.get("task_id", ""),
            tool=data.get("tool", ""),
            args=data.get("args") or {},
        )
    if kind == "confirm_resolved":
        return ConfirmResolvedEvent(approved=bool(data.get("approved")))
    if kind == "done":
        return DoneEvent(message=data.get("message", ""))
    if kind == "error":
        return ErrorEvent(message=data.get("message", ""))
    if kind == "sources":
        return SourcesEvent(items=list(data.get("items") or []))
    if kind == "image":
        return ImageEvent(
            image_b64=data.get("image_b64", ""),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            steps=int(data.get("steps", 0)),
            elapsed_ms=int(data.get("elapsed_ms", 0)),
            prompt=data.get("prompt", ""),
            size=data.get("size", ""),
        )
    logger.debug("unknown event type: %r", kind)
    return None
