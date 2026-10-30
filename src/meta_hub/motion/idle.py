"""Idle layer: breathing, micro-sway and random blinks (design D10, task 5.4).

Runs whenever the agent is not speaking or gesturing, so the avatar never
looks like a frozen statue.  Everything is a pure function of time, which makes
it testable and keeps it on the same media clock as speech.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .bones import BonePose


@dataclass
class IdleLayer:
    breath_period: float = 4.0
    breath_amplitude: float = 1.4       # degrees on Chest
    sway_amplitude: float = 1.6         # degrees on Head / Neck
    blink_min_interval: float = 2.5
    blink_max_interval: float = 7.0
    blink_duration: float = 0.16
    seed: int = 7
    enabled: bool = True
    _blinks: list[float] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        self._rng = rng
        self._blinks = []
        self._schedule_next_blink(0.0)

    def _schedule_next_blink(self, now: float) -> None:
        interval = self._rng.uniform(self.blink_min_interval, self.blink_max_interval)
        self._blinks.append(now + interval)

    def _blink_weight(self, t: float) -> float:
        while self._blinks and t > self._blinks[-1] + self.blink_duration:
            self._schedule_next_blink(self._blinks[-1])
        for start in self._blinks:
            if start <= t <= start + self.blink_duration:
                phase = (t - start) / self.blink_duration
                return 1.0 - abs(2.0 * phase - 1.0)
        return 0.0

    def sample(self, t: float) -> tuple[BonePose, dict[str, float]]:
        if not self.enabled:
            return BonePose(), {}
        breath = self.breath_amplitude * math.sin(2 * math.pi * t / self.breath_period)
        sway = (self.sway_amplitude * math.sin(2 * math.pi * t / 7.3)
                + 0.5 * self.sway_amplitude * math.sin(2 * math.pi * t / 11.7))
        pose = BonePose({
            "Hips": (0.0, sway * 0.18, 0.0),
            "Spine": (breath * 0.2, sway * 0.28, breath * 0.1),
            "Chest": (breath * 0.4, 0.0, breath * 0.15),
            "Neck": (-breath * 0.2, sway * 0.25, 0.0),
            "Head": (breath * 0.25, sway, sway * 0.3),
            "LeftUpperArm": (0.0, 0.0, breath * 0.35),
            "RightUpperArm": (0.0, 0.0, -breath * 0.35),
        })
        blink = self._blink_weight(t)
        weights = {"Blink": blink, "Blink_L": blink, "Blink_R": blink}
        return pose, weights

    def motion_range(self, seconds: float, samples: int = 240) -> float:
        """Total variation of the head pose over a window (for verification)."""
        if samples < 2:
            return 0.0
        total = 0.0
        prev: BonePose | None = None
        for i in range(samples):
            pose, _ = self.sample(seconds * i / (samples - 1))
            if prev is not None:
                for bone, rot in pose.euler.items():
                    before = prev.euler.get(bone, (0.0, 0.0, 0.0))
                    total += sum(abs(a - b) for a, b in zip(rot, before))
            prev = pose
        return total
