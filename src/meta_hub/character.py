"""Declarative character cards (design D7, tasks 6.1-6.4).

A character is data: avatar, voice, persona, topics and greeting.  Fields may
be omitted (defaults apply) but names and types are validated strictly with a
locatable path so a typo fails at startup instead of being ignored.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .events import Event


class CharacterError(ValueError):
    pass


@dataclass
class AvatarConfig:
    vrm: str = ""                     # renderer-visible model identifier/path
    expression_map: dict[str, str] = field(default_factory=dict)


@dataclass
class VoiceConfig:
    prompt_wav: str = ""              # zero-shot reference audio
    prompt_text: str = "希望你以后能够做的比我还好呦。"
    speed: float = 1.0


@dataclass
class CharacterCard:
    id: str
    name: str
    avatar: AvatarConfig = field(default_factory=AvatarConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    persona: str = ""
    topics: list[str] = field(default_factory=list)
    greeting: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, default_id: str = "") -> "CharacterCard":
        if not isinstance(data, dict):
            raise CharacterError("character card must be a JSON object")
        known = {"id", "name", "avatar", "voice", "persona", "topics", "greeting"}
        _reject_unknown(data, known, "character")
        if "name" not in data or not isinstance(data["name"], str) or not data["name"].strip():
            raise CharacterError("character.name is required and must be a non-empty string")
        char_id = data.get("id", default_id or _slug(data["name"]))
        if not isinstance(char_id, str) or not char_id.strip():
            raise CharacterError("character.id must be a non-empty string")
        avatar = _nested(data.get("avatar", {}), {"vrm", "expression_map"}, "avatar")
        voice = _nested(data.get("voice", {}), {"prompt_wav", "prompt_text", "speed"}, "voice")
        if "vrm" in avatar and not isinstance(avatar["vrm"], str):
            raise CharacterError("avatar.vrm must be a string")
        if "prompt_wav" in voice and not isinstance(voice["prompt_wav"], str):
            raise CharacterError("voice.prompt_wav must be a string")
        if "prompt_text" in voice and not isinstance(voice["prompt_text"], str):
            raise CharacterError("voice.prompt_text must be a string")
        if not isinstance(avatar.get("expression_map", {}), dict):
            raise CharacterError("avatar.expression_map must be an object")
        if avatar.get("expression_map"):
            for k, v in avatar["expression_map"].items():
                if not isinstance(v, str):
                    raise CharacterError(f"avatar.expression_map.{k} must be a string")
        if not isinstance(voice.get("speed", 1.0), (int, float)) or isinstance(
                voice.get("speed", 1.0), bool):
            raise CharacterError("voice.speed must be a number")
        persona = data.get("persona", "")
        if not isinstance(persona, str):
            raise CharacterError("persona must be a string")
        topics = data.get("topics", [])
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            raise CharacterError("topics must be a list of strings")
        greeting = data.get("greeting", "")
        if not isinstance(greeting, str):
            raise CharacterError("greeting must be a string")
        return cls(
            id=char_id,
            name=data["name"],
            avatar=AvatarConfig(vrm=str(avatar.get("vrm", "")),
                                expression_map=dict(avatar.get("expression_map", {}))),
            voice=VoiceConfig(
                prompt_wav=str(voice.get("prompt_wav", "")),
                prompt_text=str(voice.get("prompt_text", VoiceConfig.prompt_text)),
                speed=float(voice.get("speed", 1.0)),
            ),
            persona=persona,
            topics=list(topics),
            greeting=greeting,
        )


def _reject_unknown(data: dict[str, Any], known: set[str], where: str) -> None:
    unknown = set(data) - known
    if unknown:
        raise CharacterError(f"{where}: unknown field(s): {sorted(unknown)}")


def _nested(value: Any, known: set[str], where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CharacterError(f"{where} must be an object")
    _reject_unknown(value, known, where)
    return value


def _slug(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    return slug or "character"


def load_card(path: str | Path) -> CharacterCard:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CharacterError(f"{p}: invalid JSON: {exc}") from exc
    return CharacterCard.from_dict(data, default_id=p.stem)


def load_cards(directory: str | Path) -> dict[str, CharacterCard]:
    cards: dict[str, CharacterCard] = {}
    for path in sorted(Path(directory).glob("*.json")):
        card = load_card(path)
        if card.id in cards:
            raise CharacterError(f"duplicate character id: {card.id}")
        cards[card.id] = card
    return cards


@dataclass
class Activation:
    """The one-shot orchestration performed when a character is selected."""

    def __init__(self, card: CharacterCard) -> None:
        self.card = card
        self.avatar = card.avatar.vrm
        self.voice_prompt_wav = card.voice.prompt_wav
        self.voice_prompt_text = card.voice.prompt_text
        self.voice_speed = card.voice.speed
        self.persona = card.persona
        self.topics = list(card.topics)
        self.greeting = card.greeting


class CharacterRuntime:
    """Selects one character at startup; no hot switching (design D7)."""

    def __init__(self, active: CharacterCard | None = None) -> None:
        self.active = active

    @classmethod
    def from_directory(cls, character_id: str,
                       directory: str | Path) -> "CharacterRuntime":
        """Startup selection: load every card, pick one by id (or name)."""
        cards = load_cards(directory)
        card = cards.get(character_id)
        if card is None:
            by_name = [c for c in cards.values() if c.name == character_id]
            if len(by_name) == 1:
                card = by_name[0]
            else:
                raise CharacterError(
                    f"unknown character {character_id!r}; available: {sorted(cards)}")
        return cls(card)

    def activate(self, card: CharacterCard) -> Activation:
        self.active = card
        return Activation(card)

    def activate_selected(self) -> Activation:
        if self.active is None:
            raise CharacterError("no character selected")
        return self.activate(self.active)

    @property
    def memory_namespace(self) -> str:
        if self.active is None:
            raise CharacterError("no active character")
        return self.active.id


@dataclass
class CharacterMemory:
    events: list[Event] = field(default_factory=list)
    utterances: list[str] = field(default_factory=list)
    max_events: int = 200
    max_utterances: int = 50

    def observe(self, event: Event) -> None:
        self.events.append(event)
        del self.events[:-self.max_events]

    def note_utterance(self, text: str) -> None:
        if text.strip():
            self.utterances.append(text.strip())
            del self.utterances[:-self.max_utterances]

    def recent(self, limit: int = 12) -> list[Event]:
        return self.events[-limit:]

    def clear(self) -> None:
        self.events.clear()
        self.utterances.clear()


class MemoryStore:
    """Memory namespaced by character id; one character can never read another."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else None
        self._memories: dict[str, CharacterMemory] = {}

    def for_character(self, character_id: str) -> CharacterMemory:
        if character_id not in self._memories:
            memory = CharacterMemory()
            if self.root is not None:
                path = self._path(character_id)
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    memory.events = [Event.from_dict(e) for e in data.get("events", [])]
                    memory.utterances = [str(u) for u in data.get("utterances", [])]
            self._memories[character_id] = memory
        return self._memories[character_id]

    def save(self, character_id: str) -> None:
        if self.root is None:
            return
        memory = self.for_character(character_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(character_id).write_text(json.dumps({
            "events": [e.to_dict() for e in memory.events],
            "utterances": memory.utterances,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _path(self, character_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in character_id)
        return self.root / f"{safe}.json"  # type: ignore[union-attr]
