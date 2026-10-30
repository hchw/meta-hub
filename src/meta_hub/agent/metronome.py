"""Metronome + agent state machine (task 3.2).

One fixed tick drives the loop.  The states are deliberately few:

    IDLE --tick--> EVALUATING --plan--> SPEAKING --done--> IDLE
                        |                    |
                        +--do_nothing------> IDLE
                        +--error-----------> IDLE

An interrupt always lands back in IDLE.  Timing is injected so tests can run
the machine without sleeping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class AgentState(str, Enum):
    IDLE = "idle"
    EVALUATING = "evaluating"
    SPEAKING = "speaking"


class TransitionError(RuntimeError):
    pass


_ALLOWED: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {AgentState.EVALUATING, AgentState.SPEAKING},
    AgentState.EVALUATING: {AgentState.IDLE, AgentState.SPEAKING},
    AgentState.SPEAKING: {AgentState.IDLE, AgentState.EVALUATING},
}


@dataclass
class Metronome:
    interval: float = 1.0
    clock: Callable[[], float] = None  # type: ignore[assignment]
    state: AgentState = AgentState.IDLE
    last_tick: float | None = None
    history: list[tuple[float, AgentState, str]] = field(default_factory=list)
    on_transition: Callable[[AgentState, AgentState, str], None] | None = None

    def __post_init__(self) -> None:
        if self.clock is None:
            import time
            self.clock = time.monotonic
        if self.interval <= 0:
            raise ValueError("interval must be positive")
        if self.last_tick is None:
            self.last_tick = self.clock()

    # -- transitions ------------------------------------------------------
    def transition(self, target: AgentState, reason: str = "") -> None:
        if target == self.state:
            return
        if target not in _ALLOWED[self.state]:
            raise TransitionError(f"{self.state.value} -> {target.value} is not allowed")
        previous, self.state = self.state, target
        self.history.append((self.clock(), target, reason))
        if self.on_transition:
            self.on_transition(previous, target, reason)

    # -- ticks ------------------------------------------------------------
    def due(self, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        return now - (self.last_tick or 0.0) >= self.interval

    def tick(self, now: float | None = None) -> str:
        """Advance one beat; return the action the loop should take."""
        now = self.clock() if now is None else now
        if not self.due(now):
            return "wait"
        self.last_tick = now
        if self.state is AgentState.IDLE:
            self.transition(AgentState.EVALUATING, "tick")
            return "evaluate"
        if self.state is AgentState.EVALUATING:
            return "wait_model"
        return "wait_playback"

    # -- model / playback feedback ---------------------------------------
    def on_plan(self, *, has_actions: bool) -> None:
        if self.state is not AgentState.EVALUATING:
            raise TransitionError("on_plan requires EVALUATING")
        self.transition(AgentState.SPEAKING if has_actions else AgentState.IDLE,
                        "plan" if has_actions else "do_nothing")

    def on_model_error(self) -> None:
        if self.state is AgentState.EVALUATING:
            self.transition(AgentState.IDLE, "model_error")

    def on_playback_done(self) -> None:
        if self.state is not AgentState.SPEAKING:
            raise TransitionError("on_playback_done requires SPEAKING")
        self.transition(AgentState.IDLE, "playback_done")

    def on_interrupt(self) -> None:
        self.transition(AgentState.IDLE, "interrupt")

    def on_soft_interrupt(self) -> None:
        """Soft interrupts queue at the sentence boundary: state is unchanged."""
        if self.state is AgentState.SPEAKING:
            return
        raise TransitionError("soft interrupt only applies while SPEAKING")

    def run(self, max_ticks: int, *, should_evaluate: Callable[[], bool],
            on_evaluate: Callable[[], bool]) -> list[str]:
        """Tiny synchronous driver used by tests and the fake loop."""
        actions: list[str] = []
        for _ in range(max_ticks):
            action = self.tick()
            actions.append(action)
            if action == "evaluate":
                if should_evaluate():
                    self.on_plan(has_actions=on_evaluate())
            self.clock = self.clock  # keep mypy quiet
        return actions
