from __future__ import annotations

import unittest

from meta_hub.motion.bones import BonePose, MotionSender
from meta_hub.motion.idle import IdleLayer
from meta_hub.motion.player import VmcMotionPlayer, expression_weights
from meta_hub.stages.vmc import VmcSender, arkit_to_vrm, blend_names_for


class Tell:
    def __init__(self):
        self.sent = []

    def send_message(self, address, value):
        self.sent.append((address, value))


class ProfileTest(unittest.TestCase):
    def test_vrm0_names_are_default(self):
        self.assertIn("A", blend_names_for())
        self.assertEqual(arkit_to_vrm({"JawOpen": 1.0})["A"], 1.0)

    def test_vrm1_names_convert_vrm0_presets(self):
        names = blend_names_for("vrm1")
        self.assertIn("aa", names)
        self.assertNotIn("A", names)
        out = arkit_to_vrm({"JawOpen": 1.0, "MouthSmileLeft": 1.0}, profile="vrm1")
        self.assertAlmostEqual(out["aa"], 1.0)
        self.assertIn("happy", out)

    def test_sender_uses_profile_names(self):
        sender = VmcSender(profile="vrm1")
        sender.client = Tell()
        sender.send({"aa": 0.5})
        names = [v[0] for a, v in sender.client.sent if a == "/VMC/Ext/Blend/Val"]
        self.assertIn("aa", names)
        self.assertNotIn("A", names)

    def test_sender_emits_root_only_when_requested(self):
        sender = MotionSender(send_root=True)
        sender.client = Tell()
        sender.send(BonePose(), {})
        self.assertIn("/VMC/Ext/Root/Pos", [a for a, _ in sender.client.sent])
        sender2 = MotionSender(send_root=False)
        sender2.client = Tell()
        sender2.send(BonePose(), {})
        self.assertNotIn("/VMC/Ext/Root/Pos", [a for a, _ in sender2.client.sent])

    def test_expression_mapping_follows_profile(self):
        self.assertEqual(expression_weights("joy", 1.0, "vrm0"), {"Joy": 1.0})
        self.assertEqual(expression_weights("joy", 1.0, "vrm1"), {"happy": 1.0})


class PlayerTest(unittest.TestCase):
    def build(self):
        self.now = 0.0
        sender = MotionSender()
        sender.client = Tell()
        player = VmcMotionPlayer(
            sender=sender, idle=IdleLayer(enabled=False), autostart=False,
            clock=lambda: self.now,
        )
        return player, sender

    def weights(self, sender):
        return {v[0]: v[1] for a, v in sender.client.sent
                if a == "/VMC/Ext/Blend/Val"}

    def test_expression_reaches_weights(self):
        player, sender = self.build()
        player.set("joy", 0.8)
        player.send_frame()
        self.assertAlmostEqual(self.weights(sender)["Joy"], 0.8)

    def test_gesture_overlays_bones_without_stopping_expression(self):
        player, sender = self.build()
        player.set("angry", 1.0)
        player.play("nod", 1.0, 1.0)
        self.now = 0.4
        player.send_frame()
        bones = [v for a, v in sender.client.sent if a == "/VMC/Ext/Bone/Pos"]
        self.assertTrue(any(abs(x) > 1e-6 for v in bones for x in v[4:7]))
        self.assertAlmostEqual(self.weights(sender)["Angry"], 1.0)

    def test_cancel_is_idempotent_and_resets(self):
        player, sender = self.build()
        player.set("joy", 1.0)
        player.play("nod", 1.0, 1.0)
        player.cancel_all()
        player.cancel_all()
        self.now = 1.0
        sender.client.sent.clear()
        player.send_frame()
        self.assertTrue(all(abs(v) < 1e-9 for v in self.weights(sender).values()))
        bones = [v for a, v in sender.client.sent if a == "/VMC/Ext/Bone/Pos"]
        self.assertTrue(all(abs(x) < 1e-9 for v in bones for x in v[4:7]))

    def test_face_weights_from_a2f_are_preserved(self):
        player, sender = self.build()
        player.set_face_weights({"A": 0.7, "Blink": 0.1})
        player.send_frame()
        self.assertAlmostEqual(self.weights(sender)["A"], 0.7)


if __name__ == "__main__":
    unittest.main()
