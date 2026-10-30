"""VMC bone output (design D8/D9, tasks 5.2/5.5).

Frames are small Euler rotations relative to the rest pose, sent as VMC
``/VMC/Ext/Bone/Pos`` messages.  We drive the full humanoid body (not just the
head) so gestures can use arms, hips, spine and legs.  The same sender still
emits blendshape frames, so face and body share one clock.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pythonosc.udp_client import SimpleUDPClient

# Bones this system owns.  The renderer must disable its own tracking for
# exactly these parts, otherwise the motion is diluted (design D9).
DRIVEN_BONES = (
    "Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
    "LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
    "RightUpperLeg", "RightLowerLeg", "RightFoot",
)

# Explicit ownership map; persisted next to the runtime config for operators.
DEFAULT_OWNERSHIP: dict[str, str] = {
    "Head": "vmc", "Neck": "vmc", "Chest": "vmc", "UpperChest": "vmc",
    "Spine": "vmc", "Hips": "vmc",
    "LeftShoulder": "vmc", "LeftUpperArm": "vmc", "LeftLowerArm": "vmc", "LeftHand": "vmc",
    "RightShoulder": "vmc", "RightUpperArm": "vmc", "RightLowerArm": "vmc", "RightHand": "vmc",
    "LeftUpperLeg": "vmc", "LeftLowerLeg": "vmc", "LeftFoot": "vmc",
    "RightUpperLeg": "vmc", "RightLowerLeg": "vmc", "RightFoot": "vmc",
    "Fingers": "renderer", "Toes": "renderer", "Eyes": "renderer",
}


@dataclass
class BonePose:
    """Euler rotations in degrees, relative to the rest pose."""

    euler: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    def merged(self, other: "BonePose") -> "BonePose":
        out = {k: tuple(v) for k, v in self.euler.items()}
        for bone, rot in other.euler.items():
            a = out.get(bone, (0.0, 0.0, 0.0))
            out[bone] = (a[0] + rot[0], a[1] + rot[1], a[2] + rot[2])
        return BonePose(out)

    def is_neutral(self, eps: float = 1e-9) -> bool:
        return all(abs(v) < eps for rot in self.euler.values() for v in rot)


NEUTRAL = BonePose()


def euler_to_quaternion(rx: float, ry: float, rz: float) -> tuple[float, float, float, float]:
    """XYZ Euler degrees -> quaternion (x, y, z, w)."""
    hx, hy, hz = (math.radians(v) * 0.5 for v in (rx, ry, rz))
    cx, sx = math.cos(hx), math.sin(hx)
    cy, sy = math.cos(hy), math.sin(hy)
    cz, sz = math.cos(hz), math.sin(hz)
    return (
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    )


class VmcBoneSender:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 39539,
        driven_bones: tuple[str, ...] = DRIVEN_BONES,
        send_bone_apply: bool = False,
        send_root: bool = False,
    ) -> None:
        self.client = SimpleUDPClient(host, port)
        self.driven_bones = driven_bones
        self.send_bone_apply = send_bone_apply
        self.send_root = send_root
        self.sent_frames = 0
        self.last_pose = BonePose()

    def send(self, pose: BonePose) -> None:
        self.client.send_message("/VMC/Ext/OK", 1)
        self.client.send_message("/VMC/Ext/T", time.time())
        if self.send_root:
            # Identity root pose; some receivers require it before bones apply.
            self.client.send_message(
                "/VMC/Ext/Root/Pos",
                ("root", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            )
        for bone in self.driven_bones:
            rot = pose.euler.get(bone, (0.0, 0.0, 0.0))
            qx, qy, qz, qw = euler_to_quaternion(*rot)
            self.client.send_message(
                "/VMC/Ext/Bone/Pos",
                (bone, 0.0, 0.0, 0.0, qx, qy, qz, qw),
            )
        if self.send_bone_apply:
            # Non-standard; kept only for renderers that expect it.
            self.client.send_message("/VMC/Ext/Bone/Apply", 1)
        self.sent_frames += 1
        self.last_pose = pose

    def send_neutral(self) -> None:
        self.send(NEUTRAL)


def make_motion_sender() -> "MotionSender":
    """MotionSender configured from environment settings (production path)."""
    from ..config import settings

    return MotionSender(
        settings.vmc_host,
        settings.vmc_port,
        send_bones=settings.vmc_bones,
        send_bone_apply=settings.vmc_bone_apply,
        send_root=settings.vmc_root,
        profile=settings.vmc_blend_profile,
    )


class MotionSender:
    """Sends bones and blendshapes on the same VMC connection."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 39539,
        vrm_names: list[str] | None = None,
        driven_bones: tuple[str, ...] = DRIVEN_BONES,
        send_bones: bool = True,
        send_bone_apply: bool = False,
        send_root: bool = False,
        profile: str = "vrm0",
    ) -> None:
        from ..stages.vmc import blend_names_for

        self.client = SimpleUDPClient(host, port)
        self.vrm_names = list(vrm_names or blend_names_for(profile))
        self.driven_bones = driven_bones
        self.send_bones = send_bones
        self.send_bone_apply = send_bone_apply
        self.send_root = send_root
        self.profile = profile
        self.last_pose = BonePose()
        self.last_weights: dict[str, float] = {}
        self.sent_frames = 0

    def send(self, pose: BonePose, weights: dict[str, float] | None = None) -> None:
        weights = weights or {}
        self.client.send_message("/VMC/Ext/OK", 1)
        self.client.send_message("/VMC/Ext/T", time.time())
        if self.send_root:
            self.client.send_message(
                "/VMC/Ext/Root/Pos",
                ("root", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
            )
        for name in self.vrm_names:
            self.client.send_message(
                "/VMC/Ext/Blend/Val", (name, float(weights.get(name, 0.0)))
            )
        self.client.send_message("/VMC/Ext/Blend/Apply", 1)
        if self.send_bones:
            for bone in self.driven_bones:
                rot = pose.euler.get(bone, (0.0, 0.0, 0.0))
                qx, qy, qz, qw = euler_to_quaternion(*rot)
                self.client.send_message(
                    "/VMC/Ext/Bone/Pos",
                    (bone, 0.0, 0.0, 0.0, qx, qy, qz, qw),
                )
        if self.send_bone_apply:
            self.client.send_message("/VMC/Ext/Bone/Apply", 1)
        self.last_pose = pose
        self.last_weights = weights
        self.sent_frames += 1

    def send_neutral(self) -> None:
        self.send(NEUTRAL, {})


@dataclass
class Ownership:
    """Which parts are driven by us vs. left to the renderer's tracking."""

    bones: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_OWNERSHIP))

    def validate(self, driven: tuple[str, ...] = DRIVEN_BONES) -> None:
        missing = [b for b in driven if self.bones.get(b) != "vmc"]
        if missing:
            raise ValueError(f"bones must be owned by vmc: {missing}")

    @classmethod
    def load(cls, path: str | Path) -> "Ownership":
        data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        known = set(DEFAULT_OWNERSHIP)
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown bones in ownership map: {sorted(unknown)}")
        merged = dict(DEFAULT_OWNERSHIP)
        merged.update({k: str(v) for k, v in data.items()})
        ownership = cls(merged)
        ownership.validate()
        return ownership

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.bones, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
