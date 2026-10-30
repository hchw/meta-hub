#!/usr/bin/env python3
"""Minimal VMC probe: send one head nod and/or a blendshape pulse.

Useful when switching renderers (e.g. VSeeFace -> VNyan): this isolates the
transport from the agent loop.

    python tools/vmc_probe.py --port 39539 --bone nod
    python tools/vmc_probe.py --port 39539 --blend A
    python tools/vmc_probe.py --port 39539 --bone nod --blend Joy --seconds 3
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from meta_hub.motion.bones import BonePose, MotionSender  # noqa: E402
from meta_hub.motion.primitives import GESTURES, gesture_pose  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=39539)
    ap.add_argument("--bone", choices=sorted(GESTURES), default=None,
                    help="gesture to play; omit for blendshape-only probes")
    ap.add_argument("--blend", default="", help="blendshape name, e.g. A or Joy")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--no-bones", action="store_true")
    ap.add_argument("--bone-apply", action="store_true",
                    help="also send the non-standard /VMC/Ext/Bone/Apply")
    ap.add_argument("--root", action="store_true",
                    help="send an identity /VMC/Ext/Root/Pos before bones")
    ap.add_argument("--profile", choices=["vrm0", "vrm1"], default="vrm0")
    args = ap.parse_args(argv)
    if args.bone is None and not args.blend:
        args.bone = "nod"  # bare invocation = quick head test

    sender = MotionSender(args.host, args.port,
                          send_bones=not args.no_bones and args.bone is not None,
                          send_bone_apply=args.bone_apply,
                          send_root=args.root,
                          profile=args.profile)
    duration = max(0.2, args.seconds)
    frames = max(1, int(duration * args.fps))
    for i in range(frames):
        t = duration * i / max(1, frames - 1)
        pose = gesture_pose(args.bone, 1.0, duration, t) if args.bone else BonePose()
        # Pulse in the middle so the change is visible against neutral frames.
        on = 3 < i < frames - 3
        weights = {args.blend: 1.0 if on else 0.0} if args.blend else {}
        sender.send(pose, weights)
        time.sleep(1.0 / max(1.0, args.fps))
    sender.send_neutral()
    print(f"sent {frames} frames to {args.host}:{args.port} "
          f"(bone={args.bone or '-'}, blend={args.blend or '-'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
