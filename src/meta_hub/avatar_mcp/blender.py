"""Stage 3: run headless Blender (Windows host) from WSL via interop.

Every Blender-side step (bone remap, expressions, spring bones, VRM import /
export) is a plain ``bpy`` script executed as::

    blender.exe --background --python <script> -- <args...>

No GUI, no ``--factory-startup`` (that would hide the user-installed VRM
add-on). WSL paths in ``args`` are auto-translated to Windows paths.
"""
from __future__ import annotations

import os
from pathlib import Path

from .env import settings, to_windows


def blender_run(
    script: str,
    args: list[str] | None = None,
    *,
    cwd: str | None = None,
    timeout: float | None = 1800,
    factory_startup: bool = False,
) -> dict:
    """Execute a bpy script under headless Blender on the Windows host.

    ``script`` is a WSL path to a ``.py`` file on a Windows-accessible drive.
    ``args`` are forwarded after ``--``; ``/mnt/...`` entries are translated to
    Windows paths first.
    """
    from .env import run

    script_path = Path(script).expanduser()
    if not script_path.exists():
        return {"ok": False, "error": f"blender script not found: {script_path}"}
    if not os.path.exists(settings.blender_exe):
        return {
            "ok": False,
            "error": f"Blender executable not found: {settings.blender_exe}",
            "hint": "set AVATAR_BLENDER_EXE to the Windows blender.exe path",
        }

    win_script = to_windows(str(script_path))
    win_args = [to_windows(a) for a in (args or [])]

    cmd = [settings.blender_exe, "--background"]
    if factory_startup:
        cmd.append("--factory-startup")
    cmd += ["--python", win_script]
    if win_args:
        cmd += ["--", *win_args]

    result = run(
        cmd,
        cwd=cwd or str(script_path.parent),
        env={"PYTHONUNBUFFERED": "1"},
        timeout=timeout,
    )
    payload = result.to_dict(tail=60)
    payload["script"] = str(script_path)
    payload["script_windows"] = win_script
    payload["args"] = win_args
    # Blender print() goes to stdout; keep a small tail for convenience.
    payload["blender_stdout_tail"] = "\n".join(result.stdout.splitlines()[-40:])
    return payload
