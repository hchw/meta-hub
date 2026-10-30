"""Agent loop wiring: ingress -> gatekeeper -> LLM -> timeline (design D3-D6).

``LiveAgent`` is the single place where the pieces meet.  Ingress threads call
``submit``; the metronome thread calls ``step``.  Keeping the schedule
explicit makes the loop deterministic and testable without a live room.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .agent.context import ContextAssembler
from .agent.gatekeeper import Decision, Gatekeeper
from .agent.llm import LLMClient, Plan
from .agent.metronome import AgentState, Metronome
from .character import CharacterMemory
from .events import Event
from .timeline import PlayResult, TimelineCompiler, TimelineExecutor


@dataclass
class StepResult:
    action: str
    decision: Decision | None = None
    plan: Plan | None = None
    playback: PlayResult | None = None
    error: str | None = None


@dataclass
class LiveAgent:
    gatekeeper: Gatekeeper
    metronome: Metronome
    assembler: ContextAssembler
    llm: LLMClient
    executor: TimelineExecutor
    memory: CharacterMemory | None = None
    compiler: TimelineCompiler = field(default_factory=TimelineCompiler)
    clock: Callable[[], float] = time.monotonic
    pending: list[Event] = field(default_factory=list)
    last_result: StepResult | None = None

    # -- ingress side -----------------------------------------------------
    def submit(self, event: Event) -> None:
        self.pending.append(event)
        self.assembler.observe(event)
        if self.memory is not None:
            self.memory.observe(event)
        if event.is_high_value(self.gatekeeper.config.hard_interrupt_gift_value):
            self.executor.request_hard(event)
        elif self.metronome.state is AgentState.SPEAKING:
            self.executor.request_soft(event.kind.value)

    # -- metronome side ---------------------------------------------------
    def step(self, now: float | None = None) -> StepResult:
        now = self.clock() if now is None else now
        action = self.metronome.tick(now)
        if action != "evaluate":
            return StepResult(action)
        decision = self.gatekeeper.evaluate(self.pending, now)
        if not decision.allowed:
            if self.metronome.state is AgentState.EVALUATING:
                self.metronome.transition(AgentState.IDLE, decision.reason)
            result = StepResult("denied", decision=decision)
            self.last_result = result
            return result

        trigger = list(decision.trigger or [])
        if trigger:
            for event in trigger:
                if event in self.pending:
                    self.pending.remove(event)
            self.pending = self.pending[-50:]
        context = self.assembler.assemble(decision.trigger_reason or decision.reason,
                                          trigger)
        plan = self.llm.complete(context.system, context.messages)
        if plan.error:
            self.metronome.on_model_error()
            self.gatekeeper.record_do_nothing(now)
            result = StepResult("model_error", decision=decision, plan=plan,
                                error=plan.error)
            self.last_result = result
            return result
        if not plan.has_actions:
            self.metronome.on_plan(has_actions=False)
            self.gatekeeper.record_do_nothing(now)
            result = StepResult("do_nothing", decision=decision, plan=plan)
            self.last_result = result
            return result

        self.metronome.on_plan(has_actions=True)
        timeline = self.compiler.compile(plan)
        for item in timeline.speech:
            if item.kind == "speak":
                self.assembler.note_utterance(item.text)
                if self.memory is not None:
                    self.memory.note_utterance(item.text)
        playback = self.executor.play(timeline)
        self.gatekeeper.record_spoken(proactive=decision.proactive,
                                      now=self.clock())
        if playback.hard_event is not None:
            self.metronome.on_interrupt()
        else:
            self.metronome.on_playback_done()
        result = StepResult("spoke", decision=decision, plan=plan,
                            playback=playback)
        self.last_result = result
        return result

    def drain(self, max_steps: int = 1,
              interval: float = 0.0,
              sleep: Callable[[float], None] = time.sleep) -> list[StepResult]:
        """Convenience for scripts/tests: run a few beats."""
        results = []
        for _ in range(max_steps):
            results.append(self.step())
            if interval:
                sleep(interval)
        return results
