#!/usr/bin/env python3
"""'Wipe the glass' VMC motion stream for VNyan.

Both hands are held in front of the chest, elbows bent, while the torso/hips
sweep left-right on the beat.  This is intentionally a small, tunable demo of
the full-body bone pipeline (port 3334, VRM1 blendshapes).
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from meta_hub.motion.bones import BonePose, MotionSender  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3334)
    ap.add_argument("--bpm", type=float, default=120.0)
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="0 = run until Ctrl+C")
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--static", action="store_true", help="freeze the sweep for pose inspection")
    ap.add_argument("--hand-x", type=float, default=90.0)
    ap.add_argument("--hand-y", type=float, default=0.0)
    ap.add_argument("--hand-z", type=float, default=0.0)
    ap.add_argument("--lower-z", type=float, default=98.0)
    ap.add_argument("--upper-z", type=float, default=90.0)
    ap.add_argument("--upper-y", type=float, default=0.0)
    ap.add_argument("--lower-x", type=float, default=90.0)
    ap.add_argument("--profile", default="vrm0")
    args = ap.parse_args(argv)

    sender = MotionSender(args.host, args.port, profile=args.profile)
    beat_duration = 60.0 / max(1.0, args.bpm)
    dt = 1.0 / max(1.0, args.fps)
    start = time.monotonic()
    next_tick = start
    last_beat = -1
    face = ""
    face_until = 0.0
    print(f"wipe-glass -> {args.host}:{args.port} @ {args.bpm:g} BPM", flush=True)

    try:
        while True:
            now = time.monotonic()
            elapsed = now - start
            if args.seconds and elapsed >= args.seconds:
                break

            beat = elapsed / beat_duration
            idx = int(beat)
            phase = 2.0 * math.pi * beat
            sweep = 0.0 if args.static else math.sin(phase)
            bounce = 0.0 if args.static else abs(math.sin(phase))

            # 8-beat expression accents. They are sent on the same socket as
            # the bones, so face and body never race each other.
            if idx != last_beat:
                last_beat = idx
                mod = idx % 8
                face = "happy" if mod == 0 else "aa" if mod == 3 else "blink" if mod == 6 else ""
                face_until = now + (0.22 if face == "blink" else beat_duration * 0.9)

            pose = BonePose({
                # weight shift / knee bounce
                "Hips": (2.5 * bounce, 4.0 * sweep, 3.0 * sweep),
                "Spine": (0.0, -3.0 * sweep, 0.0),
                "Chest": (-6.0, 8.0 * sweep, 0.0),
                "UpperChest": (-2.0, 4.0 * sweep, 0.0),
                "Neck": (0.0, -2.0 * sweep, 0.0),
                "Head": (0.0, -4.0 * sweep, 2.0 * sweep),

                # Both hands up in front, elbows bent. Keep the upper arms
                # steady and let the torso sweep the hands across the glass.
                "LeftShoulder": (0.0, 0.0, 8.0),
                "RightShoulder": (0.0, 0.0, -8.0),
                # Bring both upper arms forward (Y), then bend the elbows
                # upward (local Z).  Bending around Y made the hands meet in
                # the middle like handcuffs.
                "LeftUpperArm": (0.0, args.upper_y, -args.upper_z),
                "RightUpperArm": (0.0, -args.upper_y, args.upper_z),
                # More elbow bend so the forearms/hands point upward rather
                # than forward.  Fingers follow the hand bone, so this is what
                # makes them face up.
                "LeftLowerArm": (args.lower_x, 0.0, 0.0),
                "RightLowerArm": (-args.lower_x, 0.0, 0.0),
                # Fingers point up via the elbow bend; this roll turns the
                # palms from facing down to facing the camera.  The two hands
                # are mirrored, so the roll signs are opposite.
                "LeftHand": (args.hand_x, args.hand_y, args.hand_z),
                "RightHand": (-args.hand_x, -args.hand_y, -args.hand_z),

                "LeftUpperLeg": (9.0 * bounce, 0.0, 3.0 * sweep),
                "RightUpperLeg": (9.0 * bounce, 0.0, -3.0 * sweep),
                "LeftLowerLeg": (8.0 * max(0.0, bounce), 0.0, 0.0),
                "RightLowerLeg": (8.0 * max(0.0, bounce), 0.0, 0.0),
            })
            weights = {face: 1.0} if face and now < face_until else {}
            sender.send(pose, weights)

            next_tick += dt
            time.sleep(max(0.0, next_tick - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        sender.send_neutral()
    print("wipe-glass stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
