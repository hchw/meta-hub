from __future__ import annotations

import unittest

from meta_hub.agent.metronome import AgentState, Metronome, TransitionError


class MetronomeTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.m = Metronome(interval=1.0, clock=lambda: self.now)

    def test_fixed_tick_transitions(self):
        self.assertEqual(self.m.state, AgentState.IDLE)
        self.assertEqual(self.m.tick(), "wait")
        self.now += 1.0
        self.assertEqual(self.m.tick(), "evaluate")
        self.assertEqual(self.m.state, AgentState.EVALUATING)
        self.m.on_plan(has_actions=True)
        self.assertEqual(self.m.state, AgentState.SPEAKING)
        self.m.on_playback_done()
        self.assertEqual(self.m.state, AgentState.IDLE)

    def test_do_nothing_returns_to_idle(self):
        self.now += 1.0
        self.m.tick()
        self.m.on_plan(has_actions=False)
        self.assertEqual(self.m.state, AgentState.IDLE)

    def test_model_error_returns_to_idle(self):
        self.now += 1.0
        self.m.tick()
        self.m.on_model_error()
        self.assertEqual(self.m.state, AgentState.IDLE)

    def test_interrupt_returns_to_idle(self):
        self.now += 1.0
        self.m.tick()
        self.m.on_plan(has_actions=True)
        self.m.on_interrupt()
        self.assertEqual(self.m.state, AgentState.IDLE)

    def test_invalid_transition_is_rejected(self):
        with self.assertRaises(TransitionError):
            self.m.on_playback_done()
        with self.assertRaises(TransitionError):
            self.m.on_soft_interrupt()

    def test_history_records_transitions(self):
        self.now += 1.0
        self.m.tick()
        self.m.on_plan(has_actions=True)
        self.m.on_playback_done()
        self.assertEqual([h[1] for h in self.m.history],
                         [AgentState.EVALUATING, AgentState.SPEAKING, AgentState.IDLE])


if __name__ == "__main__":
    unittest.main()
