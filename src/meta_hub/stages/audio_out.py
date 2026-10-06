"""Audio out stage: play the synthesized wav on the Windows side (design D8).

The renderer stays silent; speech is played into a Windows audio device
(a virtual sound card feeding OBS). WSL mirrors the Windows network but not
audio, so the wav is handed to a Windows-side player rather than played in WSL.
"""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path
from ..config import settings


def to_windows_path(p: str | Path) -> str:
    """Map a /mnt/<drive>/... WSL path to a Windows <Drive>:\\... path."""
    m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", str(p))
    if not m:
        raise ValueError(f"cannot map {p!r} to a Windows path (expected /mnt/<drive>/...)")
    return f"{m.group(1).upper()}:\\" + m.group(2).replace("/", "\\")


def start_playback(wav_path: str, dest_dir: str | None = None) -> subprocess.Popen:
    """Copy the wav to a Windows-visible dir and start playing it (non-blocking)."""
    target_dir = Path(dest_dir or settings.audio_win_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / Path(wav_path).name
    shutil.copy2(wav_path, dest)
    win = to_windows_path(dest)
    ps = f"$p = New-Object System.Media.SoundPlayer '{win}'; $p.PlaySync()"
    return subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]
    )


def wait(proc: subprocess.Popen, timeout: float | None = None) -> int:
    return proc.wait(timeout=timeout)
