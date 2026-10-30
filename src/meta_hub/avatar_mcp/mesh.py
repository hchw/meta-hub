"""Stage 1: image -> 3D mesh (TripoSR, WSL-side)."""
from __future__ import annotations

import os
from pathlib import Path

from .env import settings, to_windows

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def generate_mesh(
    image_path: str,
    output_dir: str | None = None,
    *,
    foreground_ratio: float = 0.85,
    mc_resolution: int = 256,
    no_remove_bg: bool = False,
    timeout: float | None = 1800,
) -> dict:
    """Run TripoSR on a reference photo and return the produced GLB.

    Raises nothing; every failure is returned as ``{"ok": False, ...}`` with a
    locatable ``error``/``hint`` so the agent can fix inputs and retry.
    """
    src = Path(image_path).expanduser()
    if not src.exists():
        return {
            "ok": False,
            "error": f"input image not found: {src}",
            "hint": "provide an absolute path to a PNG/JPG photo of a person",
        }
    if src.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        return {
            "ok": False,
            "error": f"unsupported image suffix: {src.suffix}",
            "hint": f"supported: {sorted(SUPPORTED_IMAGE_SUFFIXES)}",
        }
    if not os.path.exists(settings.triposr_python):
        return {
            "ok": False,
            "error": f"TripoSR python not found: {settings.triposr_python}",
            "hint": "set AVATAR_TRIPOSR_PYTHON or deploy TripoSR",
        }

    out_dir = Path(output_dir) if output_dir else Path(settings.path("mesh", src.stem))
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        settings.triposr_python,
        "run.py",
        str(src),
        "--output-dir",
        str(out_dir),
        "--model-save-format",
        "glb",
        "--foreground-ratio",
        str(foreground_ratio),
        "--mc-resolution",
        str(mc_resolution),
    ]
    if no_remove_bg:
        cmd.append("--no-remove-bg")

    from .env import run

    result = run(
        cmd,
        cwd=settings.triposr_repo,
        env={"HF_HOME": settings.hf_home, "PYTHONUNBUFFERED": "1"},
        timeout=timeout,
    )

    glb = out_dir / "0" / "mesh.glb"
    if not result.ok:
        return {
            **result.to_dict(tail=40),
            "error": result.error,
            "hint": "inspect stderr; TripoSR needs a CUDA GPU and a clear full-body photo",
            "output_dir": str(out_dir),
        }
    if not glb.exists():
        return {
            "ok": False,
            "error": f"TripoSR finished but no GLB at {glb}",
            "cmd": cmd,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
            "output_dir": str(out_dir),
        }
    return {
        "ok": True,
        "mesh_glb": str(glb),
        "mesh_glb_windows": to_windows(str(glb)),
        "size_bytes": glb.stat().st_size,
        "output_dir": str(out_dir),
        "source_image": str(src),
    }
