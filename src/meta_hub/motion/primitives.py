"""Named procedural gestures (design D8, task 5.3).

A gesture is a continuous function of progress ``p``; it starts and ends at
rest (``_envelope``), so clips can be overlaid on speech without a reset pop.
Head-only gestures keep the old amplitudes; full-body gestures drive hips,
spine, arms and legs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .bones import BonePose

# name -> (amplitude in degrees, cycles); special-cased gestures use the
# envelope only and ignore these values.
GESTURES: dict[str, tuple[float, float]] = {
    "nod": (14.0, 1.0),
    "shake": (12.0, 1.0),
    "tilt": (16.0, 1.0),
    "lean": (9.0, 1.0),
    "wave": (1.0, 1.0),
    "arms_up": (1.0, 1.0),
    "point": (1.0, 1.0),
    "bow": (1.0, 1.0),
    "clap": (1.0, 1.0),
    "dance": (1.0, 1.0),
}

DEFAULT_DURATION = {
    "nod": 0.9,
    "shake": 1.1,
    "tilt": 1.2,
    "lean": 1.6,
    "wave": 2.4,
    "arms_up": 1.8,
    "point": 1.6,
    "bow": 1.8,
    "clap": 1.6,
    "dance": 8.0,
}


@dataclass
class GestureClip:
    name: str
    intensity: float
    duration: float
    elapsed: float = 0.0

    def __post_init__(self) -> None:
        if self.name not in GESTURES:
            raise ValueError(f"unknown gesture: {self.name}")
        if not 0 <= self.intensity <= 1:
            raise ValueError("intensity must be in [0, 1]")
        if self.duration <= 0:
            raise ValueError("duration must be positive")

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    def sample(self, elapsed: float | None = None) -> BonePose:
        t = self.elapsed if elapsed is None else elapsed
        return gesture_pose(self.name, self.intensity, self.duration, t)

    def advance(self, dt: float) -> BonePose:
        self.elapsed += max(0.0, dt)
        return self.sample()


def _envelope(progress: float) -> float:
    """Zero at both ends, smooth peak in the middle -> returns to rest."""
    progress = min(1.0, max(0.0, progress))
    return math.sin(math.pi * progress)


def _plateau(progress: float, attack: float = 0.08, release: float = 0.12) -> float:
    """Quick ease-in, steady hold, quick ease-out (body gestures)."""
    p = min(1.0, max(0.0, progress))
    if p <= 0.0 or p >= 1.0:
        return 0.0

    def ease(x: float) -> float:
        x = min(1.0, max(0.0, x))
        return x * x * (3.0 - 2.0 * x)

    return min(ease(p / attack), ease((1.0 - p) / release))


def _dance(env: float, p: float, intensity: float, elapsed: float) -> BonePose:
    """A looping club sway: hips/chest counter-rotate, arms alternate.

    Tempo is expressed in seconds (not normalized progress) so a longer dance
    does not become a slow-motion sway.
    """
    phase = 2.0 * math.pi * 1.4 * elapsed
    beat = 2.0 * math.pi * 2.8 * elapsed
    g = env * intensity
    side = math.sin(phase)
    bounce = math.sin(beat)
    lift_l = (45.0 + 30.0 * math.sin(beat)) * g
    lift_r = (45.0 - 30.0 * math.sin(beat)) * g
    return BonePose({
        "Hips": (2.0 * bounce * g, 9.0 * side * g, 6.0 * math.sin(beat + 0.6) * g),
        "Spine": (2.0 * bounce * g, -5.0 * side * g, -3.0 * math.sin(beat + 0.6) * g),
        "Chest": (3.0 * bounce * g, 4.0 * side * g, -4.0 * math.sin(beat + 1.1) * g),
        "Neck": (1.5 * bounce * g, -2.0 * side * g, 0.0),
        "Head": (4.0 * math.sin(beat + 0.4) * g, -4.0 * side * g,
                 3.0 * math.sin(beat + 1.5) * g),
        "LeftUpperArm": (10.0 * side * g, 0.0, lift_l),
        "RightUpperArm": (-10.0 * side * g, 0.0, -lift_r),
        "LeftLowerArm": (0.0, 35.0 * g, 12.0 * math.sin(beat + 0.8) * g),
        "RightLowerArm": (0.0, -35.0 * g, -12.0 * math.sin(beat + 0.8) * g),
        "LeftHand": (0.0, 8.0 * math.sin(beat + 1.2) * g, 0.0),
        "RightHand": (0.0, -8.0 * math.sin(beat + 1.2) * g, 0.0),
        "LeftUpperLeg": (7.0 * side * g, 0.0, 2.0 * bounce * g),
        "RightUpperLeg": (-7.0 * side * g, 0.0, -2.0 * bounce * g),
        "LeftLowerLeg": (4.0 * max(0.0, -side) * g, 0.0, 0.0),
        "RightLowerLeg": (4.0 * max(0.0, side) * g, 0.0, 0.0),
    })


def gesture_pose(name: str, intensity: float, duration: float, elapsed: float) -> BonePose:
    if name not in GESTURES:
        raise ValueError(f"unknown gesture: {name}")
    amp, cycles = GESTURES[name]
    p = 0.0 if duration <= 0 else min(1.0, max(0.0, elapsed / duration))
    if p >= 1.0:
        return BonePose()
    body_gesture = name in ("wave", "arms_up", "point", "bow", "clap", "dance")
    env = (_plateau(p) if body_gesture else _envelope(p)) * intensity
    wave = math.sin(2 * math.pi * cycles * p)

    if name == "nod":
        return BonePose({"Head": (amp * env * wave, 0.0, 0.0)})
    if name == "shake":
        return BonePose({"Head": (0.0, amp * env * wave, 0.0)})
    if name == "tilt":
        return BonePose({"Head": (0.0, 0.0, amp * env * wave)})
    if name == "lean":
        return BonePose({
            "Chest": (amp * env * wave, 0.0, 0.0),
            "Head": (-0.35 * amp * env * wave, 0.0, 0.0),
        })
    if name == "wave":
        flick = math.sin(2 * math.pi * 3.0 * p)
        return BonePose({
            "RightUpperArm": (0.0, 0.0, -72.0 * env),
            "RightLowerArm": (0.0, -20.0 * env, -12.0 * env + 14.0 * flick * env),
            "RightHand": (0.0, 18.0 * flick * env, 0.0),
            "Chest": (0.0, -3.0 * env, 0.0),
            "Head": (0.0, 0.0, 4.0 * env),
        })
    if name == "arms_up":
        return BonePose({
            "LeftUpperArm": (0.0, 0.0, 82.0 * env),
            "RightUpperArm": (0.0, 0.0, -82.0 * env),
            "LeftLowerArm": (0.0, 12.0 * env, 6.0 * env),
            "RightLowerArm": (0.0, -12.0 * env, -6.0 * env),
            "Chest": (-4.0 * env, 0.0, 0.0),
            "Head": (-6.0 * env, 0.0, 0.0),
        })
    if name == "point":
        return BonePose({
            "RightUpperArm": (0.0, 0.0, -62.0 * env),
            "RightLowerArm": (0.0, -18.0 * env, 0.0),
            "RightHand": (0.0, -8.0 * env, 0.0),
            "Chest": (0.0, -8.0 * env, 0.0),
            "Head": (0.0, -5.0 * env, 0.0),
        })
    if name == "bow":
        return BonePose({
            "Hips": (6.0 * env, 0.0, 0.0),
            "Spine": (10.0 * env, 0.0, 0.0),
            "Chest": (18.0 * env, 0.0, 0.0),
            "Neck": (6.0 * env, 0.0, 0.0),
            "Head": (8.0 * env, 0.0, 0.0),
        })
    if name == "clap":
        beat = math.sin(2 * math.pi * 2.0 * p)
        return BonePose({
            "LeftUpperArm": (0.0, 0.0, 28.0 * env),
            "RightUpperArm": (0.0, 0.0, -28.0 * env),
            "LeftLowerArm": (0.0, 65.0 * env + 18.0 * beat * env, 0.0),
            "RightLowerArm": (0.0, -65.0 * env - 18.0 * beat * env, 0.0),
            "Chest": (0.0, 0.0, 0.0),
        })
    if name == "dance":
        return _dance(env, p, intensity, elapsed)
    return BonePose()


def make_gesture(name: str, intensity: float = 0.6,
                 duration: float | None = None) -> GestureClip:
    if name not in GESTURES:
        raise ValueError(f"unknown gesture: {name}")
    return GestureClip(name, intensity, duration or DEFAULT_DURATION[name])
