"""LLM tool-calling boundary (design D4, task 3.3).

One model call returns an *ordered* list of tool calls; that list is the unit
the timeline compiler consumes.  The transport is injectable so the whole loop
can be tested without a network or an API key.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from ..motion.choreography import MOVES, POSE_EASES, POSES, parse_dance
from ..motion.primitives import GESTURES as _GESTURES

GESTURES = tuple(_GESTURES)
EXPRESSIONS = ("neutral", "joy", "sad", "angry", "surprised", "shy", "thinking")
MAX_WAIT_SECONDS = 10.0

TOOL_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "speak",
            "description": "Say one sentence out loud. Sentences are played in order.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "One sentence."}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gesture",
            "description": (
                "Overlay a head/body/arm gesture. Gestures do NOT consume "
                "speech time; they run in parallel with the current sentence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": list(GESTURES)},
                    "intensity": {"type": "number", "minimum": 0, "maximum": 1},
                    "duration": {"type": "number", "minimum": 0.1, "maximum": 10},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "choreograph",
            "description": (
                "Compose a multi-count dance from key poses (preferred) or "
                "looping moves. The runtime interpolates at 60fps; do not emit "
                "raw bone angles. Key poses give holds, easing and asymmetric "
                "weight shifts; use them for musical dances."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bpm": {"type": "number", "minimum": 40, "maximum": 240},
                    "loop": {"type": "boolean"},
                    "name": {"type": "string"},
                    "poses": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 48,
                        "description": "Preferred for musical key-pose dances.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "at": {"type": "number", "minimum": 0},
                                "pose": {"type": "string", "enum": list(POSES)},
                                "hold": {"type": "number", "minimum": 0},
                                "ease": {"type": "string", "enum": list(POSE_EASES)},
                                "mirror": {"type": "boolean"},
                            },
                            "required": ["pose"],
                        },
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {
                            "type": "object",
                            "properties": {
                                "at": {"type": "number", "minimum": 0},
                                "move": {"type": "string", "enum": list(MOVES)},
                                "beats": {"type": "number", "minimum": 0.25, "maximum": 8},
                                "intensity": {"type": "number", "minimum": 0, "maximum": 1},
                                "mirror": {"type": "boolean"},
                            },
                            "required": ["move", "beats"],
                        },
                    },
                },
                "anyOf": [{"required": ["poses"]}, {"required": ["steps"]}],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_expression",
            "description": "Set a persistent facial expression until changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": list(EXPRESSIONS)},
                    "weight": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Pause the sequence. Consumes time on the speech track.",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "number", "minimum": 0}},
                "required": ["seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "do_nothing",
            "description": "Choose silence. No sound and no motion is produced.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        },
    },
]


class ToolCallError(ValueError):
    """The model returned calls we cannot execute."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "ToolCall":
        if "function" in raw:
            fn = raw["function"] or {}
            name = fn.get("name", "")
            args = fn.get("arguments", {})
        else:
            name = raw.get("name", "")
            args = raw.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError as exc:
                raise ToolCallError(f"{name}: arguments are not valid JSON") from exc
        if not isinstance(args, dict):
            raise ToolCallError(f"{name}: arguments must be an object")
        return cls(str(name), args)


@dataclass
class Plan:
    calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None
    error: str | None = None

    @property
    def has_actions(self) -> bool:
        return any(c.name != "do_nothing" for c in self.calls)

    @property
    def explanation(self) -> str:
        for call in self.calls:
            if call.name == "do_nothing":
                return str(call.arguments.get("reason", ""))
        return ""


def validate_calls(calls: list[ToolCall]) -> list[ToolCall]:
    for call in calls:
        a = call.arguments
        if call.name == "speak":
            if not isinstance(a.get("text"), str) or not a["text"].strip():
                raise ToolCallError("speak.text must be a non-empty string")
        elif call.name == "gesture":
            if a.get("name") not in GESTURES:
                raise ToolCallError(f"gesture.name must be one of {GESTURES}")
            _check_range(a, "intensity", 0.0, 1.0, default=0.6)
            _check_range(a, "duration", 0.1, 10.0, default=1.0)
        elif call.name == "choreograph":
            try:
                parse_dance(a.get("program", a))
            except ValueError as exc:
                raise ToolCallError(f"choreograph: {exc}") from exc
        elif call.name == "set_expression":
            if a.get("name") not in EXPRESSIONS:
                raise ToolCallError(f"set_expression.name must be one of {EXPRESSIONS}")
            _check_range(a, "weight", 0.0, 1.0, default=1.0)
        elif call.name == "wait":
            _check_range(a, "seconds", 0.0, MAX_WAIT_SECONDS, default=0.0)
        elif call.name == "do_nothing":
            pass
        else:
            raise ToolCallError(f"unknown tool: {call.name}")
    return calls


def _check_range(args: dict[str, Any], key: str, lo: float, hi: float,
                 *, default: float) -> None:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolCallError(f"{key} must be a number")
    if not lo <= float(value) <= hi:
        raise ToolCallError(f"{key} must be between {lo} and {hi}")


def parse_plan(raw_calls: list[dict[str, Any]], raw: Any = None) -> Plan:
    try:
        calls = validate_calls([ToolCall.from_raw(c) for c in raw_calls])
    except ToolCallError as exc:
        return Plan(calls=[], raw=raw, error=str(exc))
    return Plan(calls=calls, raw=raw)


class LLMError(RuntimeError):
    """Distinguishable model failure (spec: failure isolation)."""


Transport = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


@dataclass
class LLMClient:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.8
    timeout: float = 20.0
    transport: Transport | None = None

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None) -> Plan:
        payload_messages = [{"role": "system", "content": system}, *messages]
        tools = TOOL_SCHEMA if tools is None else tools
        try:
            response = (self.transport or self._http_transport)(payload_messages, tools)
        except Exception as exc:  # network, timeout, bad JSON...
            return Plan(raw=None, error=f"llm_error: {exc}")
        try:
            message = response["choices"][0]["message"]
            raw_calls = message.get("tool_calls") or []
            if not raw_calls and message.get("content"):
                return Plan(raw=response)
            return parse_plan(raw_calls, raw=response)
        except (KeyError, IndexError, TypeError) as exc:
            return Plan(raw=response, error=f"malformed response: {exc}")

    def _http_transport(self, messages: list[dict[str, Any]],
                        tools: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
 "Accept": "application/json",
 "User-Agent": "meta-hub/0.1 pi-live",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(str(exc)) from exc
