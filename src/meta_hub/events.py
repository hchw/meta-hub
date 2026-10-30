"""Unified livestream event contract (design D1/D2, task 2.1).

Every ingress adapter — local capture, companion plugin, or the scripted fake
source — converts its native payloads into :class:`Event`.  The agent and the
executor only ever see this structure, so swapping the source never changes
downstream code.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    """The interaction types the agent understands."""

    COMMENT = "comment"
    GIFT = "gift"
    LIKE = "like"
    ENTER = "enter"
    FANSCLUB = "fansclub"
    FOLLOW = "follow"


class EventError(ValueError):
    """Malformed event payload."""


# Priority used by the gatekeeper for event ordering (higher = more urgent).
DEFAULT_PRIORITY: dict[str, int] = {
    EventKind.GIFT.value: 90,
    EventKind.FOLLOW.value: 70,
    EventKind.FANSCLUB.value: 60,
    EventKind.COMMENT.value: 50,
    EventKind.ENTER.value: 30,
    EventKind.LIKE.value: 20,
}


@dataclass(frozen=True)
class Event:
    """One normalized interaction.

    ``event_id`` is the deduplication key.  Adapters should use the platform's
    own id when available; otherwise a deterministic id is synthesized so a
    re-delivered payload is still collapsed by the ingress client.
    """

    kind: EventKind
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)
    viewer_id: str = ""
    viewer_name: str = ""
    text: str = ""
    gift_id: str = ""
    gift_name: str = ""
    gift_count: int = 0
    gift_value: int = 0
    direction: str = ""  # follow / unfollow
    reason: str = ""  # fansclub change reason
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EventKind):
            try:
                object.__setattr__(self, "kind", EventKind(str(self.kind)))
            except ValueError as exc:
                raise EventError(f"unknown event kind: {self.kind!r}") from exc
        if not self.event_id:
            raise EventError("event_id is required")
        if self.kind is EventKind.COMMENT and not isinstance(self.text, str):
            raise EventError("comment.text must be a string")
        if self.kind is EventKind.GIFT and self.gift_count < 0:
            raise EventError("gift.gift_count must be >= 0")

    @property
    def priority(self) -> int:
        base = DEFAULT_PRIORITY[self.kind.value]
        if self.kind is EventKind.GIFT:
            # A bigger gift is more urgent, within the gift band.
            return min(99, base + min(9, self.gift_value // 100))
        return base

    def is_high_value(self, min_value: int) -> bool:
        return self.kind is EventKind.GIFT and self.gift_value >= min_value

    # -- constructors -----------------------------------------------------
    @classmethod
    def comment(cls, viewer_id: str, text: str, *, viewer_name: str = "",
                event_id: str | None = None, ts: float | None = None,
                raw: dict[str, Any] | None = None) -> "Event":
        return cls(EventKind.COMMENT, event_id=event_id or uuid.uuid4().hex,
                   ts=time.time() if ts is None else ts, viewer_id=viewer_id,
                   viewer_name=viewer_name or viewer_id, text=text,
                   raw=raw or {})

    @classmethod
    def gift(cls, viewer_id: str, gift_id: str, count: int = 1, *,
             viewer_name: str = "", gift_name: str = "", value: int = 0,
             event_id: str | None = None, ts: float | None = None,
             raw: dict[str, Any] | None = None) -> "Event":
        return cls(EventKind.GIFT, event_id=event_id or uuid.uuid4().hex,
                   ts=time.time() if ts is None else ts, viewer_id=viewer_id,
                   viewer_name=viewer_name or viewer_id, gift_id=gift_id,
                   gift_name=gift_name or gift_id, gift_count=count,
                   gift_value=value, raw=raw or {})

    @classmethod
    def like(cls, viewer_id: str, count: int = 1, *, viewer_name: str = "",
             event_id: str | None = None, ts: float | None = None,
             raw: dict[str, Any] | None = None) -> "Event":
        return cls(EventKind.LIKE, event_id=event_id or uuid.uuid4().hex,
                   ts=time.time() if ts is None else ts, viewer_id=viewer_id,
                   viewer_name=viewer_name or viewer_id, gift_count=count,
                   raw=raw or {})

    @classmethod
    def enter(cls, viewer_id: str, *, viewer_name: str = "",
              event_id: str | None = None, ts: float | None = None,
              raw: dict[str, Any] | None = None) -> "Event":
        return cls(EventKind.ENTER, event_id=event_id or uuid.uuid4().hex,
                   ts=time.time() if ts is None else ts, viewer_id=viewer_id,
                   viewer_name=viewer_name or viewer_id, raw=raw or {})

    @classmethod
    def fansclub(cls, viewer_id: str, reason: str, *, viewer_name: str = "",
                 event_id: str | None = None, ts: float | None = None,
                 raw: dict[str, Any] | None = None) -> "Event":
        return cls(EventKind.FANSCLUB, event_id=event_id or uuid.uuid4().hex,
                   ts=time.time() if ts is None else ts, viewer_id=viewer_id,
                   viewer_name=viewer_name or viewer_id, reason=reason,
                   raw=raw or {})

    @classmethod
    def follow(cls, viewer_id: str, direction: str = "follow", *,
               viewer_name: str = "", event_id: str | None = None,
               ts: float | None = None, raw: dict[str, Any] | None = None) -> "Event":
        return cls(EventKind.FOLLOW, event_id=event_id or uuid.uuid4().hex,
                   ts=time.time() if ts is None else ts, viewer_id=viewer_id,
                   viewer_name=viewer_name or viewer_id, direction=direction,
                   raw=raw or {})

    # -- serialization ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "event_id": self.event_id,
            "ts": self.ts,
            "viewer_id": self.viewer_id,
            "viewer_name": self.viewer_name,
            "text": self.text,
            "gift_id": self.gift_id,
            "gift_name": self.gift_name,
            "gift_count": self.gift_count,
            "gift_value": self.gift_value,
            "direction": self.direction,
            "reason": self.reason,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        if not isinstance(data, dict):
            raise EventError(f"event must be an object, got {type(data).__name__}")
        try:
            kind = EventKind(data.get("kind", ""))
        except ValueError as exc:
            raise EventError(f"unknown event kind: {data.get('kind')!r}") from exc
        return cls(
            kind=kind,
            event_id=str(data.get("event_id") or uuid.uuid4().hex),
            ts=float(data.get("ts", time.time())),
            viewer_id=str(data.get("viewer_id", "")),
            viewer_name=str(data.get("viewer_name", "")),
            text=str(data.get("text", "")),
            gift_id=str(data.get("gift_id", "")),
            gift_name=str(data.get("gift_name", "")),
            gift_count=int(data.get("gift_count", 0) or 0),
            gift_value=int(data.get("gift_value", 0) or 0),
            direction=str(data.get("direction", "")),
            reason=str(data.get("reason", "")),
            raw=dict(data.get("raw") or {}),
        )
