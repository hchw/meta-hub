from __future__ import annotations

import threading
import unittest

from meta_hub.agent.llm import parse_plan
from meta_hub.timeline import (TimelineCompiler, TimelineExecutor,
                               estimate_duration)


def call(tool, **args):
    return {"function": {"name": tool, "arguments": args}}


class FakeSpeaker:
    def __init__(self, on_speak=None, block=False):
        self.spoken: list[str] = []
        self.waits: list[float] = []
        self.stops = 0
        self.on_speak = on_speak
        self.block = block
        self.started = threading.Event()

    def speak(self, text, duration, cancelled):
        self.spoken.append(text)
        self.started.set()
        if self.on_speak:
            self.on_speak(text)
        if self.block:
            cancelled.wait(2.0)

    def wait(self, seconds, cancelled):
        self.waits.append(seconds)

    def stop(self):
        self.stops += 1


class FakeGestures:
    def __init__(self, log=None):
        self.played = []
        self.cancelled = 0
        self.log = log

    def play(self, name, intensity, duration):
        self.played.append((name, intensity, duration))
        if self.log is not None:
            self.log.append(f"gesture:{name}")

    def cancel_all(self):
        self.cancelled += 1


class FakeDances:
    def __init__(self):
        self.played = []
        self.cancelled = 0

    def play_dance(self, program):
        self.played.append(program)

    def cancel_all(self):
        self.cancelled += 1


class FakeExpressions:
    def __init__(self, log=None):
        self.sets = []
        self.log = log

    def set(self, name, weight):
        self.sets.append((name, weight))
        if self.log is not None:
            self.log.append(f"expression:{name}")


def executor(speaker=None, gestures=None, expressions=None, dances=None):
    return TimelineExecutor(speaker or FakeSpeaker(), gestures or FakeGestures(),
                            expressions or FakeExpressions(), dances=dances)


class CompilerTest(unittest.TestCase):
    def test_gesture_does_not_consume_speech_time(self):
        plan = parse_plan([
            call("gesture", name="nod", intensity=0.7, duration=1.0),
            call("speak", text="第一句。"),
            call("speak", text="第二句。"),
        ])
        timeline = TimelineCompiler(lambda t: 1.0).compile(plan)
        self.assertEqual([i.start for i in timeline.speech], [0.0, 1.0])
        self.assertEqual(timeline.speech[0].start, 0.0)
        self.assertEqual(timeline.gestures[0].start, 0.0)
        self.assertAlmostEqual(timeline.duration, 2.0)

    def test_wait_consumes_time_and_expression_persists(self):
        plan = parse_plan([
            call("set_expression", name="joy", weight=0.9),
            call("speak", text="a"),
            call("gesture", name="tilt"),
            call("wait", seconds=0.5),
            call("speak", text="b"),
        ])
        timeline = TimelineCompiler(lambda t: 1.0).compile(plan)
        speaks = [i for i in timeline.speech if i.kind == "speak"]
        self.assertEqual([i.start for i in speaks], [0.0, 1.5])
        self.assertAlmostEqual(timeline.duration, 2.5)
        self.assertEqual([e.name for e in timeline.expressions], ["joy"])

    def test_gesture_after_speak_still_overlays_that_sentence(self):
        plan = parse_plan([
            call("speak", text="第一句。"),
            call("gesture", name="dance", duration=2.0),
        ])
        timeline = TimelineCompiler(lambda t: 1.0).compile(plan)
        self.assertEqual(timeline.gestures[0].start, 0.0)

    def test_choreograph_compiles_to_dance_overlay(self):
        plan = parse_plan([call("choreograph", bpm=120, steps=[
            {"at": 0, "move": "bounce", "beats": 2},
            {"at": 2, "move": "clap", "beats": 2},
        ])])
        timeline = TimelineCompiler(lambda t: 2.0).compile(plan)
        self.assertEqual(len(timeline.dances), 1)
        self.assertEqual(timeline.dances[0].start, 0.0)
        self.assertEqual(timeline.dances[0].program.total_beats, 4.0)

    def test_choreograph_after_speak_still_overlays_sentence(self):
        plan = parse_plan([
            call("speak", text="跳起来。"),
            call("choreograph", steps=[{"move": "bounce", "beats": 2}]),
        ])
        timeline = TimelineCompiler(lambda t: 1.0).compile(plan)
        self.assertEqual(timeline.dances[0].start, 0.0)

    def test_do_nothing_yields_empty_timeline(self):
        timeline = TimelineCompiler().compile(
            parse_plan([call("do_nothing", reason="quiet")]))
        self.assertEqual(timeline.speech, [])
        self.assertEqual(timeline.duration, 0.0)

    def test_default_estimator(self):
        self.assertGreater(estimate_duration("a" * 50), estimate_duration("a"))


