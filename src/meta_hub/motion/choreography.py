"""High-level dance programs: LLM names moves and beats, runtime interpolates.

The model must never generate per-frame bone data.  It emits a small JSON
program (BPM + move blocks).  This module validates it, maps moves to body
poses and can be sampled at 60fps by ``VmcMotionPlayer``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .bones import BonePose

# Moves the LLM is allowed to compose.  Each is a loop-friendly function of
# phase in [0, 1); use ``mirror`` to make left/right variants.
MOVES = (
    "bounce",
    "step_touch",
    "hip_sway",
    "body_roll",
    "arm_wave",
    "clap",
    "point",
    "spin",
    "wave",
)

_SWAP = {
    "Left": "Right", "Right": "Left",
    "LeftShoulder": "RightShoulder", "RightShoulder": "LeftShoulder",
    "LeftUpperArm": "RightUpperArm", "RightUpperArm": "LeftUpperArm",
    "LeftLowerArm": "RightLowerArm", "RightLowerArm": "LeftLowerArm",
    "LeftHand": "RightHand", "RightHand": "LeftHand",
    "LeftUpperLeg": "RightUpperLeg", "RightUpperLeg": "LeftUpperLeg",
    "LeftLowerLeg": "RightLowerLeg", "RightLowerLeg": "LeftLowerLeg",
    "LeftFoot": "RightFoot", "RightFoot": "LeftFoot",
}


def _mirror(pose: BonePose) -> BonePose:
    out: dict[str, tuple[float, float, float]] = {}
    for bone, (x, y, z) in pose.euler.items():
        target = _SWAP.get(bone, bone)
        if target != bone:
            out[target] = (x, -y, -z)
        else:
            out[bone] = (x, -y, -z)  # central bones: mirror yaw/roll
    return BonePose(out)


def _move(name: str, phase: float, intensity: float) -> BonePose:
    s = math.sin(2.0 * math.pi * phase)
    c = math.cos(2.0 * math.pi * phase)
    s2 = math.sin(4.0 * math.pi * phase)
    i = intensity

    if name == "bounce":
        return BonePose({
            "Hips": (3.0 * s * i, 0.0, 0.0),
            "Chest": (2.0 * s * i, 0.0, 0.0),
            "Head": (-2.0 * s * i, 0.0, 0.0),
            "LeftUpperLeg": (5.0 * max(0.0, s) * i, 0.0, 2.0 * s * i),
            "RightUpperLeg": (5.0 * max(0.0, s) * i, 0.0, -2.0 * s * i),
            "LeftLowerLeg": (4.0 * max(0.0, s) * i, 0.0, 0.0),
            "RightLowerLeg": (4.0 * max(0.0, s) * i, 0.0, 0.0),
            "LeftUpperArm": (0.0, 0.0, 6.0 * s * i),
            "RightUpperArm": (0.0, 0.0, -6.0 * s * i),
        })
    if name == "step_touch":
        return BonePose({
            "Hips": (0.0, 10.0 * s * i, 7.0 * s * i),
            "Spine": (0.0, -5.0 * s * i, -3.0 * s * i),
            "Chest": (0.0, -4.0 * s * i, -3.0 * s * i),
            "Head": (0.0, 3.0 * s * i, 2.0 * s * i),
            "LeftUpperLeg": (12.0 * max(0.0, s) * i, 0.0, 8.0 * s * i),
            "RightUpperLeg": (12.0 * max(0.0, -s) * i, 0.0, 8.0 * s * i),
            "LeftLowerLeg": (8.0 * max(0.0, -s) * i, 0.0, 0.0),
            "RightLowerLeg": (8.0 * max(0.0, s) * i, 0.0, 0.0),
            "LeftUpperArm": (0.0, 0.0, 22.0 + 10.0 * s * i),
            "RightUpperArm": (0.0, 0.0, -22.0 + 10.0 * s * i),
        })
    if name == "hip_sway":
        return BonePose({
            "Hips": (2.0 * c * i, 14.0 * s * i, 8.0 * s * i),
            "Spine": (0.0, -7.0 * s * i, -4.0 * s * i),
            "Chest": (1.0 * c * i, 5.0 * s * i, -3.0 * s * i),
            "Neck": (0.0, -2.0 * s * i, 0.0),
            "Head": (2.0 * c * i, -5.0 * s * i, 3.0 * s * i),
            "LeftUpperArm": (0.0, 0.0, 18.0 + 12.0 * s * i),
            "RightUpperArm": (0.0, 0.0, -18.0 + 12.0 * s * i),
            "LeftLowerArm": (0.0, 20.0 * i, 0.0),
            "RightLowerArm": (0.0, -20.0 * i, 0.0),
        })
    if name == "body_roll":
        return BonePose({
            "Hips": (6.0 * s * i, 6.0 * c * i, 5.0 * c * i),
            "Spine": (4.0 * s2 * i, -3.0 * c * i, -4.0 * s * i),
            "Chest": (6.0 * c * i, 3.0 * s * i, -5.0 * c * i),
            "Neck": (-2.0 * c * i, 0.0, 0.0),
            "Head": (-4.0 * c * i, 3.0 * s * i, 4.0 * s * i),
            "LeftUpperArm": (0.0, 0.0, 25.0 * i),
            "RightUpperArm": (0.0, 0.0, -25.0 * i),
        })
    if name == "arm_wave":
        lift_l = (55.0 + 25.0 * s) * i
        lift_r = (55.0 - 25.0 * s) * i
        return BonePose({
            "LeftUpperArm": (0.0, 0.0, lift_l),
            "RightUpperArm": (0.0, 0.0, -lift_r),
            "LeftLowerArm": (0.0, 20.0 * i, 15.0 * s2 * i),
            "RightLowerArm": (0.0, -20.0 * i, -15.0 * s2 * i),
            "LeftHand": (0.0, 15.0 * s2 * i, 0.0),
            "RightHand": (0.0, -15.0 * s2 * i, 0.0),
            "Chest": (0.0, 0.0, 5.0 * s * i),
        })
    if name == "clap":
        close = 20.0 + 35.0 * (0.5 + 0.5 * s)
        return BonePose({
            "LeftUpperArm": (0.0, 0.0, 25.0 * i),
            "RightUpperArm": (0.0, 0.0, -25.0 * i),
            "LeftLowerArm": (0.0, close * i, 0.0),
            "RightLowerArm": (0.0, -close * i, 0.0),
            "Chest": (0.0, 0.0, 0.0),
            "Head": (2.0 * s2 * i, 0.0, 0.0),
        })
    if name == "point":
        return BonePose({
            "RightUpperArm": (0.0, 0.0, -65.0 * i),
            "RightLowerArm": (0.0, -18.0 * i, 0.0),
            "RightHand": (0.0, -8.0 * i, 0.0),
            "Chest": (0.0, -8.0 * i, 0.0),
            "Head": (0.0, -5.0 * i, 0.0),
        })
    if name == "spin":
        angle = 360.0 * phase
        return BonePose({
            "Hips": (0.0, angle, 0.0),
            "Spine": (0.0, -15.0 * i, 0.0),
            "Chest": (0.0, -10.0 * i, 0.0),
            "LeftUpperArm": (0.0, 0.0, 55.0 * i),
            "RightUpperArm": (0.0, 0.0, -55.0 * i),
        })
    if name == "wave":
        flick = math.sin(6.0 * math.pi * phase)
        return BonePose({
            "RightUpperArm": (0.0, 0.0, -72.0 * i),
            "RightLowerArm": (0.0, -20.0 * i, -12.0 * i + 14.0 * flick * i),
            "RightHand": (0.0, 18.0 * flick * i, 0.0),
            "Chest": (0.0, -3.0 * i, 0.0),
            "Head": (0.0, 0.0, 4.0 * i),
        })
    return BonePose()


@dataclass(frozen=True)
class DanceStep:
    at: float
    move: str
    beats: float
    intensity: float = 0.8
    mirror: bool = False

    @property
    def end(self) -> float:
        return self.at + self.beats

    def sample(self, local_beat: float) -> BonePose:
        phase = 0.0 if self.beats <= 0 else min(1.0, max(0.0, local_beat / self.beats))
        pose = _move(self.move, phase, self.intensity)
        return _mirror(pose) if self.mirror else pose


@dataclass
class DanceProgram:
    bpm: float = 120.0
    steps: list[DanceStep] = field(default_factory=list)
    loop: bool = True
    name: str = ""

    @property
    def total_beats(self) -> float:
        return max((s.end for s in self.steps), default=0.0)

    @property
    def duration(self) -> float:
        return self.total_beats * 60.0 / self.bpm if self.bpm > 0 else 0.0

    def sample(self, elapsed: float) -> BonePose:
        if not self.steps or self.bpm <= 0:
            return BonePose()
        beat = elapsed * self.bpm / 60.0
        total = self.total_beats
        if self.loop:
            beat = beat % total
        elif beat >= total:
            return BonePose()
        # Last step whose start is <= current beat; hold gaps as rest.
        current = None
        for step in self.steps:
            if step.at <= beat + 1e-9:
                current = step
            else:
                break
        if current is None or beat >= current.end:
            return BonePose()
        local = beat - current.at
        # Moves are cyclic: phase 0 and phase 1 produce the same pose, so
        # stepping to the next move at a loop boundary is already continuous.
        return current.sample(local)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DanceProgram":
        if not isinstance(data, dict):
            raise ValueError("dance program must be an object")
        bpm = float(data.get("bpm", 120.0))
        if not 40.0 <= bpm <= 240.0:
            raise ValueError("bpm must be between 40 and 240")
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("steps must be a non-empty list")
        if len(raw_steps) > 32:
            raise ValueError("steps must contain at most 32 entries")
        steps: list[DanceStep] = []
        for raw in raw_steps:
            if not isinstance(raw, dict):
                raise ValueError("each step must be an object")
            move = raw.get("move")
            if move not in MOVES:
                raise ValueError(f"unknown move: {move!r}; use one of {MOVES}")
            at = float(raw.get("at", 0.0))
            beats = float(raw.get("beats", 1.0))
            intensity = float(raw.get("intensity", 0.8))
            mirror = bool(raw.get("mirror", False))
            if at < 0 or beats <= 0 or not 0 <= intensity <= 1:
                raise ValueError("step needs at>=0, beats>0, 0<=intensity<=1")
            steps.append(DanceStep(at, str(move), beats, intensity, mirror))
        steps.sort(key=lambda s: (s.at, s.beats))
        total = max(s.end for s in steps)
        if total > 128:
            raise ValueError("dance is too long (max 128 beats)")
        return cls(bpm=bpm, steps=steps, loop=bool(data.get("loop", True)),
                   name=str(data.get("name", "")))


def _smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def blend_pose(a: BonePose, b: BonePose, w: float) -> BonePose:
    w = min(1.0, max(0.0, w))
    keys = set(a.euler) | set(b.euler)
    out: dict[str, tuple[float, float, float]] = {}
    for bone in keys:
        av = a.euler.get(bone, (0.0, 0.0, 0.0))
        bv = b.euler.get(bone, (0.0, 0.0, 0.0))
        out[bone] = (av[0] + (bv[0] - av[0]) * w,
                     av[1] + (bv[1] - av[1]) * w,
                     av[2] + (bv[2] - av[2]) * w)
    return BonePose(out)


def parse_dance(data: dict[str, Any]) -> DanceProgram:
    return DanceProgram.from_dict(data)


def default_program(bpm: float = 120.0) -> DanceProgram:
    """A safe 8-count demo loop for the CLI and smoke tests."""
    return DanceProgram.from_dict({
        "bpm": bpm,
        "loop": True,
        "steps": [
            {"at": 0, "move": "bounce", "beats": 2, "intensity": 0.8},
            {"at": 2, "move": "step_touch", "beats": 2, "intensity": 0.7},
            {"at": 4, "move": "hip_sway", "beats": 2, "intensity": 0.8},
            {"at": 6, "move": "arm_wave", "beats": 2, "intensity": 0.75},
            {"at": 8, "move": "body_roll", "beats": 2, "intensity": 0.7},
            {"at": 10, "move": "clap", "beats": 2, "intensity": 0.75},
        ],
    })


# ---------------------------------------------------------------------------
# Key-pose library: hand-authored full-body poses.  These are the "words" of
# the upgraded dance language; the LLM arranges them on a beat grid.
# ---------------------------------------------------------------------------

_RAW_POSES: dict[str, dict[str, tuple[float, float, float]]] = {
    "center": {},
    "hip_left": {
        "Hips": (0, -12, 9), "Spine": (0, 6, -4), "Chest": (0, 5, -4),
        "Neck": (0, 4, 0), "Head": (2, 4, 4),
        "LeftUpperArm": (0, 0, 18), "RightUpperArm": (0, 0, -10),
        "LeftLowerArm": (0, 25, 0), "RightLowerArm": (0, -25, 0),
        "LeftUpperLeg": (8, 0, 6), "RightUpperLeg": (-4, 0, 4),
    },
    "hip_right": {
        "Hips": (0, 12, -9), "Spine": (0, -6, 4), "Chest": (0, -5, 4),
        "Neck": (0, -4, 0), "Head": (2, -4, -4),
        "LeftUpperArm": (0, 0, 10), "RightUpperArm": (0, 0, -18),
        "LeftLowerArm": (0, 25, 0), "RightLowerArm": (0, -25, 0),
        "LeftUpperLeg": (-4, 0, -4), "RightUpperLeg": (8, 0, -6),
    },
    "arms_open": {
        "LeftUpperArm": (0, 0, 58), "RightUpperArm": (0, 0, -58),
        "LeftLowerArm": (0, 18, 8), "RightLowerArm": (0, -18, -8),
        "Chest": (-3, 0, 0), "Head": (-4, 0, 0),
    },
    "arms_up": {
        "LeftUpperArm": (0, 0, 95), "RightUpperArm": (0, 0, -95),
        "LeftLowerArm": (0, 12, 5), "RightLowerArm": (0, -12, -5),
        "Chest": (-5, 0, 0), "Head": (-8, 0, 0),
    },
    "left_arm_up": {
        "LeftUpperArm": (0, 0, 95), "LeftLowerArm": (0, 15, 8),
        "RightUpperArm": (0, 0, -8), "RightLowerArm": (0, -15, 0),
        "Chest": (-2, 10, 0), "Head": (-3, 8, 4),
    },
    "right_arm_up": {
        "RightUpperArm": (0, 0, -95), "RightLowerArm": (0, -15, -8),
        "LeftUpperArm": (0, 0, 8), "LeftLowerArm": (0, 15, 0),
        "Chest": (-2, -10, 0), "Head": (-3, -8, -4),
    },
    "hands_on_hips": {
        "LeftUpperArm": (0, 0, 32), "RightUpperArm": (0, 0, -32),
        "LeftLowerArm": (0, 78, 0), "RightLowerArm": (0, -78, 0),
        "Chest": (2, 0, 0), "Head": (2, 0, 0),
    },
    "point_left": {
        "LeftUpperArm": (0, 0, 72), "LeftLowerArm": (0, 8, 0),
        "RightUpperArm": (0, 0, -10), "RightLowerArm": (0, -20, 0),
        "Chest": (0, 12, 0), "Head": (0, 10, 3),
    },
    "point_right": {
        "RightUpperArm": (0, 0, -72), "RightLowerArm": (0, -8, 0),
        "LeftUpperArm": (0, 0, 10), "LeftLowerArm": (0, 20, 0),
        "Chest": (0, -12, 0), "Head": (0, -10, -3),
    },
    "clap_open": {
        "LeftUpperArm": (0, 0, 38), "RightUpperArm": (0, 0, -38),
        "LeftLowerArm": (0, 20, 0), "RightLowerArm": (0, -20, 0),
        "Chest": (0, 0, 0),
    },
    "clap_close": {
        "LeftUpperArm": (0, 0, 28), "RightUpperArm": (0, 0, -28),
        "LeftLowerArm": (0, 68, 0), "RightLowerArm": (0, -68, 0),
        "Head": (3, 0, 0),
    },
    "body_wave_low": {
        "Hips": (14, 0, 0), "Spine": (-6, 0, 0), "Chest": (-12, 0, 0),
        "Neck": (6, 0, 0), "Head": (8, 0, 0),
        "LeftUpperArm": (0, 0, 25), "RightUpperArm": (0, 0, -25),
        "LeftLowerArm": (0, 45, 0), "RightLowerArm": (0, -45, 0),
        "LeftUpperLeg": (12, 0, 0), "RightUpperLeg": (12, 0, 0),
        "LeftLowerLeg": (10, 0, 0), "RightLowerLeg": (10, 0, 0),
    },
    "body_wave_high": {
        "Hips": (-12, 0, 0), "Spine": (6, 0, 0), "Chest": (14, 0, 0),
        "Neck": (-6, 0, 0), "Head": (-8, 0, 0),
        "LeftUpperArm": (0, 0, 45), "RightUpperArm": (0, 0, -45),
        "LeftLowerArm": (0, 55, 0), "RightLowerArm": (0, -55, 0),
    },
    "step_left": {
        "Hips": (0, -8, 5), "Spine": (0, 4, -3), "Chest": (0, 3, -3),
        "Head": (0, 2, 2),
        "LeftUpperLeg": (22, 0, 12), "LeftLowerLeg": (-12, 0, 0),
        "RightUpperLeg": (-6, 0, -4), "RightLowerLeg": (8, 0, 0),
        "LeftUpperArm": (0, 0, 22), "RightUpperArm": (0, 0, -14),
        "LeftLowerArm": (0, 35, 0), "RightLowerArm": (0, -35, 0),
    },
    "step_right": {
        "Hips": (0, 8, -5), "Spine": (0, -4, 3), "Chest": (0, -3, 3),
        "Head": (0, -2, -2),
        "RightUpperLeg": (22, 0, -12), "RightLowerLeg": (-12, 0, 0),
        "LeftUpperLeg": (-6, 0, 4), "LeftLowerLeg": (8, 0, 0),
        "RightUpperArm": (0, 0, -22), "LeftUpperArm": (0, 0, 14),
        "RightLowerArm": (0, -35, 0), "LeftLowerArm": (0, 35, 0),
    },
    "kick_left": {
        "Hips": (0, 0, 10), "Chest": (0, 0, -5), "Head": (0, 0, -4),
        "LeftUpperLeg": (48, 0, 6), "LeftLowerLeg": (-35, 0, 0),
        "RightUpperLeg": (-5, 0, 0), "RightLowerLeg": (5, 0, 0),
        "LeftUpperArm": (0, 0, 30), "RightUpperArm": (0, 0, -30),
    },
    "kick_right": {
        "Hips": (0, 0, -10), "Chest": (0, 0, 5), "Head": (0, 0, 4),
        "RightUpperLeg": (48, 0, -6), "RightLowerLeg": (-35, 0, 0),
        "LeftUpperLeg": (-5, 0, 0), "LeftLowerLeg": (5, 0, 0),
        "RightUpperArm": (0, 0, -30), "LeftUpperArm": (0, 0, 30),
    },
    "lean_back": {
        "Hips": (-8, 0, 0), "Spine": (-8, 0, 0), "Chest": (-10, 0, 0),
        "Neck": (-4, 0, 0), "Head": (-6, 0, 0),
        "LeftUpperArm": (0, 0, 30), "RightUpperArm": (0, 0, -30),
    },
    "bow": {
        "Hips": (6, 0, 0), "Spine": (10, 0, 0), "Chest": (20, 0, 0),
        "Neck": (6, 0, 0), "Head": (8, 0, 0),
        "LeftUpperArm": (0, 0, 8), "RightUpperArm": (0, 0, -8),
    },
    "crouch": {
        "Hips": (12, 0, 0), "Spine": (10, 0, 0), "Chest": (8, 0, 0),
        "Head": (-4, 0, 0),
        "LeftUpperLeg": (35, 0, 4), "RightUpperLeg": (35, 0, -4),
        "LeftLowerLeg": (-28, 0, 0), "RightLowerLeg": (-28, 0, 0),
        "LeftUpperArm": (0, 0, 25), "RightUpperArm": (0, 0, -25),
        "LeftLowerArm": (0, 45, 0), "RightLowerArm": (0, -45, 0),
    },
    "spin_mid": {
        "Hips": (0, 180, 0), "Spine": (0, -20, 0), "Chest": (0, -15, 0),
        "LeftUpperArm": (0, 0, 55), "RightUpperArm": (0, 0, -55),
        "LeftLowerArm": (0, 25, 0), "RightLowerArm": (0, -25, 0),
    },
}

POSES: dict[str, BonePose] = {
    name: BonePose(data) for name, data in _RAW_POSES.items()
}

POSE_EASES = ("linear", "smooth", "snap", "soft")


def pose(name: str, *, mirror: bool = False) -> BonePose:
    if name not in POSES:
        raise ValueError(f"unknown pose: {name!r}; use one of {tuple(POSES)}")
    p = POSES[name]
    return _mirror(p) if mirror else BonePose(dict(p.euler))


@dataclass(frozen=True)
class PoseKey:
    at: float
    pose: str
    hold: float = 0.0
    ease: str = "smooth"
    mirror: bool = False

    def __post_init__(self) -> None:
        if self.pose not in POSES:
            raise ValueError(f"unknown pose: {self.pose!r}")
        if self.ease not in POSE_EASES:
            raise ValueError(f"ease must be one of {POSE_EASES}")
        if self.at < 0 or self.hold < 0:
            raise ValueError("pose at/hold must be >= 0")


@dataclass
class PoseProgram:
    """A key-pose dance: poses on a beat grid, interpolated with easing."""

    bpm: float = 120.0
    keys: list[PoseKey] = field(default_factory=list)
    loop: bool = True
    name: str = ""
    loop_transition: float = 0.5

    @property
    def total_beats(self) -> float:
        base = max((k.at + k.hold for k in self.keys), default=0.0)
        return base + (self.loop_transition if self.loop else 0.0)

    @property
    def duration(self) -> float:
        return self.total_beats * 60.0 / self.bpm if self.bpm > 0 else 0.0

    def _keyframes(self) -> list[PoseKey]:
        keys = list(self.keys)
        if self.loop and keys:
            keys.append(PoseKey(self.total_beats, keys[0].pose,
                                ease="smooth", mirror=keys[0].mirror))
        return keys

    def sample(self, elapsed: float) -> BonePose:
        keys = self._keyframes()
        if not keys or self.bpm <= 0:
            return BonePose()
        beat = elapsed * self.bpm / 60.0
        total = self.total_beats
        if self.loop:
            beat = beat % total
        elif beat >= total:
            return BonePose()
        prev = keys[0]
        nxt = keys[0]
        for i, key in enumerate(keys):
            if key.at <= beat + 1e-9:
                prev = key
                nxt = keys[i + 1] if i + 1 < len(keys) else key
            else:
                break
        target = pose(nxt.pose, mirror=nxt.mirror)
        start = pose(prev.pose, mirror=prev.mirror)
        if nxt is prev:
            return start
        span = max(1e-9, nxt.at - prev.at - prev.hold)
        local = beat - prev.at - prev.hold
        t = min(1.0, max(0.0, local / span))
        if local <= 0:
            return start
        if t >= 1:
            return target
        return blend_pose(start, target, _ease(t, prev.ease))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PoseProgram":
        bpm = float(data.get("bpm", 120.0))
        if not 40.0 <= bpm <= 240.0:
            raise ValueError("bpm must be between 40 and 240")
        raw_keys = data.get("poses")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise ValueError("poses must be a non-empty list")
        if len(raw_keys) > 48:
            raise ValueError("poses must contain at most 48 entries")
        keys: list[PoseKey] = []
        for raw in raw_keys:
            if not isinstance(raw, dict):
                raise ValueError("each pose key must be an object")
            at = float(raw.get("at", 0.0))
            hold = float(raw.get("hold", 0.0))
            keys.append(PoseKey(
                at=at,
                pose=str(raw.get("pose", "")),
                hold=hold,
                ease=str(raw.get("ease", "smooth")),
                mirror=bool(raw.get("mirror", False)),
            ))
        keys.sort(key=lambda k: k.at)
        total = max(k.at + k.hold for k in keys)
        if total > 128:
            raise ValueError("dance is too long (max 128 beats)")
        transition = float(data.get("loop_transition", 0.5))
        if not 0.0 <= transition <= 4.0:
            raise ValueError("loop_transition must be between 0 and 4 beats")
        return cls(bpm=bpm, keys=keys, loop=bool(data.get("loop", True)),
                   name=str(data.get("name", "")), loop_transition=transition)


def _ease(t: float, kind: str) -> float:
    t = min(1.0, max(0.0, t))
    if kind == "linear":
        return t
    if kind == "snap":
        return 1.0 - (1.0 - t) ** 3
    if kind == "soft":
        return t * t * (3.0 - 2.0 * t)
    return _smoothstep(t)


def parse_dance(data: dict[str, Any]):
    if not isinstance(data, dict):
        raise ValueError("dance program must be an object")
    if "poses" in data:
        return PoseProgram.from_dict(data)
    if "steps" in data:
        return DanceProgram.from_dict(data)
    raise ValueError("dance program needs either 'poses' or 'steps'")
