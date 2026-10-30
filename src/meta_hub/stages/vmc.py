"""Sink stage: ARKit weights -> VMC (OSC/UDP) -> VMC renderer (VNyan, VSeeFace, ...)."""
from __future__ import annotations

import time

from pythonosc.udp_client import SimpleUDPClient

# A2F/ARKit -> VRM 0.x blendshape names (lossy: 52+ names -> ~15).
ARKIT_TO_VRM: dict[str, list[tuple[str, float]]] = {
    "JawOpen": [("A", 1.0)],
    "MouthFunnel": [("O", 1.0)],
    "MouthPucker": [("U", 1.0)],
    "MouthStretchLeft": [("I", 0.5)],
    "MouthStretchRight": [("I", 0.5)],
    "MouthSmileLeft": [("Joy", 0.6)],
    "MouthSmileRight": [("Joy", 0.6)],
    "EyeBlinkLeft": [("Blink_L", 1.0), ("Blink", 0.5)],
    "EyeBlinkRight": [("Blink_R", 1.0), ("Blink", 0.5)],
    "EyeLookUpLeft": [("LookUp", 0.5)],
    "EyeLookUpRight": [("LookUp", 0.5)],
    "EyeLookDownLeft": [("LookDown", 0.5)],
    "EyeLookDownRight": [("LookDown", 0.5)],
    "EyeLookInLeft": [("LookLeft", 0.5)],
    "EyeLookOutLeft": [("LookRight", 0.5)],
    "EyeLookInRight": [("LookRight", 0.5)],
    "EyeLookOutRight": [("LookLeft", 0.5)],
    "BrowDownLeft": [("Angry", 0.5)],
    "BrowDownRight": [("Angry", 0.5)],
    "BrowInnerUp": [("Sorrow", 0.4)],
}

VRM_NAMES = ["A", "I", "U", "E", "O", "Blink", "Blink_L", "Blink_R",
             "LookUp", "LookDown", "LookLeft", "LookRight",
             "Joy", "Angry", "Sorrow", "Fun", "Neutral"]

VRM1_NAMES = ["aa", "ih", "ou", "ee", "oh", "blink", "blinkLeft", "blinkRight",
              "lookUp", "lookDown", "lookLeft", "lookRight",
              "happy", "angry", "sad", "relaxed", "surprised", "neutral"]

# VRM 0.x -> VRM 1.0 preset expressions (VMC spec compatibility table).
VRM0_TO_VRM1: dict[str, str] = {
    "Joy": "happy",
    "Angry": "angry",
    "Sorrow": "sad",
    "Fun": "relaxed",
    "A": "aa",
    "I": "ih",
    "U": "ou",
    "E": "ee",
    "O": "oh",
    "Blink": "blink",
    "Blink_L": "blinkLeft",
    "Blink_R": "blinkRight",
    "LookUp": "lookUp",
    "LookDown": "lookDown",
    "LookLeft": "lookLeft",
    "LookRight": "lookRight",
    "Neutral": "neutral",
}


def blend_names_for(profile: str = "vrm0") -> list[str]:
    if profile not in ("vrm0", "vrm1"):
        raise ValueError(f"unknown blend profile: {profile!r}")
    return list(VRM1_NAMES if profile == "vrm1" else VRM_NAMES)


def convert_profile_weights(weights: dict[str, float],
                            profile: str = "vrm0") -> dict[str, float]:
    """Translate VRM0 names to the selected profile.

    The VMC spec asks senders to use VRM0 names and receivers to convert, but a
    profile switch is useful when a renderer does not convert correctly.
    """
    if profile != "vrm1":
        return dict(weights)
    out: dict[str, float] = {}
    for name, value in weights.items():
        key = VRM0_TO_VRM1.get(name, name)
        out[key] = max(out.get(key, 0.0), value)
    return out


def arkit_to_vrm(named: dict[str, float], mouth_gain: float = 1.0,
                 profile: str = "vrm0") -> dict[str, float]:
    out: dict[str, float] = {}
    for a, w in named.items():
        for v, gain in ARKIT_TO_VRM.get(a, []):
            out[v] = out.get(v, 0.0) + w * gain
    out = {k: max(0.0, min(1.0, v)) for k, v in out.items()}
    if mouth_gain != 1.0:
        # Optional boost when the renderer dilutes VMC (e.g. camera tracking blended in).
        for k in ("A", "I", "U", "E", "O"):
            if k in out:
                out[k] = max(0.0, min(1.0, out[k] * mouth_gain))
    return convert_profile_weights(out, profile)


class VmcSender:
    def __init__(self, host: str = "127.0.0.1", port: int = 39539,
                 profile: str = "vrm0"):
        self.client = SimpleUDPClient(host, port)
        self.profile = profile
        self.names = blend_names_for(profile)

    def send(self, vrm_weights: dict[str, float]) -> None:
        self.client.send_message("/VMC/Ext/OK", 1)
        self.client.send_message("/VMC/Ext/T", time.time())
        for name in self.names:
            self.client.send_message("/VMC/Ext/Blend/Val",
                                     (name, float(vrm_weights.get(name, 0.0))))
        self.client.send_message("/VMC/Ext/Blend/Apply", 1)

    def send_neutral(self, hold: float = 0.3, fps: float = 30.0) -> None:
        """Hold all blendshapes at 0 so the face returns to neutral after speech (task 4.2)."""
        end = time.monotonic() + max(0.0, hold)
        while True:
            self.send({})
            if time.monotonic() >= end:
                break
            time.sleep(1.0 / max(1.0, fps))
