"""Environment, toolchain paths and subprocess helpers for the avatar MCP."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AvatarSettings:
    """Resolved locations of every external tool used by the pipeline.

    The heavy generators live in their own venvs and are driven out of process
    (same pattern as ``meta_hub.config.Settings.cosy_python``). Blender lives
    on the Windows host and is reached through WSL interop.
    """

    # --- WSL-side generators -------------------------------------------------
    triposr_repo: str = os.environ.get("AVATAR_TRIPOSR_REPO", "/home/hebl/models/TripoSR")
    triposr_python: str = os.environ.get(
        "AVATAR_TRIPOSR_PYTHON", "/home/hebl/models/TripoSR/.venv/bin/python"
    )
    unirig_repo: str = os.environ.get("AVATAR_UNIRIG_REPO", "/home/hebl/models/UniRig")
    unirig_python: str = os.environ.get(
        "AVATAR_UNIRIG_PYTHON", "/home/hebl/models/UniRig/.venv/bin/python"
    )
    # open3d needs libusb-1.0; the venv ships it via a locally extracted .deb.
    unirig_ld_library_path: str = os.environ.get(
        "AVATAR_UNIRIG_LD_LIBRARY_PATH",
        "/home/hebl/models/UniRig/.sys/usr/lib/x86_64-linux-gnu",
    )
    hf_home: str = os.environ.get("AVATAR_HF_HOME", "/home/hebl/models/.hf")

    # --- Windows-side Blender ------------------------------------------------
    blender_exe: str = os.environ.get(
        "AVATAR_BLENDER_EXE",
        "/mnt/d/apps/blender-5.2.3-candidate+v52.35/"
        "blender-5.2.3-candidate+v52.35/blender.exe",
    )

    # --- Hyper3D Rodin API ---------------------------------------------------
    rodin_api_key: str = os.environ.get("RODIN_API_KEY", "")
    rodin_base_url: str = os.environ.get(
        "AVATAR_RODIN_BASE_URL", "https://api.hyper3d.com/api/v2"
    )
    rodin_tier: str = os.environ.get("AVATAR_RODIN_TIER", "Gen-2.5-Medium")

    # --- Shared work directory (on the Windows disk, see design D8) ----------
    work_dir: str = os.environ.get("AVATAR_WORK_DIR", "/mnt/d/meta-hub/avatar-work")

    def path(self, *parts: str) -> str:
        return str(Path(self.work_dir).joinpath(*parts))

    def win_path(self, wsl_path: str) -> str:
        """Translate a WSL path to a Windows path (``wslpath -w``)."""
        return to_windows(wsl_path)


settings = AvatarSettings()


def to_windows(path: str) -> str:
    """Best-effort WSL -> Windows path translation."""
    if not path:
        return path
    if _looks_windows(path):
        return path
    # Fast path for /mnt/<drive>/... which covers everything under the work dir.
    p = Path(path)
    parts = p.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper()
        rest = "\\".join(parts[3:])
        return f"{drive}:\\{rest}"
    try:
        out = subprocess.run(
            ["wslpath", "-w", path], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return path


def _looks_windows(path: str) -> bool:
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()


@dataclass
class CommandResult:
    ok: bool
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    error: str | None = None

    def to_dict(self, *, tail: int | None = None) -> dict:
        out = {
            "ok": self.ok,
            "returncode": self.returncode,
            "cmd": self.cmd,
            "stdout": _tail(self.stdout, tail),
            "stderr": _tail(self.stderr, tail),
        }
        if self.error:
            out["error"] = self.error
        return out


def _tail(text: str, n: int | None) -> str:
    if not text or n is None:
        return text
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> CommandResult:
    """Run a command, never raising on non-zero exit."""
    merged = os.environ.copy()
    if env:
        merged.update(env)
    if not shutil.which(cmd[0]) and not os.path.exists(cmd[0]):
        return CommandResult(
            ok=False, cmd=cmd, returncode=127, stdout="", stderr="",
            error=f"executable not found: {cmd[0]}",
        )
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=merged, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            ok=False, cmd=cmd, returncode=124,
            stdout=exc.stdout or "", stderr=exc.stderr or "",
            error=f"timed out after {timeout}s",
        )
    except OSError as exc:
        return CommandResult(
            ok=False, cmd=cmd, returncode=126, stdout="", stderr="",
            error=f"{type(exc).__name__}: {exc}",
        )
    return CommandResult(
        ok=proc.returncode == 0,
        cmd=cmd,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        error=None if proc.returncode == 0 else f"exit code {proc.returncode}",
    )
