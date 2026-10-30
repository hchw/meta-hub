from __future__ import annotations

import unittest

from meta_hub.motion.choreography import (DanceProgram, PoseProgram, blend_pose,
                                                 default_program, parse_dance)
from meta_hub.motion.bones import BonePose


class DanceProgramTest(unittest.TestCase):
    def test_default_program_has_steps_and_loops(self):
        p = default_program(120)
        self.assertGreater(len(p.steps), 3)
        self.assertAlmostEqual(p.duration, 6.0)
        self.assertFalse(p.sample(1.0).is_neutral())
        # one full loop returns to the same phase
        self.assertEqual(p.sample(0.1).euler.keys(), p.sample(p.duration + 0.1).euler.keys())

    def test_rejects_unknown_move(self):
        with self.assertRaises(ValueError):
            DanceProgram.from_dict({"steps": [{"at": 0, "move": "backflip", "beats": 2}]})

    def test_rejects_bad_bpm_and_steps(self):
        with self.assertRaises(ValueError):
            DanceProgram.from_dict({"bpm": 10, "steps": [{"move": "bounce", "beats": 1}]})
        with self.assertRaises(ValueError):
            DanceProgram.from_dict({"steps": []})

    def test_mirror_swaps_arms(self):
        p = DanceProgram.from_dict({
            "steps": [{"at": 0, "move": "point", "beats": 2, "mirror": True}],
        })
        pose = p.sample(0.5)
        self.assertIn("LeftUpperArm", pose.euler)
        self.assertNotIn("RightUpperArm", pose.euler)

    def test_loop_and_stop(self):
        p = DanceProgram.from_dict({
            "loop": False,
            "steps": [{"at": 0, "move": "bounce", "beats": 2}],
        })
        self.assertFalse(p.sample(10).is_neutral() is False)
        self.assertTrue(p.sample(p.duration + 0.01).is_neutral())

    def test_blend_is_linear(self):
        a = BonePose({"Head": (0.0, 0.0, 0.0)})
        b = BonePose({"Head": (10.0, 20.0, -10.0)})
        m = blend_pose(a, b, 0.5).euler["Head"]
        self.assertEqual(m, (5.0, 10.0, -5.0))


class PoseProgramTest(unittest.TestCase):
    def build(self):
        return PoseProgram.from_dict({
            "bpm": 120,
            "loop": True,
            "poses": [
                {"at": 0, "pose": "center", "hold": 0.5, "ease": "smooth"},
                {"at": 2, "pose": "hip_left", "hold": 1.0, "ease": "snap"},
                {"at": 4, "pose": "left_arm_up", "ease": "soft"},
                {"at": 6, "pose": "clap_close", "ease": "smooth"},
            ],
        })

    def test_samples_between_key_poses(self):
        p = self.build()
        self.assertFalse(p.sample(0.5).is_neutral())
        self.assertFalse(p.sample(1.2).is_neutral())
        self.assertFalse(p.sample(p.duration - 0.1).is_neutral())

    def test_loop_closes_to_first_pose(self):
        p = self.build()
        self.assertEqual(p.sample(0.0).euler.keys(), p.sample(p.duration).euler.keys())

    def test_rejects_unknown_pose_and_ease(self):
        with self.assertRaises(ValueError):
            PoseProgram.from_dict({"poses": [{"pose": "moonwalk"}]})
        with self.assertRaises(ValueError):
            PoseProgram.from_dict({"poses": [{"pose": "center", "ease": "warp"}]})

    def test_parse_dance_dispatch(self):
        self.assertIsInstance(parse_dance({"poses": [{"pose": "center"}]}), PoseProgram)
        self.assertIsInstance(parse_dance({"steps": [{"move": "bounce", "beats": 1}]}), DanceProgram)
        with self.assertRaises(ValueError):
            parse_dance({})


if __name__ == "__main__":
    unittest.main()
