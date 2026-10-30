"""Stage 2: mesh -> rigged mesh (UniRig skeleton + skinning, WSL-side)."""
from __future__ import annotations

import os
from pathlib import Path

from .env import settings, to_windows

SKELETON_TASK = "configs/task/quick_inference_skeleton_articulationxl_ar_256.yaml"
SKIN_TASK = "configs/task/quick_inference_unirig_skin.yaml"


def _unirig_env() -> dict[str, str]:
    venv_bin = str(Path(settings.unirig_python).parent)
    return {
        "HF_HOME": settings.hf_home,
        "LD_LIBRARY_PATH": settings.unirig_ld_library_path,
        "PYTHONUNBUFFERED": "1",
        "PATH": venv_bin + os.pathsep + os.environ.get("PATH", ""),
    }


def _bash(script: str, args: list[str]):
    from .env import run

    cmd = ["bash", script, *args]
    return run(cmd, cwd=settings.unirig_repo, env=_unirig_env(), timeout=None)


def rig(
    mesh_path: str,
    output_dir: str | None = None,
    *,
    seed: int = 12345,
    faces_target_count: int = 50000,
    skeleton_timeout: float | None = 1800,
    skin_timeout: float | None = 1800,
) -> dict:
    """Rig a mesh with UniRig: predict a skeleton, then skinning weights.

    Returns the rigged FBX (mesh + armature + vertex groups) and, when it can be
    produced, a merged rigged GLB.
    """
    from .env import run

    src = Path(mesh_path).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"mesh not found: {src}"}
    if src.suffix.lower() not in {".glb", ".gltf", ".obj", ".fbx", ".vrm", ".dae"}:
        return {
            "ok": False,
            "error": f"unsupported mesh suffix: {src.suffix}",
            "hint": "supported: obj/fbx/glb/gltf/dae/vrm",
        }
    if not os.path.exists(settings.unirig_python):
        return {
            "ok": False,
            "error": f"UniRig python not found: {settings.unirig_python}",
            "hint": "set AVATAR_UNIRIG_PYTHON or deploy UniRig",
        }

    out_dir = Path(output_dir) if output_dir else Path(settings.path("rig", src.stem))
    out_dir.mkdir(parents=True, exist_ok=True)
    skeleton_fbx = out_dir / f"{src.stem}_skeleton.fbx"
    skin_fbx = out_dir / f"{src.stem}_skin.fbx"

    # --- stage A: skeleton ---------------------------------------------------
    res_a = run(
        [
            "bash", "launch/inference/generate_skeleton.sh",
            "--input", str(src),
            "--output", str(skeleton_fbx),
            "--seed", str(seed),
        ],
        cwd=settings.unirig_repo, env=_unirig_env(), timeout=skeleton_timeout,
    )
    if not res_a.ok or not skeleton_fbx.exists():
        return {
            "ok": False,
            "stage": "skeleton",
            "error": res_a.error or f"no skeleton at {skeleton_fbx}",
            **res_a.to_dict(tail=40),
            "output_dir": str(out_dir),
        }

    # --- stage B: skinning ---------------------------------------------------
    res_b = run(
        [
            "bash", "launch/inference/generate_skin.sh",
            "--input", str(skeleton_fbx),
            "--output", str(skin_fbx),
            "--seed", str(seed),
        ],
        cwd=settings.unirig_repo, env=_unirig_env(), timeout=skin_timeout,
    )
    if not res_b.ok or not skin_fbx.exists():
        return {
            "ok": False,
            "stage": "skin",
            "error": res_b.error or f"no skinned mesh at {skin_fbx}",
            **res_b.to_dict(tail=40),
            "skeleton_fbx": str(skeleton_fbx),
            "output_dir": str(out_dir),
        }

    result = {
        "ok": True,
        "rigged_fbx": str(skin_fbx),
        "rigged_fbx_windows": to_windows(str(skin_fbx)),
        "skeleton_fbx": str(skeleton_fbx),
        "size_bytes": skin_fbx.stat().st_size,
        "output_dir": str(out_dir),
        "source_mesh": str(src),
    }

    # --- optional: merge skin into the source mesh as GLB --------------------
    merged_glb = out_dir / f"{src.stem}_rigged.glb"
    res_m = run(
        [
            "bash", "launch/inference/merge.sh",
            "--source", str(skin_fbx),
            "--target", str(src),
            "--output", str(merged_glb),
        ],
        cwd=settings.unirig_repo, env=_unirig_env(), timeout=1800,
    )
    if res_m.ok and merged_glb.exists():
        result["merged_glb"] = str(merged_glb)
        result["merged_glb_windows"] = to_windows(str(merged_glb))
        result["merged_size_bytes"] = merged_glb.stat().st_size
    else:
        result["merge_warning"] = (res_m.error or "merge produced no GLB")
        result["merge_stderr"] = res_m.stderr[-1000:]

    return result
