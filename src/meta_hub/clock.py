"""Single media clock based on the audio sample counter (design D5).

Audio and facial animation must share one timeline. We anchor a monotonic
wall-clock to the audio sample counter: sample index = elapsed * sample_rate.
Every stage (audio playback position, A2F time-codes, VMC frame emission)
is expressed on this same counter, so drift cannot accumulate across
subsystems.
"""
from __future__ import annotations
import time


class SampleClock:
    """Maps wall-clock time <-> audio sample index for one utterance."""

    def __init__(self, sample_rate: int, start_wall: float | None = None) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.sample_rate = int(sample_rate)
        self._start = time.monotonic() if start_wall is None else start_wall

    @property
    def start(self) -> float:
        return self._start

    def elapsed(self) -> float:
        """Seconds since the clock started."""
        return time.monotonic() - self._start

    def samples_elapsed(self) -> int:
        """Audio sample index equivalent to the current wall-clock."""
        return int(self.elapsed() * self.sample_rate)

    def wall_for_sample(self, n: int) -> float:
        """Wall-clock instant of audio sample ``n``."""
        return self._start + n / self.sample_rate

    def sleep_until_sample(self, n: int) -> float:
        """Block until audio sample ``n``; return lag in seconds (>=0 = woke late)."""
        target = self.wall_for_sample(n)
        remaining = target - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        return time.monotonic() - target
