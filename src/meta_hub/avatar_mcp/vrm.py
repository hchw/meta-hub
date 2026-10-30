"""Stage 4/5: VRM export and validation via headless Blender."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .blender import blender_run
from .env import settings, to_windows

SCRIPTS_DIR = Path(__file__).resolve().parent / "blender_scripts"


def _materialize(script_name: str) -> str:
    """Copy a bundled Blender script onto the (Windows) work dir and return it."""
    src = SCRIPTS_DIR / script_name
    dst_dir = Path(settings.path("tools"))
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / script_name
    shutil.copy2(src, dst)
    return str(dst)


def _parse_result(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("AVATAR_RESULT "):
            try:
                return json.loads(line[len("AVATAR_RESULT "):])
            except json.JSONDecodeError:
                return None
    return None


def export_vrm(
    model_path: str,
    output_vrm: str | None = None,
    *,
    auto_humanoid: bool = True,
    auto_expressions: bool = False,
    allow_non_humanoid: bool = False,
    spec_version: str = "0.0",
    timeout: float | None = 1800,
) -> dict:
    """Import a rigged model in headless Blender and export a VRM.

    ``spec_version`` defaults to ``"0.0"`` because the runtime renderer
    (VSeeFace) only supports VRM 0.x. Pass ``"1.0"`` for VRM 1.0.
    """
    src = Path(model_path).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"model not found: {src}"}
    out = Path(output_vrm) if output_vrm else Path(settings.path("vrm", src.stem + ".vrm"))
    out.parent.mkdir(parents=True, exist_ok=True)

    script = _materialize("vrm_export.py")
    res = blender_run(
        script,
        [
            str(src),
            str(out),
            "1" if auto_humanoid else "0",
            "1" if auto_expressions else "0",
            "1" if allow_non_humanoid else "0",
            spec_version,
        ],
        timeout=timeout,
    )
    report = _parse_result(res.get("stdout", ""))
    if report is None:
        return {
            "ok": False,
            "error": "Blender produced no AVATAR_RESULT line",
            **res,
        }
    report["vrm"] = str(out)
    report["vrm_windows"] = to_windows(str(out))
    report["blender_returncode"] = res.get("returncode")
    return report


def build_expressions(
    model_path: str,
    output_vrm: str | None = None,
    *,
    from_arkit: bool = False,
    mode: str = "geo",
    params: dict | None = None,
    previews: bool = True,
    timeout: float | None = 1800,
) -> dict:
    """Build VRM expressions and export a VRM.

    ``mode="geo"`` uses the procedural head/eye/mouth warps in
    ``build_expressions_geo.py``; ``mode="auto"`` only runs the add-on's
    automatic assignment (no real deformation if the mesh has no shape keys).
    """
    src = Path(model_path).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"model not found: {src}"}
    out = Path(output_vrm) if output_vrm else Path(settings.path("vrm", src.stem + ".vrm"))
    out.parent.mkdir(parents=True, exist_ok=True)
    _materialize("vrm_export.py")  # imported by the scripts

    if mode == "auto":
        script = _materialize("build_expressions.py")
        res = blender_run(
            script, [str(src), str(out), "1" if from_arkit else "0"], timeout=timeout
        )
    else:
        script = _materialize("build_expressions_geo.py")
        preview_dir = str(Path(settings.path("preview", src.stem))) if previews else ""
        res = blender_run(
            script,
            [str(src), str(out), json.dumps(params or {}), preview_dir],
            timeout=timeout,
        )
    report = _parse_result(res.get("stdout", ""))
    if report is None:
        return {"ok": False, "error": "Blender produced no AVATAR_RESULT line", **res}
    report.setdefault("vrm", str(out))
    report.setdefault("vrm_windows", to_windows(str(out)))
    report["blender_returncode"] = res.get("returncode")
    return report


def validate(vrm_path: str, *, timeout: float | None = 900) -> dict:
    """Import a VRM in headless Blender and report humanoid/expression/geometry."""
    src = Path(vrm_path).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"vrm not found: {src}"}
    if src.suffix.lower() != ".vrm":
        return {"ok": False, "error": f"not a .vrm file: {src}"}

    script = _materialize("vrm_validate.py")
    _materialize("vrm_export.py")  # imported by vrm_validate.py at runtime
    res = blender_run(script, [str(src)], timeout=timeout)
    report = _parse_result(res.get("stdout", ""))
    if report is None:
        return {
            "ok": False,
            "error": "Blender produced no AVATAR_RESULT line",
            **res,
        }
    report["blender_returncode"] = res.get("returncode")
    return report
