"""Replaceable ingress adapters (design D1/D2, tasks 2.2/2.3/7.x).

The contract between "where events come from" and "the agent" is deliberately
tiny:

* every adapter is a source of :class:`~meta_hub.events.Event`
* :class:`ReconnectingIngress` owns liveness: heartbeat, reconnect with
  backoff, and deduplication by ``event_id``.

Because all of that lives here, swapping a capture sidecar for an official
companion-plugin bridge never touches the agent or the executor.
"""
from __future__ import annotations

import json
import socket
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Protocol

from ..events import Event


class IngressError(RuntimeError):
    """The transport failed; the reconnect loop will try again."""


@dataclass
class IngressStats:
    received: int = 0
    delivered: int = 0
    duplicates: int = 0
    reconnects: int = 0
    heartbeats: int = 0


class EventAdapter(Protocol):
    """Transport-level source of events."""

    name: str

    def connect(self) -> None: ...

    def receive(self, timeout: float) -> Event | None:
        """Return the next event, ``None`` on timeout, raise on disconnect."""

    def heartbeat(self) -> None: ...

    def close(self) -> None: ...


class ReconnectingIngress:
    """Turns a flaky adapter into a reliable, deduplicated event stream."""

    def __init__(
        self,
        adapter: EventAdapter,
        *,
        dedup_size: int = 4096,
        reconnect_min: float = 0.5,
        reconnect_max: float = 30.0,
        heartbeat_interval: float = 5.0,
        poll_timeout: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.dedup_size = max(1, dedup_size)
        self.reconnect_min = reconnect_min
        self.reconnect_max = max(reconnect_min, reconnect_max)
        self.heartbeat_interval = heartbeat_interval
        self.poll_timeout = poll_timeout
        self._sleep = sleep
        self._monotonic = monotonic
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._connected = False
        self._last_heartbeat = -1e9
        self.stats = IngressStats()
        self._stopped = False

    # -- public -----------------------------------------------------------
    def stream(self) -> Iterator[Event]:
        """Yield events forever, reconnecting as needed."""
        backoff = self.reconnect_min
        while not self._stopped:
            try:
                if not self._connected:
                    self.adapter.connect()
                    self._connected = True
                    self._last_heartbeat = self._monotonic()
                    backoff = self.reconnect_min
                self._heartbeat_if_due()
                event = self.adapter.receive(self.poll_timeout)
                if event is None:
                    continue
                self.stats.received += 1
                if self._is_duplicate(event):
                    self.stats.duplicates += 1
                    continue
                self.stats.delivered += 1
                yield event
            except (IngressError, OSError, ValueError, json.JSONDecodeError):
                self._disconnect()
                self.stats.reconnects += 1
                self._sleep(backoff)
                backoff = min(self.reconnect_max, backoff * 2)

    def run(self, on_event: Callable[[Event], None],
            max_events: int | None = None) -> IngressStats:
        n = 0
        for event in self.stream():
            on_event(event)
            n += 1
            if max_events is not None and n >= max_events:
                break
        return self.stats

    def stop(self) -> None:
        self._stopped = True
        self._disconnect()

    # -- internals --------------------------------------------------------
    def _disconnect(self) -> None:
        if self._connected:
            try:
                self.adapter.close()
            except Exception:
                pass
        self._connected = False

    def _heartbeat_if_due(self) -> None:
        if self.heartbeat_interval <= 0:
            return
        now = self._monotonic()
        if now - self._last_heartbeat >= self.heartbeat_interval:
            self.adapter.heartbeat()
            self.stats.heartbeats += 1
            self._last_heartbeat = now

    def _is_duplicate(self, event: Event) -> bool:
        if event.event_id in self._seen:
            self._seen.move_to_end(event.event_id)
            return True
        self._seen[event.event_id] = None
        while len(self._seen) > self.dedup_size:
            self._seen.popitem(last=False)
        return False


class TcpJsonAdapter:
    """Newline-delimited JSON over a local TCP socket.

    Used by the local capture sidecar (development) and by the companion
    bridge (official channel).  The wire format is intentionally boring:
    one JSON object per line, in and out.
    """

    name = "tcp-json"

    def __init__(self, host: str = "127.0.0.1", port: int = 7711,
                 connect_timeout: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._buf = b""

    def connect(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=self.connect_timeout)
            sock.settimeout(0.2)
        except OSError as exc:
            raise IngressError(f"cannot connect {self.host}:{self.port}: {exc}") from exc
        self._sock = sock
        self._buf = b""

    def receive(self, timeout: float) -> Event | None:
        if self._sock is None:
            raise IngressError("not connected")
        deadline = time.monotonic() + timeout
        while True:
            line, self._buf = self._split_line(self._buf)
            if line is not None:
                if not line.strip():
                    continue
                return Event.from_dict(json.loads(line))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._sock.settimeout(min(0.2, remaining))
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                continue
            except OSError as exc:
                raise IngressError(f"receive failed: {exc}") from exc
            if not chunk:
                raise IngressError("peer closed the connection")
            self._buf += chunk

    def heartbeat(self) -> None:
        self._send({"type": "heartbeat", "ts": time.time()})

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def send_event(self, event: Event) -> None:
        """For tests/bridges that push events over the same wire."""
        self._send(event.to_dict())

    def _send(self, payload: dict) -> None:
        if self._sock is None:
            raise IngressError("not connected")
        try:
            self._sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError as exc:
            raise IngressError(f"send failed: {exc}") from exc

    @staticmethod
    def _split_line(buf: bytes) -> tuple[str | None, bytes]:
        idx = buf.find(b"\n")
        if idx < 0:
            return None, buf
        return buf[:idx].decode("utf-8", errors="replace"), buf[idx + 1:]


def replay(events: Iterable[Event], *, speed: float = 1.0,
           clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep) -> Iterator[Event]:
    """Yield events on their relative timeline (differences between ``ts``).

    ``speed`` > 1 compresses the timeline, < 1 stretches it.  Events whose
    ``ts`` is out of order are emitted immediately (never go backwards).
    """
    base_ts: float | None = None
    start = clock()
    for event in events:
        if base_ts is None:
            base_ts = event.ts
        due = start + max(0.0, event.ts - base_ts) / max(1e-9, speed)
        now = clock()
        if due > now:
            sleep(due - now)
        yield event
