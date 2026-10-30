"""Concrete VMC player for the timeline executor (renderer-facing).

The executor talks to a ``GesturePlayer`` + ``ExpressionPlayer``; this is the
implementation that actually sends VMC frames.  It owns one background clock so
gestures, expressions, face weights (from A2F) and the idle layer share the same
output stream instead of racing each other on the UDP socket.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable

from ..stages.vmc import convert_profile_weights
from .bones import BonePose, MotionSender
from .choreography import DanceProgram
from .idle import IdleLayer
from .primitives import GestureClip, make_gesture

# Character expression name -> VRM 0.x blendshape weights.
EXPRESSION_VRM0: dict[str, dict[str, float]] = {
    "neutral": {},
    "joy": {"Joy": 1.0},
    "happy": {"Joy": 1.0},
    "sad": {"Sorrow": 1.0},
    "angry": {"Angry": 1.0},
    "surprised": {"Fun": 1.0},
    "shy": {"Joy": 0.4, "Sorrow": 0.2},
    "thinking": {"Sorrow": 0.3},
}

def expression_weights(name: str, weight: float = 1.0,
                       profile: str = "vrm0") -> dict[str, float]:
    base = EXPRESSION_VRM0.get(name, {})
    weights = {k: v * weight for k, v in base.items()}
    return convert_profile_weights(weights, profile)


class VmcMotionPlayer:
    """Sends bones + blendshapes at a fixed rate; thread-safe entry points."""

    def __init__(self, host: str = "127.0.0.1", port: int = 39539,
                 fps: float = 60.0, *, profile: str = "vrm0",
                 send_bones: bool = True, send_root: bool = False,
                 idle: IdleLayer | None = None,
                 sender: MotionSender | None = None,
                 autostart: bool = True,
                 smoothing: float = 0.12,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.sender = sender or MotionSender(
            host, port, profile=profile, send_bones=send_bones,
            send_root=send_root,
        )
        self.fps = max(1.0, fps)
        self.profile = profile
        self.idle = idle or IdleLayer()
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._clips: list[tuple[GestureClip, float]] = []
        self._dances: list[tuple[DanceProgram, float]] = []
        self._expression = ("neutral", 1.0)
        self._face: dict[str, float] = {}
        self._started_at = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent_frames = 0
        self._autostart = autostart
        # Exponential smoothing removes the robotic "snap" from procedural
        # gestures without adding visible input lag (~0.1s time constant).
        self.smoothing = max(0.0, float(smoothing))
        self._smooth_pose: dict[str, list[float]] = {}
        self._smooth_weights: dict[str, float] = {}
        self._last_frame_at: float | None = None

    @classmethod
    def from_settings(cls, **kwargs) -> "VmcMotionPlayer":
        from ..config import settings
        kwargs.setdefault("host", settings.vmc_host)
        kwargs.setdefault("port", settings.vmc_port)
        kwargs.setdefault("profile", settings.vmc_blend_profile)
        kwargs.setdefault("send_bones", settings.vmc_bones)
        kwargs.setdefault("send_root", settings.vmc_root)
        kwargs.setdefault("smoothing", settings.vmc_smoothing)
        return cls(**kwargs)

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._started_at = self._clock()
        self._thread = threading.Thread(target=self._loop, name="vmc-player", daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2.0)
        self._thread = None

    def _loop(self) -> None:
        interval = 1.0 / self.fps
        while not self._stop.is_set():
            self.send_frame()
            self._sleep(interval)

    # -- GesturePlayer / ExpressionPlayer ---------------------------------
    def play(self, name: str, intensity: float = 0.6,
             duration: float = 1.0) -> None:
        clip = make_gesture(name, intensity, duration)
        with self._lock:
            self._clips.append((clip, self._clock()))
        if self._autostart:
            self.start()

    def play_dance(self, program: DanceProgram) -> None:
        now = self._clock()
        with self._lock:
            self._dances = [(d, t) for d, t in self._dances
                            if d.loop or max(0.0, now - t) < d.duration]
            self._dances.append((program, now))
        if self._autostart:
            self.start()

    def cancel_all(self) -> None:
        with self._lock:
            self._clips.clear()
            self._dances.clear()
            self._expression = ("neutral", 1.0)
            self._face = {}
        self.sender.send_neutral()

    def set(self, name: str, weight: float = 1.0) -> None:
        with self._lock:
            self._expression = (name, max(0.0, min(1.0, float(weight))))

    # -- external A2F frames ----------------------------------------------
    def set_face_weights(self, weights: dict[str, float]) -> None:
        with self._lock:
            self._face = dict(weights)

    # -- frame composition ------------------------------------------------
    def send_frame(self, now: float | None = None) -> dict[str, float]:
        now = self._clock() if now is None else now
        elapsed = max(0.0, now - self._started_at)
        idle_pose, idle_weights = self.idle.sample(elapsed)
        with self._lock:
            active: list[GestureClip] = []
            motion = None
            for clip, started in self._clips:
                local = max(0.0, now - started)
                if local >= clip.duration:
                    continue
                active.append(clip)
                pose = clip.sample(local)
                motion = pose if motion is None else motion.merged(pose)
            self._clips = [(c, s) for c, s in self._clips if c in active]
            dances = []
            for program, started in self._dances:
                local = max(0.0, now - started)
                if not program.loop and local >= program.duration:
                    continue
                dances.append((program, started))
                pose = program.sample(local)
                motion = pose if motion is None else motion.merged(pose)
            self._dances = dances
        expr_name, expr_weight = self._expression
        face = dict(self._face)
        pose = idle_pose if motion is None else motion.merged(idle_pose)
        weights = dict(face)
        for key, value in idle_weights.items():
            weights[key] = max(weights.get(key, 0.0), value)
        for key, value in expression_weights(expr_name, expr_weight, self.profile).items():
            weights[key] = max(weights.get(key, 0.0), value)
        dt = (1.0 / self.fps) if self._last_frame_at is None else now - self._last_frame_at
        self._last_frame_at = now
        if self.smoothing > 0 and dt > 0:
            pose = self._smooth_bone_pose(pose, dt)
            weights = self._smooth_blendshapes(weights, dt)
        self.sender.send(pose, weights)
        self.sent_frames += 1
        return weights

    # -- smoothing --------------------------------------------------------
    def _smooth_bone_pose(self, pose: BonePose, dt: float) -> BonePose:
        alpha = 1.0 - math.exp(-dt / self.smoothing)
        keys = set(pose.euler) | set(self._smooth_pose)
        out: dict[str, tuple[float, float, float]] = {}
        for bone in keys:
            target = pose.euler.get(bone, (0.0, 0.0, 0.0))
            current = self._smooth_pose.get(bone, list(target))
            nxt = [c + (t - c) * alpha for c, t in zip(current, target)]
            if any(abs(v) > 1e-5 for v in nxt):
                self._smooth_pose[bone] = nxt
                out[bone] = (nxt[0], nxt[1], nxt[2])
            else:
                self._smooth_pose.pop(bone, None)
        return BonePose(out)

    def _smooth_blendshapes(self, weights: dict[str, float], dt: float) -> dict[str, float]:
        # Faces need to stay snappy: use a quarter of the body time constant.
        alpha = 1.0 - math.exp(-dt / max(0.01, self.smoothing * 0.25))
        keys = set(weights) | set(self._smooth_weights)
        out: dict[str, float] = {}
        for key in keys:
            target = float(weights.get(key, 0.0))
            current = self._smooth_weights.get(key, target)
            value = current + (target - current) * alpha
            if abs(value) > 1e-4:
                self._smooth_weights[key] = value
                out[key] = value
            else:
                self._smooth_weights.pop(key, None)
        return out
