"""VMC bone output, procedural gestures and the idle layer."""
from .bones import (BonePose, DEFAULT_OWNERSHIP, DRIVEN_BONES, MotionSender,
                    Ownership, VmcBoneSender, euler_to_quaternion, make_motion_sender)
from .idle import IdleLayer
from .player import VmcMotionPlayer, expression_weights
from .primitives import GESTURES, GestureClip, gesture_pose, make_gesture

__all__ = ["BonePose", "DEFAULT_OWNERSHIP", "DRIVEN_BONES", "MotionSender",
           "Ownership", "VmcBoneSender", "euler_to_quaternion", "make_motion_sender",
           "IdleLayer",
           "GESTURES", "GestureClip", "gesture_pose", "make_gesture",
           "VmcMotionPlayer", "expression_weights"]
