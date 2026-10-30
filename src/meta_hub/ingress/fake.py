"""Scripted fake event source (task 2.2).

Lets the whole agent loop run end-to-end before any real channel exists: give
it a list of events with delays and it replays them on a timeline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Sequence

from ..events import Event
from .base import EventAdapter, IngressError


@dataclass
class ScriptedEntry:
    delay: float
    event: Event


class ScriptedAdapter(EventAdapter):
    """Replays ``(delay, event)`` pairs; ``connect`` restarts the script."""

    name = "scripted"

    def __init__(self, script: Sequence[ScriptedEntry | tuple[float, Event]], *,
                 loop: bool = False,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.script = [
            item if isinstance(item, ScriptedEntry) else ScriptedEntry(*item)
            for item in script
        ]
        self.loop = loop
        self._monotonic = monotonic
        self._index = 0
        self._due = 0.0
        self._connected = False

    @classmethod
    def from_events(cls, events: Iterable[Event], *, interval: float = 1.0,
                    loop: bool = False) -> "ScriptedAdapter":
        return cls([(interval, e) for e in events], loop=loop)

    def connect(self) -> None:
        self._index = 0
        first = self.script[0].delay if self.script else 0.0
        self._due = self._monotonic() + first
        self._connected = True

    def receive(self, timeout: float) -> Event | None:
        if not self._connected:
            raise IngressError("not connected")
        if self._index >= len(self.script):
            if not self.loop or not self.script:
                time.sleep(min(timeout, 0.05))
                return None
            self._index = 0
        entry = self.script[self._index]
        now = self._monotonic()
        if now < self._due:
            time.sleep(min(timeout, max(0.0, self._due - now)))
            return None
        self._index += 1
        self._due = self._monotonic() + (
            self.script[self._index].delay if self._index < len(self.script) else 0.0
        )
        return entry.event
    def heartbeat(self) -> None:
        pass

    def close(self) -> None:
        self._connected = False


class ListAdapter(EventAdapter):
    """Drains a fixed list, then raises: handy for reconnect tests."""

    name = "list"

    def __init__(self, events: Iterable[Event]) -> None:
        self._events = list(events)
        self._i = 0
        self.connected = 0

    def connect(self) -> None:
        self.connected += 1
        self._i = 0

    def receive(self, timeout: float) -> Event | None:
        if self._i >= len(self._events):
            raise IngressError("script exhausted")
        event = self._events[self._i]
        self._i += 1
        return event

    def heartbeat(self) -> None:
        pass

    def close(self) -> None:
        pass


def replay_events(events: Iterable[Event], *, speed: float = 1.0,
                  sleep: Callable[[float], None] = time.sleep) -> Iterator[Event]:
    """Yield events honoring the relative ``ts`` deltas (see ``base.replay``)."""
    from .base import replay
    return replay(events, speed=speed, sleep=sleep)