class ExecutorTest(unittest.TestCase):
    def test_gesture_and_speech_are_parallel(self):
        log = []
        speaker = FakeSpeaker(on_speak=lambda text: log.append(f"speak:{text}"))
        gestures = FakeGestures(log)
        expressions = FakeExpressions(log)
        ex = executor(speaker, gestures, expressions)
        plan = parse_plan([
            call("gesture", name="nod", intensity=0.8, duration=1.0),
            call("speak", text="你好。"),
        ])
        result = ex.play_plan(plan, TimelineCompiler(lambda t: 0.5))
        self.assertTrue(result.completed)
        self.assertEqual(gestures.played[0][0], "nod")
        self.assertEqual(log[:2], ["expression:neutral", "gesture:nod"])
        self.assertIn("speak:你好。", log)
        self.assertEqual(result.played_seconds, 0.5)

    def test_dance_player_receives_program(self):
        dances = FakeDances()
        ex = executor(dances=dances)
        plan = parse_plan([call("choreograph", steps=[
            {"move": "bounce", "beats": 1}], bpm=120)])
        ex.play_plan(plan, TimelineCompiler(lambda t: 1.0))
        self.assertEqual(len(dances.played), 1)

    def test_expression_persists_until_changed(self):
        speaker = FakeSpeaker()
        expressions = FakeExpressions()
        ex = executor(speaker, expressions=expressions)
        plan = parse_plan([
            call("set_expression", name="joy", weight=0.9),
            call("speak", text="a"),
            call("speak", text="b"),
            call("set_expression", name="sad", weight=0.5),
            call("speak", text="c"),
        ])
        ex.play_plan(plan, TimelineCompiler(lambda t: 0.1))
        names = [name for name, _ in expressions.sets]
        self.assertEqual(names, ["neutral", "joy", "sad", "neutral"])

    def test_soft_interrupt_waits_for_sentence_boundary(self):
        speaker = FakeSpeaker()
        ex = executor(speaker)
        speaker.on_speak = lambda text: ex.request_soft("ordinary_comment")
        plan = parse_plan([
            call("speak", text="第一句。"),
            call("speak", text="第二句。"),
        ])
        result = ex.play_plan(plan, TimelineCompiler(lambda t: 0.1))
        self.assertEqual(speaker.spoken, ["第一句。"])
        self.assertEqual(result.soft_reason, "ordinary_comment")
        self.assertFalse(result.completed)

    def test_hard_interrupt_stops_immediately_and_is_idempotent(self):
        speaker = FakeSpeaker(block=True)
        gestures = FakeGestures()
        expressions = FakeExpressions()
        ex = executor(speaker, gestures, expressions)
        plan = parse_plan([
            call("speak", text="很长的一句话。"),
            call("speak", text="不该出现。"),
        ])
        thread = threading.Thread(
            target=lambda: ex.play_plan(plan, TimelineCompiler(lambda t: 5.0)))
        thread.start()
        self.assertTrue(speaker.started.wait(1.0))
        ex.request_hard("big_gift")
        ex.request_hard("big_gift")
        thread.join(2.0)
        self.assertEqual(speaker.stopped if hasattr(speaker, "stopped") else speaker.stops, 2)
        self.assertNotIn("不该出现。", speaker.spoken)
        self.assertEqual(ex.hard_cancels, 1)
        self.assertGreaterEqual(gestures.cancelled, 1)
        self.assertEqual(expressions.sets[-1], ("neutral", 1.0))


if __name__ == "__main__":
    unittest.main()
