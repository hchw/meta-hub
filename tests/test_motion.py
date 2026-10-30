from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from meta_hub.motion.bones import (DRIVEN_BONES, BonePose, MotionSender, Ownership,
                                   VmcBoneSender, euler_to_quaternion)
from meta_hub.motion.idle import IdleLayer
from meta_hub.motion.primitives import GESTURES, gesture_pose, make_gesture


class Tell:
    def __init__(self):
        self.sent = []

    def send_message(self, address, value):
        self.sent.append((address, value))


class BoneSenderTest(unittest.TestCase):
    def test_quaternion_is_normalized(self):
        q = euler_to_quaternion(10, -20, 30)
        self.assertAlmostEqual(sum(v * v for v in q), 1.0, places=6)

    def test_sends_head_neck_chest(self):
        sender = VmcBoneSender()
        sender.client = Tell()
        sender.send(BonePose({"Head": (10, 0, 0), "Neck": (0, 5, 0),
                              "Chest": (0, 0, 3)}))
        addresses = [a for a, _ in sender.client.sent]
        self.assertIn("/VMC/Ext/Bone/Pos", addresses)
        self.assertNotIn("/VMC/Ext/Bone/Apply", addresses)
        bones = [v[0] for a, v in sender.client.sent if a == "/VMC/Ext/Bone/Pos"]
        self.assertEqual(bones, list(DRIVEN_BONES))
        self.assertEqual(sender.sent_frames, 1)
        self.assertTrue(sender.client.sent)

    def test_optional_bone_apply_for_legacy_renderers(self):
        sender = VmcBoneSender(send_bone_apply=True)
        sender.client = Tell()
        sender.send_neutral()
        self.assertIn("/VMC/Ext/Bone/Apply", [a for a, _ in sender.client.sent])

    def test_motion_sender_combines_face_and_bones(self):
        sender = MotionSender()
        sender.client = Tell()
        sender.send(BonePose({"Head": (5, 0, 0)}), {"A": 0.7})
        addresses = [a for a, _ in sender.client.sent]
        self.assertIn("/VMC/Ext/Blend/Val", addresses)
        self.assertIn("/VMC/Ext/Bone/Pos", addresses)
        self.assertNotIn("/VMC/Ext/Bone/Apply", addresses)

    def test_motion_sender_can_disable_bones_for_blendshape_only_renderers(self):
        sender = MotionSender(send_bones=False)
        sender.client = Tell()
        sender.send(BonePose({"Head": (5, 0, 0)}), {"A": 0.7})
        addresses = [a for a, _ in sender.client.sent]
        self.assertIn("/VMC/Ext/Blend/Val", addresses)
        self.assertNotIn("/VMC/Ext/Bone/Pos", addresses)


class GestureTest(unittest.TestCase):
    def test_every_named_gesture_returns_to_rest(self):
        for name in GESTURES:
            mid = gesture_pose(name, 1.0, 1.0, 0.25)
            self.assertFalse(mid.is_neutral(), name)
            end = gesture_pose(name, 1.0, 1.0, 1.0)
            self.assertTrue(end.is_neutral(), name)
            after = gesture_pose(name, 1.0, 1.0, 1.5)
            self.assertTrue(after.is_neutral(), name)

    def test_clip_advances_and_finishes(self):
        clip = make_gesture("nod", 0.5, 0.4)
        clip.advance(0.2)
        self.assertFalse(clip.done)
        clip.advance(0.3)
        self.assertTrue(clip.done)
        self.assertTrue(clip.sample().is_neutral())

    def test_unknown_gesture(self):
        with self.assertRaises(ValueError):
            make_gesture("backflip")


class IdleLayerTest(unittest.TestCase):
    def test_sixty_seconds_of_visible_low_frequency_motion(self):
        idle = IdleLayer()
        self.assertGreater(idle.motion_range(60.0), 1.0)
        poses = [idle.sample(t)[0] for t in range(0, 61)]
        head_x = [p.euler["Head"][0] for p in poses]
        self.assertGreater(max(head_x) - min(head_x), 0.1)

    def test_random_blinks_happen(self):
        idle = IdleLayer(seed=3)
        weights = [idle.sample(t / 10)[1]["Blink"] for t in range(0, 600)]
        self.assertGreater(max(weights), 0.9)

    def test_disabled_idle_is_still(self):
        idle = IdleLayer(enabled=False)
        pose, weights = idle.sample(12.3)
        self.assertTrue(pose.is_neutral())
        self.assertEqual(weights, {})


class OwnershipTest(unittest.TestCase):
    def test_default_owns_full_body(self):
        ownership = Ownership()
        ownership.validate()
        self.assertEqual(ownership.bones["RightUpperArm"], "vmc")
        self.assertEqual(ownership.bones["Hips"], "vmc")

    def test_rejects_renderer_ownership_of_driven_bone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ownership.json"
            path.write_text(json.dumps({"Head": "renderer"}))
            with self.assertRaises(ValueError):
                Ownership.load(path)

    def test_rejects_unknown_bone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ownership.json"
            path.write_text(json.dumps({"Tail": "vmc"}))
            with self.assertRaises(ValueError):
                Ownership.load(path)


class BodyGestureTest(unittest.TestCase):
    def test_wave_uses_right_arm(self):
        pose = gesture_pose("wave", 1.0, 2.0, 1.0)
        self.assertIn("RightUpperArm", pose.euler)
        self.assertIn("RightLowerArm", pose.euler)

    def test_dance_uses_hips_arms_and_legs(self):
        pose = gesture_pose("dance", 1.0, 6.0, 1.5)
        for bone in ("Hips", "Chest", "LeftUpperArm", "RightUpperArm",
                     "LeftUpperLeg", "RightUpperLeg"):
            self.assertIn(bone, pose.euler)

    def test_arms_up_raises_both_upper_arms(self):
        pose = gesture_pose("arms_up", 1.0, 2.0, 1.0)
        self.assertLess(pose.euler["RightUpperArm"][2], 0)
        self.assertGreater(pose.euler["LeftUpperArm"][2], 0)


if __name__ == "__main__":
    unittest.main()
