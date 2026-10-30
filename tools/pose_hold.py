#!/usr/bin/env python3
"""Hold a JSON bone pose for visual inspection (VNyan)."""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from meta_hub.motion.bones import BonePose, MotionSender  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("pose")
ap.add_argument("--port", type=int, default=3334)
ap.add_argument("--profile", default="vrm0")
ap.add_argument("--seconds", type=float, default=20.0)
args = ap.parse_args()
raw = json.loads(args.pose)
pose = BonePose({k: tuple(v) for k, v in raw.items()})
s = MotionSender("127.0.0.1", args.port, profile=args.profile)
end = time.monotonic() + args.seconds
while time.monotonic() < end:
    s.send(pose, {})
    time.sleep(1 / 60)
s.send_neutral()
