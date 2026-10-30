"""Headless Blender: build/assign VRM expressions on a rigged model.

Invoked by ``avatar.build_expressions`` as::

    blender.exe --background --python build_expressions.py -- <in> <out> <from_arkit>

Optionally imports ARKit-named shape keys into VRM expressions, runs the
add-on's automatic assignment, exports a VRM and reports the expression set.
"""
import bpy
import addon_utils
import json
import os
import sys
import traceback

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
except NameError:
    pass

from vrm_export import expression_report, import_model  # noqa: E402


def emit(**kw):
    print("AVATAR_RESULT " + json.dumps(kw, ensure_ascii=False))


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    inp, out = args[0], args[1]
    from_arkit = len(args) >= 3 and args[2] == "1"

    addon_utils.enable("bl_ext.user_default.vrm", default_set=True, persistent=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    import_model(inp)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        emit(ok=False, error="no armature in input model", input=inp)
        return
    arm = arms[0]
    bpy.context.view_layer.objects.active = arm

    warnings = []
    if from_arkit:
        try:
            bpy.ops.vrm.assign_vrm1_expressions_from_arkit()
        except Exception as e:
            warnings.append(f"from_arkit failed: {e!r}")
    try:
        bpy.ops.vrm.assign_vrm1_expressions_automatically()
    except Exception as e:
        warnings.append(f"auto expressions failed: {e!r}")

    report = {"ok": True, "input": inp, "expressions": expression_report(arm),
              "warnings": warnings}
    if out and out != "-":
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            bpy.ops.export_scene.vrm(filepath=out)
            report["output"] = out
            report["size_bytes"] = os.path.getsize(out) if os.path.exists(out) else -1
            report["ok"] = os.path.exists(out)
        except Exception as e:
            report["ok"] = False
            report["error"] = f"export failed: {e!r}"
    emit(**report)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        emit(ok=False, error=f"{type(e).__name__}: {e}",
             traceback=traceback.format_exc()[-2000:])
        sys.exit(1)
