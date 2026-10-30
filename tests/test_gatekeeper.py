from __future__ import annotations

import unittest

from meta_hub.agent.gatekeeper import ConfigError, Gatekeeper, GatekeeperConfig
from meta_hub.events import Event


class GatekeeperTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.config = GatekeeperConfig(
            proactive_enabled=True,
            cooldown_seconds=10.0,
            silence_threshold_seconds=25.0,
            budget_window_seconds=3600.0,
            budget_max_speaks=10,
            event_cooldown_seconds=2.0,
            min_event_priority=25,
            hard_interrupt_gift_value=500,
        )
        self.gk = Gatekeeper(self.config, clock=lambda: self.now)

    def test_proactive_allowed_when_cold(self):
        decision = self.gk.evaluate()
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.proactive)
        self.assertEqual(decision.reason, "proactive")

    def test_cooldown_rejects(self):
        self.gk.record_spoken(proactive=True, now=0)
        self.now = 5
        self.assertFalse(self.gk.evaluate().allowed)
        self.assertEqual(self.gk.evaluate().reason, "cooldown")

    def test_silence_threshold_rejects(self):
        self.gk.record_spoken(proactive=True, now=0)
        self.now = 30  # cooldown passed but 25*1.5=37.5 not reached
        decision = self.gk.evaluate()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "silence_threshold")

    def test_budget_exhausted(self):
        self.config.budget_max_speaks = 1
        self.gk.record_spoken(proactive=True, now=0)
        self.now = 100
        decision = self.gk.evaluate()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "budget_exhausted")

    def test_budget_rolls_over(self):
        self.config.budget_max_speaks = 1
        self.gk.record_spoken(proactive=True, now=0)
        self.now = 3601
        decision = self.gk.evaluate()
        self.assertTrue(decision.allowed)
        self.assertEqual(self.gk.speaks_in_window, 0)

    def test_disabled_proactivity(self):
        self.config.proactive_enabled = False
        decision = self.gk.evaluate()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "proactive_disabled")

    def test_low_priority_event_is_not_actionable(self):
        self.config.proactive_enabled = False
        decision = self.gk.evaluate([Event.like("u1", 10)])  # priority 20
        self.assertFalse(decision.allowed)

    def test_event_triggers_and_event_cooldown(self):
        decision = self.gk.evaluate([Event.comment("u1", "hi")])
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.proactive)
        self.assertEqual(decision.trigger_reason, "comment")
        self.gk.record_spoken(proactive=False, now=self.now)
        self.now = 1.0
        self.assertEqual(self.gk.evaluate([Event.comment("u2", "yo")]).reason,
                         "event_cooldown")

    def test_hard_interrupt_bypasses_budget(self):
        self.config.budget_max_speaks = 0
        decision = self.gk.evaluate([Event.gift("u", "castle", value=5000)])
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.hard_interrupt)
        self.assertEqual(decision.reason, "hard_interrupt")

    def test_config_change_takes_effect_immediately(self):
        self.gk.update_config({"budget_max_speaks": 0})
        self.assertEqual(self.gk.evaluate().reason, "budget_exhausted")
        self.gk.update_config({"budget_max_speaks": 5, "proactive_enabled": False})
        self.assertEqual(self.gk.evaluate().reason, "proactive_disabled")

    def test_config_validation(self):
        with self.assertRaises(ConfigError):
            GatekeeperConfig.from_dict({"nope": 1})
        with self.assertRaises(ConfigError):
            GatekeeperConfig.from_dict({"budget_max_speaks": "many"})

    def test_anti_self_excitation_over_an_hour(self):
        cfg = GatekeeperConfig(budget_max_speaks=5, budget_window_seconds=3600,
                               cooldown_seconds=5, silence_threshold_seconds=20)
        t = [0.0]
        gk = Gatekeeper(cfg, clock=lambda: t[0])
        speaks = 0
        while t[0] < 3600:
            decision = gk.evaluate(now=t[0])
            if decision.allowed:
                speaks += 1
                gk.record_spoken(proactive=decision.proactive, now=t[0])
            t[0] += 5
        self.assertLessEqual(speaks, cfg.budget_max_speaks)
        self.assertGreater(speaks, 0)

    def test_do_nothing_relaxes_silence_but_proactive_extends(self):
        base = self.gk.effective_silence_threshold
        for _ in range(5):
            self.gk.record_do_nothing()
        relaxed = self.gk.effective_silence_threshold
        self.assertLess(relaxed, base)
        self.gk.record_spoken(proactive=True, now=self.now)
        self.assertGreater(self.gk.effective_silence_threshold, relaxed)


if __name__ == "__main__":
    unittest.main()
