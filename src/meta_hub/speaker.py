"""Speaker adapter for the timeline executor: TTS + audio + A2F face frames.

The executor owns the utterance clock but knows nothing about VMC. This class
synthesizes to a wav, plays it on the Windows side, and while it plays, pushes
A2F-derived blendshape weights into a ``VmcMotionPlayer``. The player keeps
sending bones / idle motion on the same stream, so audio, lips and gestures do
not race on the UDP socket.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .config import settings
from .stages.vmc import arkit_to_vrm


class PlayerSpeaker:
    def __init__(
        self,
        player,
        *,
        out_dir: str | Path | None = None,
        profile: str | None = None,
        play_audio: bool | None = None,
        synth: Callable[[str, str], str | None] | None = None,
        frames: Callable[[str], Iterable[tuple]] | None = None,
        start_playback: Callable[[str], object] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        verbose: bool = False,
    ) -> None:
        self.player = player
        self.out_dir = Path(out_dir or settings.out_dir)
        self.profile = profile or settings.vmc_blend_profile
        self.play_audio = settings.audio_enabled if play_audio is None else play_audio
        self._synth = synth
        self._frames = frames
        self._start_playback = start_playback
        self._sleep = sleep
        self.verbose = verbose
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._proc = None
        self._counter = 0
        self.spoken: list[str] = []
        self.last_wav: str | None = None
        # text -> (wav, frames); filled by prepare() before overlays start.
        self._prepared: dict[str, tuple[str, list[tuple]]] = {}

    # -- dependencies are lazy so unit tests can inject fakes --------------
    def _synthesize(self, text: str, path: str) -> str | None:
        if self._synth is not None:
            return self._synth(text, path)
        from .stages.speech import synthesize
        return synthesize(text, path)

    def _prepare_text(self, text: str) -> tuple[str | None, list[tuple]]:
        if text in self._prepared:
            return self._prepared[text]
        if not text or not text.strip():
            return None, []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._counter += 1
            wav = str(self.out_dir / f"speech-{self._counter:04d}.wav")
        if self._synthesize(text, wav) is None:
            return None, []
        if self.verbose:
            print(f"[speaker] synth -> {wav}", flush=True)
        # A2F failure must not suppress audio: failure isolation (spec D10).
        try:
            frames = list(self._frame_source(wav))
        except Exception as exc:  # noqa: BLE001 - report, keep speaking
            frames = []
            self.last_error = f"A2F unavailable: {exc}"
            if self.verbose:
                print(f"[speaker] {self.last_error}; playing audio only", flush=True)
        if self.verbose:
            print(f"[speaker] {len(frames)} A2F frames", flush=True)
        self._prepared[text] = (wav, frames)
        return wav, frames

    def prepare(self, timeline=None) -> None:
        """Pre-synthesize speech + prefetch A2F before overlays/audio start.

        Without this, a gesture starts immediately but audio waits for TTS and
        A2F, so the avatar appears to dance first and speak afterwards.
        """
        if timeline is None:
            return
        items = getattr(timeline, "speech", None)
        if items is not None:
            texts = [i.text for i in items if getattr(i, "kind", "") == "speak"]
        elif isinstance(timeline, (list, tuple, set)):
            texts = [str(t) for t in timeline]
        else:
            texts = [str(timeline)]
        for text in texts:
            self._prepare_text(text)

    def _frame_source(self, wav: str) -> Iterator[tuple]:
        if self._frames is not None:
            yield from self._frames(wav)
            return
        from .stages.animation import a2f_frames
        yield from a2f_frames(wav, with_time=True)

    def _play(self, wav: str):
        if self._start_playback is not None:
            return self._start_playback(wav)
        from .stages.audio_out import start_playback
        return start_playback(wav)

    # -- Speaker protocol --------------------------------------------------
    def speak(self, text: str, duration: float, cancelled: threading.Event) -> None:
        wav, frames = self._prepare_text(text)
        if wav is None:
            return
        self.last_wav = wav
        self.spoken.append(text)
        if self.verbose:
            print(f"[speaker] speak {duration:.2f}s", flush=True)
        proc = None
        if self.play_audio:
            proc = self._play(wav)
            with self._lock:
                self._proc = proc
            if self.verbose:
                print(f"[speaker] audio pid={getattr(proc, 'pid', '?')}", flush=True)
        started = time.monotonic()
        try:
            for _names, arkit, t_audio in frames:
                if cancelled.is_set():
                    break
                delay = t_audio - (time.monotonic() - started)
                if delay > 0 and cancelled.wait(delay):
                    break
                self.player.set_face_weights(
                    arkit_to_vrm(arkit, mouth_gain=settings.vmc_mouth_gain,
                                 profile=self.profile)
                )
            # Keep the mouth/face alive for the estimated utterance duration
            # even if A2F emitted a slightly shorter track.
            while not cancelled.is_set():
                remaining = duration - (time.monotonic() - started)
                if remaining <= 0:
                    break
                cancelled.wait(min(remaining, 0.05))
        finally:
            if proc is not None and proc.poll() is None:
                if cancelled.is_set():
                    proc.terminate()
                else:
                    try:
                        proc.wait(timeout=max(0.1, duration))
                    except Exception:
                        proc.terminate()
            with self._lock:
                self._proc = None
            self.player.set_face_weights({})
            if self.verbose:
                print("[speaker] done", flush=True)

    def wait(self, seconds: float, cancelled: threading.Event) -> None:
        if seconds > 0:
            cancelled.wait(seconds)

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
        self.player.set_face_weights({})
