"""Speech stage: client for the resident CosyVoice service (task 1.2/1.3).

The model no longer loads per utterance.  ``synthesize`` keeps the old
signature so ``meta-hub say``/``turn``/pipeline keep working, while
``stream_synthesize`` exposes chunks for low-latency playback.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..config import REPO_ROOT, settings
from ..tts.client import AudioChunk, SpeechError, SpeechServiceClient, SpeechServiceManager

__all__ = ["SpeechError", "AudioChunk", "synthesize", "stream_synthesize",
           "default_prompt_wav", "ensure_service"]

_manager: SpeechServiceManager | None = None


def default_prompt_wav() -> str:
    return str(Path(settings.cosy_repo) / "asset" / "zero_shot_prompt.wav")


def _manager_instance() -> SpeechServiceManager:
    global _manager
    if _manager is None:
        _manager = SpeechServiceManager(
            settings.tts_host,
            settings.tts_port,
            [
                settings.cosy_python,
                str(REPO_ROOT / "tools" / "cosy_service.py"),
                "--host", settings.tts_host,
                "--port", str(settings.tts_port),
                "--model", settings.cosy_model,
                "--cosy-repo", settings.cosy_repo,
            ],
            cwd=settings.cosy_repo,
            startup_timeout=settings.tts_startup_timeout,
        )
    return _manager


def ensure_service() -> None:
    if settings.tts_autostart:
        _manager_instance().ensure()


def _client() -> SpeechServiceClient:
    return SpeechServiceClient(settings.tts_host, settings.tts_port)


def stream_synthesize(text: str, *, prompt_wav: str | None = None,
                      prompt_text: str = "") -> Iterator[AudioChunk]:
    """Yield audio chunks while the service is still synthesizing."""
    if not text or not text.strip():
        return
    ensure_service()
    yield from _client().stream(
        text,
        prompt_wav=prompt_wav or default_prompt_wav(),
        prompt_text=prompt_text or "希望你以后能够做的比我还好呦。",
    )


def synthesize(text: str, out_path: str, prompt_wav: str | None = None,
               prompt_text: str = "") -> str | None:
    """Synthesize ``text`` to ``out_path``; ``None`` means "no content"."""
    if not text or not text.strip():
        return None
    ensure_service()
    return _client().synthesize(
        text,
        out_path,
        prompt_wav=prompt_wav or default_prompt_wav(),
        prompt_text=prompt_text or "希望你以后能够做的比我还好呦。",
    )
