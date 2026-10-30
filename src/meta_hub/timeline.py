"""Timeline compiler and single-clock executor (design D5/D6, tasks 4.1-4.4).

A plan is an ordered list of tool calls.  The compiler turns it into three
tracks:

* **speech** — ``speak`` / ``wait`` are duration type: they advance the clock.
* **gesture** — overlays: a gesture at time *t* runs alongside speech, it does
  not push the next sentence later.
* **expression** — state type: stays active until the next change (or the end).

The executor plays the tracks against one sample clock.  Soft interrupts are
only observed at sentence boundaries; hard interrupts cancel immediately and
are idempotent.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .clock import SampleClock
from .agent.llm import Plan, ToolCall
from .motion.choreography import DanceProgram, parse_dance


class Speaker(Protocol):
    def speak(self, text: str, duration: float,
              cancelled: threading.Event) -> None: ...

    def wait(self, seconds: float, cancelled: threading.Event) -> None: ...

    def stop(self) -> None: ...


class GesturePlayer(Protocol):
    def play(self, name: str, intensity: float, duration: float) -> None: ...

    def cancel_all(self) -> None: ...


class ExpressionPlayer(Protocol):
    def set(self, name: str, weight: float) -> None: ...


class DancePlayer(Protocol):
    def play_dance(self, program: DanceProgram) -> None: ...

    def cancel_all(self) -> None: ...


@dataclass(frozen=True)
class SpeechItem:
    kind: str  # "speak" | "wait"
    start: float
    duration: float
    text: str = ""


@dataclass(frozen=True)
class GestureItem:
    start: float
    duration: float
    name: str
    intensity: float


@dataclass(frozen=True)
class ExpressionItem:
    start: float
    name: str
    weight: float


@dataclass(frozen=True)
class DanceItem:
    start: float
    program: DanceProgram


@dataclass
class Timeline:
    speech: list[SpeechItem] = field(default_factory=list)
    gestures: list[GestureItem] = field(default_factory=list)
    expressions: list[ExpressionItem] = field(default_factory=list)
    dances: list[DanceItem] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return sum(i.duration for i in self.speech)

    @property
    def speech_duration(self) -> float:
        return self.duration


def estimate_duration(text: str, *, chars_per_second: float = 5.0,
                      overhead: float = 0.25) -> float:
    return max(0.3, len(text.strip()) / max(0.1, chars_per_second) + overhead)


class TimelineCompiler:
    def __init__(self, duration_of: Callable[[str], float] = estimate_duration):
        self.duration_of = duration_of

    def compile(self, plan: Plan | list[ToolCall]) -> Timeline:
        calls = plan.calls if isinstance(plan, Plan) else plan
        timeline = Timeline()
        cursor = 0.0
        current_start = 0.0
        for call in calls:
            name, args = call.name, call.arguments
            if name == "speak":
                text = str(args["text"]).strip()
                duration = float(self.duration_of(text))
                current_start = cursor
                timeline.speech.append(SpeechItem("speak", cursor, duration, text))
                cursor += duration
            elif name == "wait":
                duration = float(args.get("seconds", 0.0))
                current_start = cursor
                timeline.speech.append(SpeechItem("wait", cursor, duration))
                cursor += duration
            elif name == "gesture":
                # Attach to the current (last) sentence: a gesture emitted after
                # ``speak`` must still overlay that sentence, not start after it.
                timeline.gestures.append(GestureItem(
                    start=current_start,
                    duration=float(args.get("duration", 1.0)),
                    name=str(args["name"]),
                    intensity=float(args.get("intensity", 0.6)),
                ))
            elif name == "set_expression":
                timeline.expressions.append(ExpressionItem(
                    start=current_start,
                    name=str(args["name"]),
                    weight=float(args.get("weight", 1.0)),
                ))
            elif name == "choreograph":
                raw = args.get("program", args)
                timeline.dances.append(DanceItem(
                    start=current_start, program=parse_dance(raw)))
            elif name == "do_nothing":
                continue
            else:  # validated upstream; keep the compiler honest anyway
                raise ValueError(f"unknown tool in plan: {name}")
        return timeline


@dataclass
class PlayResult:
    completed: bool = False
    played_seconds: float = 0.0
    soft_reason: str | None = None
    hard_event: object | None = None
    hard_cancels: int = 0

    @property
    def interrupted(self) -> bool:
        return self.soft_reason is not None or self.hard_event is not None


class TimelineExecutor:
    """Plays a timeline; interrupt requests may come from another thread."""

    def __init__(self, speaker: Speaker, gestures: GesturePlayer,
                 expressions: ExpressionPlayer, *,
                 dances: DancePlayer | None = None,
                 clock_factory: Callable[[], SampleClock] = lambda: SampleClock(16000),
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.speaker = speaker
        self.gestures = gestures
        self.expressions = expressions
        self.dances = dances or (gestures if hasattr(gestures, "play_dance") else None)
        self.clock_factory = clock_factory
        self._sleep = sleep
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._hard_event: object | None = None
        self._soft_reason: str | None = None
        self._hard_cancels = 0

    # -- interrupt requests (thread-safe) --------------------------------
    def request_soft(self, reason: str = "event") -> None:
        with self._lock:
            self._soft_reason = reason

    def request_hard(self, event: object = None) -> None:
        with self._lock:
            first = self._hard_event is None
            self._hard_event = event if event is not None else "hard"
            if first:
                self._hard_cancels += 1
        self._cancelled.set()
        # Cross-boundary cancel: stop audio, stop frames, reset to neutral.
        # All three are idempotent by construction.
        try:
            self.speaker.stop()
        finally:
            try:
                self.gestures.cancel_all()
            finally:
                self.expressions.set("neutral", 1.0)

    def reset(self) -> None:
        self._cancelled.clear()
        self._hard_event = None
        self._soft_reason = None

    @property
    def hard_cancels(self) -> int:
        return self._hard_cancels

    # -- playback ---------------------------------------------------------
    def play(self, timeline: Timeline) -> PlayResult:
        prepare = getattr(self.speaker, "prepare", None)
        if prepare is not None:
            prepare(timeline)
        self.reset()
        result = PlayResult()
        pending_soft = False
        expression = ("neutral", 1.0)
        self.expressions.set(*expression)
        if not timeline.speech:
            # Dance/gesture-only plan: start overlays and leave them running.
            self._start_overlays(timeline, 0.0)
            result.completed = True
            return result
        for item in timeline.speech:
            if self._hard_event is not None:
                return self._finish(result, hard=True)
            if pending_soft:
                result.soft_reason = self._soft_reason
                return result
            self._start_overlays(timeline, item.start)
            if item.kind == "wait":
                self.speaker.wait(item.duration, self._cancelled)
            else:
                self.speaker.speak(item.text, item.duration, self._cancelled)
            result.played_seconds += item.duration
            if self._hard_event is not None:
                return self._finish(result, hard=True)
            # Boundary: soft interrupt lands here, after the sentence finished.
            pending_soft = self._soft_reason is not None
            for expr in [e for e in timeline.expressions if e.start == item.start]:
                expression = (expr.name, expr.weight)
        # Apply expressions that were scheduled at the very end / after speech.
        for expr in timeline.expressions:
            if expr.start >= timeline.duration:
                self.expressions.set(expr.name, expr.weight)
                expression = (expr.name, expr.weight)
        if pending_soft:
            result.soft_reason = self._soft_reason
            return result
        result.completed = True
        self.expressions.set("neutral", 1.0)
        return result

    def _start_overlays(self, timeline: Timeline, start: float) -> None:
        for gesture in timeline.gestures:
            if abs(gesture.start - start) < 1e-9:
                self.gestures.play(gesture.name, gesture.intensity, gesture.duration)
        for expr in timeline.expressions:
            if abs(expr.start - start) < 1e-9:
                self.expressions.set(expr.name, expr.weight)
        if self.dances is not None:
            for dance in timeline.dances:
                if abs(dance.start - start) < 1e-9:
                    self.dances.play_dance(dance.program)

    def _finish(self, result: PlayResult, *, hard: bool) -> PlayResult:
        result.completed = False
        result.soft_reason = None
        result.hard_event = self._hard_event
        result.hard_cancels = self._hard_cancels
        if hard:
            self.expressions.set("neutral", 1.0)
        return result

    def play_plan(self, plan: Plan,
                  compiler: TimelineCompiler | None = None) -> PlayResult:
        compiler = compiler or TimelineCompiler()
        return self.play(compiler.compile(plan))
