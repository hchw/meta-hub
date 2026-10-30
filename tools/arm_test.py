#!/usr/bin/env python3
"""Hold four candidate 'elbows tucked, forearms up' arm poses for comparison."""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from meta_hub.motion.bones import BonePose, MotionSender  # noqa: E402

VARIANTS = {
    "A_lower_z180": {
        "LeftUpperArm": (0, 0, -80), "RightUpperArm": (0, 0, 80),
        "LeftLowerArm": (0, 0, 180), "RightLowerArm": (0, 0, -180),
    },
    "B_lower_y90": {
        "LeftUpperArm": (0, 0, -80), "RightUpperArm": (0, 0, 80),
        "LeftLowerArm": (0, 90, 0), "RightLowerArm": (0, -90, 0),
    },
    "C_upper_fwd_lower_z90": {
        "LeftUpperArm": (0, 20, -70), "RightUpperArm": (0, -20, 70),
        "LeftLowerArm": (0, 0, 90), "RightLowerArm": (0, 0, -90),
    },
    "D_lower_x90": {
        "LeftUpperArm": (0, 0, -80), "RightUpperArm": (0, 0, 80),
        "LeftLowerArm": (90, 0, 0), "RightLowerArm": (-90, 0, 0),
    },
}

sender = MotionSender("127.0.0.1", 3334, profile="vrm1")
for name, bones in VARIANTS.items():
    print(f"\n>>> {name}", flush=True)
    sender.send(BonePose(bones), {})
    time.sleep(4.0)
sender.send_neutral()
print("done", flush=True)
