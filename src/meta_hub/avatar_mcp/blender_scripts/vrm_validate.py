"""Headless Blender: validate a VRM (humanoid mapping, expressions, geometry).

Invoked by ``avatar.validate`` as::

    blender.exe --background --python vrm_validate.py -- <vrm>

Prints one ``AVATAR_RESULT {json}`` line.
"""
import bpy
import addon_utils
import json
import os
import sys
import traceback

# Ensure the sibling helper module is importable when Blender execs this file.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
except NameError:
    pass

from vrm_export import HUMANOID_SLOTS, VRM_PRESET_EXPRESSIONS, humanoid_report, expression_report


def geometry_report():
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    total_verts = sum(len(m.data.vertices) for m in meshes)
    total_tris = sum(len(m.data.loop_triangles) for m in meshes)
    return {
        "mesh_count": len(meshes),
        "total_vertices": total_verts,
        "total_triangles": total_tris,
        "materials": len(bpy.data.materials),
        "shape_keys": sum(len(m.data.shape_keys.key_blocks) if m.data.shape_keys else 0 for m in meshes),
    }


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    vrm = args[0]
    addon_utils.enable("bl_ext.user_default.vrm", default_set=True, persistent=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.vrm(filepath=vrm)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    report = {
        "ok": bool(arms),
        "vrm": vrm,
        "size_bytes": os.path.getsize(vrm) if os.path.exists(vrm) else -1,
        "geometry": geometry_report(),
    }
    if not arms:
        report["error"] = "no armature after importing VRM (not a valid VRM?)"
        print("AVATAR_RESULT " + json.dumps(report, ensure_ascii=False))
        return
    arm = arms[0]
    report["humanoid"] = humanoid_report(arm)
    report["expressions"] = expression_report(arm)
    report["is_vrm1"] = bool(arm.data.vrm_addon_extension.is_vrm1())
    report["is_vrm0"] = bool(arm.data.vrm_addon_extension.is_vrm0())
    try:
        bpy.context.view_layer.objects.active = arm
        res = bpy.ops.vrm.model_validate()
        report["model_validate_result"] = list(res)
    except Exception as e:
        report["model_validate_error"] = repr(e)
    print("AVATAR_RESULT " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("AVATAR_RESULT " + json.dumps(
            {"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2000:]},
            ensure_ascii=False,
        ))
        sys.exit(1)
