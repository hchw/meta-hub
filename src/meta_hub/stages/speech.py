"""Speech stage: text -> wav, via CosyVoice in its own venv (out-of-process)."""
from __future__ import annotations
import subprocess
from pathlib import Path
from ..config import settings


class SpeechError(RuntimeError):
    """Distinguishable synthesis failure (spec: failure isolation)."""


def default_prompt_wav() -> str:
    return str(Path(settings.cosy_repo) / "asset" / "zero_shot_prompt.wav")


def synthesize(text: str, out_path: str, prompt_wav: str | None = None) -> str | None:
    """Run CosyVoice zero-shot TTS for ``text`` and write a wav to ``out_path``.

    Returns the wav path, or ``None`` for empty/whitespace input (a
    distinguishable "no content" result, not an error). Raises ``SpeechError``
    on synthesis failure so callers can identify it and continue.
    """
    if not text or not text.strip():
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.cosy_python, str(settings.cosy_helper),
        "--text", text, "--out", out_path,
        "--prompt-wav", prompt_wav or default_prompt_wav(),
        "--model", settings.cosy_model,
    ]
    proc = subprocess.run(cmd, cwd=settings.cosy_repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SpeechError(f"cosy_say failed (rc={proc.returncode}): {proc.stderr[-600:]}")
    if not Path(out_path).exists():
        raise SpeechError(f"cosy_say produced no file: {proc.stdout[-300:]}")
    return out_path
