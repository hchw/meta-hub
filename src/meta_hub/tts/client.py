"""Client for the resident CosyVoice service (design D11, tasks 1.2/1.3).

The model lives in its own venv and loads once; this client only crosses the
process boundary.  ``stream`` yields audio chunks as they are synthesized so
playback can start before the sentence is finished.
"""
from __future__ import annotations

import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from .protocol import ProtocolError, read_frame, request_header, write_frame


class SpeechError(RuntimeError):
    """Distinguishable synthesis failure (spec: failure isolation)."""


@dataclass
class AudioChunk:
    seq: int
    sample_rate: int
    samples: np.ndarray


class SpeechServiceClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 7712,
                 timeout: float = 60.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def stream(self, text: str, *, prompt_wav: str,
               prompt_text: str = "希望你以后能够做的比我还好呦。") -> Iterator[AudioChunk]:
        if not text or not text.strip():
            return
        request_id = uuid.uuid4().hex
        sample_rate = 0
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=min(5.0, self.timeout))
        except OSError as exc:
            raise SpeechError(
                f"speech service unreachable at {self.host}:{self.port}: {exc}"
            ) from exc
        try:
            sock.settimeout(self.timeout)
            with sock, sock.makefile("rwb") as stream:
                write_frame(stream, request_header(
                    text, prompt_wav=prompt_wav, prompt_text=prompt_text,
                    request_id=request_id,
                ))
                while True:
                    header, payload = read_frame(stream)
                    kind = header.get("type")
                    if kind == "start":
                        sample_rate = int(header.get("sample_rate", 0))
                        if sample_rate <= 0:
                            raise SpeechError("service returned no sample rate")
                        continue
                    if kind == "chunk":
                        if header.get("request_id") not in (None, request_id):
                            raise SpeechError("service returned a chunk for another request")
                        yield AudioChunk(
                            seq=int(header.get("seq", 0)),
                            sample_rate=sample_rate,
                            samples=np.frombuffer(payload, dtype=np.float32).copy(),
                        )
                        continue
                    if kind == "done":
                        return
                    if kind == "error":
                        raise SpeechError(str(header.get("message", "synthesis failed")))
                    raise SpeechError(f"unexpected frame: {kind!r}")
        except (OSError, ProtocolError) as exc:
            raise SpeechError(f"speech service failure: {exc}") from exc

    def synthesize(self, text: str, out_path: str, *,
                   prompt_wav: str, prompt_text: str = "") -> str | None:
        """Stream to a wav file; returns the path (or ``None`` for empty text)."""
        if not text or not text.strip():
            return None
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        import soundfile as sf
        wav = None
        try:
            for chunk in self.stream(
                text, prompt_wav=prompt_wav,
                prompt_text=prompt_text or "希望你以后能够做的比我还好呦。",
            ):
                if wav is None:
                    wav = sf.SoundFile(out_path, mode="w",
                                       samplerate=chunk.sample_rate,
                                       channels=1, subtype="PCM_16")
                if chunk.sample_rate != wav.samplerate:
                    raise SpeechError("service changed sample rate mid-stream")
                wav.write(chunk.samples)
        finally:
            if wav is not None:
                wav.close()
        if not Path(out_path).exists() or Path(out_path).stat().st_size == 0:
            raise SpeechError("service produced no audio")
        return out_path


class SpeechServiceManager:
    """Optionally starts the resident service once and reuses it."""

    def __init__(self, host: str, port: int, command: list[str],
                 cwd: str, *, startup_timeout: float = 180.0) -> None:
        self.host = host
        self.port = port
        self.command = command
        self.cwd = cwd
        self.startup_timeout = startup_timeout
        self._proc = None
        self._lock = threading.Lock()

    def is_up(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=0.3):
                return True
        except OSError:
            return False

    def ensure(self) -> None:
        with self._lock:
            if self.is_up():
                return
            if self._proc is None or self._proc.poll() is not None:
                import subprocess
                self._proc = subprocess.Popen(
                    self.command, cwd=self.cwd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                if self.is_up():
                    return
                if self._proc.poll() is not None:
                    raise SpeechError("speech service exited during startup")
                time.sleep(0.25)
            raise SpeechError("speech service did not become ready in time")

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
