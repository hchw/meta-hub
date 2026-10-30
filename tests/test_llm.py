from __future__ import annotations

import unittest

from meta_hub.agent.llm import (LLMClient, ToolCallError, parse_plan,
                                validate_calls, ToolCall)


def call(tool, **args):
    return {"function": {"name": tool, "arguments": args}}


class ParsePlanTest(unittest.TestCase):
    def test_multiple_ordered_tool_calls(self):
        plan = parse_plan([
            call("gesture", name="nod", intensity=0.5, duration=0.8),
            call("speak", text="你好呀。"),
            call("set_expression", name="joy", weight=0.8),
            call("wait", seconds=0.4),
            call("speak", text="欢迎来到直播间。"),
        ])
        self.assertIsNone(plan.error)
        self.assertEqual([c.name for c in plan.calls],
                         ["gesture", "speak", "set_expression", "wait", "speak"])
        self.assertTrue(plan.has_actions)

    def test_do_nothing_only_makes_no_actions(self):
        plan = parse_plan([call("do_nothing", reason="nothing worth saying")])
        self.assertFalse(plan.has_actions)
        self.assertEqual(plan.explanation, "nothing worth saying")

    def test_json_string_arguments(self):
        plan = parse_plan([{"name": "speak", "arguments": '{"text": "hi"}'}])
        self.assertIsNone(plan.error)
        self.assertEqual(plan.calls[0].arguments["text"], "hi")

    def test_unknown_tool_rejected(self):
        plan = parse_plan([call("rm_rf")])
        self.assertIn("unknown tool", plan.error or "")

    def test_invalid_ranges_rejected(self):
        plan = parse_plan([call("gesture", name="nod", intensity=3)])
        self.assertIsNotNone(plan.error)
        plan = parse_plan([call("wait", seconds=999)])
        self.assertIsNotNone(plan.error)

    def test_choreograph_is_validated(self):
        plan = parse_plan([call("choreograph", bpm=120, steps=[
            {"at": 0, "move": "bounce", "beats": 2},
            {"at": 2, "move": "clap", "beats": 2},
        ])])
        self.assertIsNone(plan.error)
        bad = parse_plan([call("choreograph", steps=[
            {"move": "backflip", "beats": 1},
        ])])
        self.assertIn("unknown move", bad.error or "")
        poses = parse_plan([call("choreograph", bpm=120, poses=[
            {"at": 0, "pose": "center"},
            {"at": 2, "pose": "hip_left", "ease": "snap"},
        ])])
        self.assertIsNone(poses.error)

    def test_direct_validation(self):
        with self.assertRaises(ToolCallError):
            validate_calls([ToolCall("speak", {"text": ""})])


class LLMClientTest(unittest.TestCase):
    def test_transport_response_is_parsed(self):
        def transport(messages, tools):
            self.assertEqual(messages[0]["role"], "system")
            return {"choices": [{"message": {"tool_calls": [
                call("speak", text="hi"),
                call("do_nothing"),
            ]}}]}

        client = LLMClient("http://x", "k", "m", transport=transport)
        plan = client.complete("system", [{"role": "user", "content": "u"}])
        self.assertIsNone(plan.error)
        self.assertTrue(plan.has_actions)

    def test_transport_failure_isolated(self):
        def transport(messages, tools):
            raise TimeoutError("slow")

        plan = LLMClient("http://x", "k", "m", transport=transport).complete("s", [])
        self.assertIsNotNone(plan.error)
        self.assertIn("llm_error", plan.error)

    def test_malformed_response(self):
        plan = LLMClient("http://x", "k", "m",
                         transport=lambda m, t: {"oops": 1}).complete("s", [])
        self.assertIsNotNone(plan.error)


if __name__ == "__main__":
    unittest.main()
