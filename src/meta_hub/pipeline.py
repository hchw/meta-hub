"""Turn orchestration: text -> speech -> animation -> VMC sink.

Timing follows design D5: every stage is expressed on one sample-counter clock
(``meta_hub.clock.SampleClock``). A2F time-codes are the authoritative
expression timeline; frames are emitted on that timeline and we report the
worst-case scheduling lag so audio/expression drift stays verifiable (<100ms).

Cross-boundary split (design D8): audio is handed to a Windows-side player
(virtual sound card -> OBS); expressions go over VMC/UDP to the renderer.
"""
from __future__ import annotations
import time
from pathlib import Path
from .clock import SampleClock
from .config import settings
from .stages.speech import synthesize
from .stages.animation import a2f_frames
from .stages.vmc import VmcSender, arkit_to_vrm


def say(text: str, out_path: str | None = None, prompt_wav: str | None = None) -> str:
    out = out_path or str(Path(settings.out_dir) / "speech.wav")
    return synthesize(text, out, prompt_wav)


def animate(
    wav_path: str,
    fps: float | None = None,
    send_vmc: bool = True,
    reset_neutral: bool = True,
    frames=None,
) -> dict:
    """Drive the renderer from a wav (or pre-fetched ``frames``); return diagnostics."""
    sender = VmcSender(settings.vmc_host, settings.vmc_port) if send_vmc else None
    fps = fps or settings.vmc_fps
    min_dt = (1.0 / fps) if fps and fps > 0 else 0.0
    clock: SampleClock | None = None
    n = 0
    duration = 0.0
    max_lag_ms = 0.0
    last_sent_t = -1e9
    t0 = time.monotonic()
    source = frames if frames is not None else a2f_frames(wav_path, with_time=True)
    for _names, arkit, t_audio in source:
        duration = t_audio
        # Optional send-rate cap (A2F can emit up to ~90fps); fps is a ceiling, not the clock.
        if min_dt and (t_audio - last_sent_t) < min_dt - 1e-9:
            continue
        if clock is None:
            # Anchor the clock at the first frame: audio start == animation start,
            # so A2F's ~0.5s model warm-up does not count as drift.
            clock = SampleClock(settings.a2f_sample_rate)
            t0 = clock.start
        lag = clock.sleep_until_sample(round(t_audio * settings.a2f_sample_rate))
        max_lag_ms = max(max_lag_ms, lag * 1000.0)
        if sender:
            sender.send(arkit_to_vrm(arkit, mouth_gain=settings.vmc_mouth_gain))
        last_sent_t = t_audio
        n += 1
    if sender and reset_neutral:
        sender.send_neutral()
    return {
        "frames": n,
        "duration": duration,
        "wall": time.monotonic() - t0,
        "max_lag_ms": max_lag_ms,
    }


def turn(
    text: str,
    out_path: str | None = None,
    send_vmc: bool = True,
    reset_neutral: bool = True,
    play_audio: bool | None = None,
) -> dict:
    """One whole-sentence turn: synthesize, then play audio + animate in sync."""
    wav = say(text, out_path)
    if wav is None:  # empty input: no content, not an error (streaming-speech spec)
        return {"frames": 0, "duration": 0.0, "wall": 0.0, "max_lag_ms": 0.0, "no_content": True}
    # Pre-fetch so audio playback and the animation clock can start together.
    frames = list(a2f_frames(wav, with_time=True))
    play = settings.audio_enabled if play_audio is None else play_audio
    proc = None
    if play:
        from .stages.audio_out import start_playback
        proc = start_playback(wav)
    result = animate(wav, send_vmc=send_vmc, reset_neutral=reset_neutral, frames=frames)
    if proc is not None:
        from .stages.audio_out import wait
        wait(proc)
        result["audio_played"] = True
    return result
