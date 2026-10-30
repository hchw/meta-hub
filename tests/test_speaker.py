from __future__ import annotations

import threading
import unittest

from meta_hub.speaker import PlayerSpeaker


class FakePlayer:
    def __init__(self):
        self.frames = []

    def set_face_weights(self, weights):
        self.frames.append(dict(weights))


class SpeakerTest(unittest.TestCase):
    def build(self, frames):
        player = FakePlayer()
        speaker = PlayerSpeaker(
            player, profile="vrm1", play_audio=False,
            synth=lambda text, path: path,
            frames=lambda wav: frames,
            sleep=lambda s: None,
        )
        return speaker, player

    def test_frames_reach_player_and_reset(self):
        speaker, player = self.build([([], {"JawOpen": 1.0}, 0.0)])
        speaker.speak("hi", 0.01, threading.Event())
        self.assertEqual(player.frames[0], {"aa": 1.0})
        self.assertEqual(player.frames[-1], {})

    def test_cancel_stops_before_frames(self):
        speaker, player = self.build([([], {"JawOpen": 1.0}, 10.0)])
        ev = threading.Event()
        ev.set()
        speaker.speak("hi", 1.0, ev)
        self.assertEqual(player.frames, [{}])

    def test_empty_synthesis_does_nothing(self):
        player = FakePlayer()
        speaker = PlayerSpeaker(
            player, play_audio=False, synth=lambda t, p: None,
            frames=lambda w: [], sleep=lambda s: None,
        )
        speaker.speak("", 1.0, threading.Event())
        self.assertEqual(player.frames, [])

    def test_prepare_caches_synthesis_and_a2f(self):
        calls = {"synth": 0, "frames": 0}

        def synth(text, path):
            calls["synth"] += 1
            return path

        def frames(wav):
            calls["frames"] += 1
            return [([], {"JawOpen": 1.0}, 0.0)]

        player = FakePlayer()
        speaker = PlayerSpeaker(
            player, play_audio=False, synth=synth, frames=frames,
            sleep=lambda s: None,
        )
        speaker.prepare(["hello"])
        speaker.speak("hello", 0.01, threading.Event())
        self.assertEqual(calls, {"synth": 1, "frames": 1})

    def test_wait_is_interruptible(self):
        speaker, _ = self.build([])
        ev = threading.Event()
        ev.set()
        speaker.wait(10.0, ev)  # returns immediately


if __name__ == "__main__":
    unittest.main()
