from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from meta_hub.character import (CharacterCard, CharacterError, CharacterRuntime,
                                MemoryStore, load_card, load_cards)
from meta_hub.events import Event


class CharacterCardTest(unittest.TestCase):
    def test_minimal_card_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alice.json"
            path.write_text(json.dumps({"name": "Alice", "persona": "温和、好奇"}))
            card = load_card(path)
            self.assertEqual(card.id, "alice")
            self.assertEqual(card.name, "Alice")
            self.assertEqual(card.avatar.vrm, "")
            self.assertEqual(card.voice.speed, 1.0)
            self.assertEqual(card.topics, [])
            self.assertEqual(card.greeting, "")

    def test_unknown_field_is_locatable(self):
        with self.assertRaises(CharacterError) as ctx:
            CharacterCard.from_dict({"name": "A", "personality": "typo"})
        self.assertIn("personality", str(ctx.exception))

    def test_type_errors_are_locatable(self):
        with self.assertRaises(CharacterError) as ctx:
            CharacterCard.from_dict({"name": "A", "avatar": {"vrm": 3}})
        self.assertIn("avatar", str(ctx.exception))
        with self.assertRaises(CharacterError) as ctx:
            CharacterCard.from_dict({"name": "A", "voice": {"speed": "fast"}})
        self.assertIn("voice.speed", str(ctx.exception))

    def test_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json")
            with self.assertRaises(CharacterError):
                load_card(path)

    def test_multiple_cards_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_text(json.dumps(
                {"name": "A", "persona": "甲", "voice": {"prompt_wav": "a.wav"}}))
            (Path(tmp) / "b.json").write_text(json.dumps(
                {"name": "B", "persona": "乙", "voice": {"prompt_wav": "b.wav"}}))
            cards = load_cards(tmp)
            self.assertEqual(set(cards), {"a", "b"})
            self.assertEqual(cards["a"].voice.prompt_wav, "a.wav")
            self.assertEqual(cards["b"].persona, "乙")

    def test_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.json", "b.json"):
                (Path(tmp) / name).write_text(json.dumps({"id": "same", "name": "X"}))
            with self.assertRaises(CharacterError):
                load_cards(tmp)


class ActivationTest(unittest.TestCase):
    def test_switching_role_changes_voice_and_persona_together(self):
        a = CharacterCard.from_dict({
            "id": "a", "name": "A", "persona": "温柔",
            "voice": {"prompt_wav": "/v/a.wav", "prompt_text": "a ref"},
        })
        b = CharacterCard.from_dict({
            "id": "b", "name": "B", "persona": "活泼",
            "voice": {"prompt_wav": "/v/b.wav", "prompt_text": "b ref"},
            "topics": ["游戏"],
        })
        runtime = CharacterRuntime()
        act_a = runtime.activate(a)
        self.assertEqual((act_a.voice_prompt_wav, act_a.persona), ("/v/a.wav", "温柔"))
        act_b = runtime.activate(b)
        self.assertEqual((act_b.voice_prompt_wav, act_b.persona), ("/v/b.wav", "活泼"))
        self.assertEqual(act_b.topics, ["游戏"])
        self.assertEqual(runtime.memory_namespace, "b")


class MemoryIsolationTest(unittest.TestCase):
    def test_startup_selection_by_id_from_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_text(json.dumps(
                {"id": "alice", "name": "Alice", "persona": "甲",
                 "voice": {"prompt_wav": "a.wav"}}))
            (Path(tmp) / "b.json").write_text(json.dumps(
                {"id": "bob", "name": "Bob", "persona": "乙",
                 "voice": {"prompt_wav": "b.wav"}}))
            runtime = CharacterRuntime.from_directory("bob", tmp)
            act = runtime.activate_selected()
            self.assertEqual((act.voice_prompt_wav, act.persona), ("b.wav", "乙"))
            with self.assertRaises(CharacterError):
                CharacterRuntime.from_directory("nobody", tmp)

    def test_memory_does_not_leak_between_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(tmp)
            a = store.for_character("alice")
            b = store.for_character("bob")
            a.observe(Event.comment("u1", "alice 的观众", viewer_name="FanA"))
            a.note_utterance("alice 说过")
            self.assertEqual(b.recent(), [])
            self.assertEqual(b.utterances, [])
            store.save("alice")
            store.save("bob")

            reloaded = MemoryStore(tmp)
            self.assertEqual(len(reloaded.for_character("alice").recent()), 1)
            self.assertEqual(reloaded.for_character("bob").recent(), [])

    def test_memory_files_are_namespaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(tmp)
            store.for_character("alice").observe(Event.comment("u", "hi"))
            store.save("alice")
            self.assertEqual((Path(tmp) / "alice.json").exists(), True)
            self.assertFalse((Path(tmp) / "bob.json").exists())


if __name__ == "__main__":
    unittest.main()
