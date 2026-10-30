from __future__ import annotations

import unittest

from meta_hub.agent.context import ContextAssembler
from meta_hub.agent.gatekeeper import Gatekeeper, GatekeeperConfig
from meta_hub.agent.llm import LLMClient
from meta_hub.agent.metronome import AgentState, Metronome
from meta_hub.events import Event
from meta_hub.live import LiveAgent
from meta_hub.timeline import TimelineCompiler, TimelineExecutor


class Speaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text, duration, cancelled):
        self.spoken.append(text)

    def wait(self, seconds, cancelled):
        pass

    def stop(self):
        pass


class Gestures:
    def __init__(self):
        self.played = []

    def play(self, name, intensity, duration):
        self.played.append(name)

    def cancel_all(self):
        pass


class Expressions:
    def __init__(self):
        self.sets = []

    def set(self, name, weight):
        self.sets.append(name)


def tool(tool, **args):
    return {"function": {"name": tool, "arguments": args}}


class LiveAgentTest(unittest.TestCase):
    def build(self, tool_calls):
        self.now = 0.0
        self.speaker = Speaker()
        self.gestures = Gestures()
        self.expressions = Expressions()
        cfg = GatekeeperConfig(proactive_enabled=False, event_cooldown_seconds=0)
        gk = Gatekeeper(cfg, clock=lambda: self.now)
        metronome = Metronome(interval=1.0, clock=lambda: self.now)
        assembler = ContextAssembler("测试人设")
        llm = LLMClient("http://x", "k", "m",
                        transport=lambda messages, tools: {
                            "choices": [{"message": {"tool_calls": tool_calls}}]})
        executor = TimelineExecutor(self.speaker, self.gestures, self.expressions)
        return LiveAgent(gk, metronome, assembler, llm, executor,
                         compiler=TimelineCompiler(lambda t: 0.2),
                         clock=lambda: self.now)

    def test_event_triggers_speech_and_gesture(self):
        agent = self.build([tool("gesture", name="nod"), tool("speak", text="你好。")])
        agent.submit(Event.comment("u", "hi"))
        self.now = 1.0
        result = agent.step()
        self.assertEqual(result.action, "spoke")
        self.assertEqual(self.speaker.spoken, ["你好。"])
        self.assertEqual(self.gestures.played, ["nod"])
        self.assertEqual(agent.metronome.state, AgentState.IDLE)
        self.assertEqual(agent.gatekeeper.speaks_in_window, 1)
        self.assertEqual(list(agent.assembler.own_utterances), ["你好。"])

    def test_do_nothing_produces_no_sound_or_motion(self):
        agent = self.build([tool("do_nothing", reason="quiet")])
        agent.submit(Event.comment("u", "hi"))
        self.now = 1.0
        result = agent.step()
        self.assertEqual(result.action, "do_nothing")
        self.assertEqual(self.speaker.spoken, [])
        self.assertEqual(self.gestures.played, [])
        self.assertEqual(agent.metronome.state, AgentState.IDLE)

    def test_model_failure_is_isolated_and_recovers(self):
        calls = {"n": 0}

        def transport(messages, tools):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("slow")
            return {"choices": [{"message": {"tool_calls": [tool("speak", text="恢复了。")]}}]}

        self.now = 0.0
        speaker = Speaker()
        agent = LiveAgent(
            Gatekeeper(GatekeeperConfig(proactive_enabled=False, event_cooldown_seconds=0),
                       clock=lambda: self.now),
            Metronome(interval=1.0, clock=lambda: self.now),
            ContextAssembler("p"),
            LLMClient("http://x", "k", "m", transport=transport),
            TimelineExecutor(speaker, Gestures(), Expressions()),
            compiler=TimelineCompiler(lambda t: 0.2),
            clock=lambda: self.now,
        )
        agent.submit(Event.comment("u", "one"))
        self.now = 1.0
        first = agent.step()
        self.assertEqual(first.action, "model_error")
        self.assertEqual(agent.metronome.state, AgentState.IDLE)
        agent.submit(Event.comment("u", "two"))
        self.now = 2.0
        second = agent.step()
        self.assertEqual(second.action, "spoke")
        self.assertEqual(speaker.spoken, ["恢复了。"])

    def test_budget_denial_keeps_idle(self):
        agent = self.build([tool("speak", text="hi")])
        agent.gatekeeper.update_config({"budget_max_speaks": 0})
        agent.submit(Event.comment("u", "hi"))
        self.now = 1.0
        result = agent.step()
        self.assertEqual(result.action, "denied")
        self.assertEqual(result.decision.reason, "budget_exhausted")
        self.assertEqual(agent.metronome.state, AgentState.IDLE)
        self.assertEqual(self.speaker.spoken, [])


if __name__ == "__main__":
    unittest.main()
