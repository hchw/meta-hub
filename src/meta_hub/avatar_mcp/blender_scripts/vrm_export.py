"""Headless Blender: import a rigged model and export a VRM.

Invoked by ``avatar.export_vrm`` as::

    blender.exe --background --python vrm_export.py -- <in> <out> <auto_humanoid> <auto_expr> <allow_non_humanoid> [<spec_version>]

``spec_version`` is ``0.0`` (default, required by VSeeFace) or ``1.0``.

Prints one ``AVATAR_RESULT {json}`` line with the outcome and a bone/expression
report. For VRM 0.0 the add-on requires a humanoid ``neck`` bone; when the
rigged input lacks one, a neck bone is inserted between ``head`` and its parent
and mapped before export.
"""
import bpy
import addon_utils
import json
import os
import sys
import traceback

HUMANOID_SLOTS = [
    "hips", "spine", "chest", "upper_chest", "neck", "head",
    "left_shoulder", "left_upper_arm", "left_lower_arm", "left_hand",
    "right_shoulder", "right_upper_arm", "right_lower_arm", "right_hand",
    "left_upper_leg", "left_lower_leg", "left_foot", "left_toes",
    "right_upper_leg", "right_lower_leg", "right_foot", "right_toes",
    "left_eye", "right_eye", "jaw",
]

# VRM 0.0 uses camelCase human-bone keys.
VRM0_HUMANOID_SLOTS = [
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes",
    "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes",
    "leftEye", "rightEye", "jaw",
]

VRM_PRESET_EXPRESSIONS = [
    "happy", "angry", "sad", "relaxed", "surprised", "aa", "ih", "ou", "ee",
    "oh", "blink", "blinkLeft", "blinkRight", "lookUp", "lookDown",
    "lookLeft", "lookRight", "neutral",
]

VRM0_PRESET_EXPRESSIONS = [
    "happy", "angry", "sad", "relaxed", "surprised",
    "a", "i", "u", "e", "o", "blink", "blinkLeft", "blinkRight",
    "lookUp", "lookDown", "lookLeft", "lookRight", "neutral",
]


def emit(**kw):
    print("AVATAR_RESULT " + json.dumps(kw, ensure_ascii=False))


def _is_vrm0(arm):
    try:
        return bool(arm.data.vrm_addon_extension.is_vrm0())
    except Exception:
        return arm.data.vrm_addon_extension.spec_version == "0.0"


def vrm0_assignments(arm):
    assigned = {}
    for entry in arm.data.vrm_addon_extension.vrm0.humanoid.human_bones:
        name = getattr(getattr(entry, "node", None), "bone_name", "")
        if name:
            assigned[entry.bone] = name
    return assigned


def humanoid_report(arm):
    ext = arm.data.vrm_addon_extension
    if _is_vrm0(arm):
        assigned = vrm0_assignments(arm)
        missing = [slot for slot in VRM0_HUMANOID_SLOTS if slot not in assigned]
        try:
            correct = bool(ext.vrm0.humanoid.bones_are_correctly_assigned())
        except Exception:
            correct = None
        return {
            "assigned": assigned,
            "missing": missing,
            "correct": correct,
            "spec_version": "0.0",
        }

    hb = ext.vrm1.humanoid.human_bones
    assigned, missing = {}, []
    for slot in HUMANOID_SLOTS:
        entry = getattr(hb, slot, None)
        name = ""
        if entry is not None:
            node = getattr(entry, "node", None)
            name = getattr(node, "bone_name", "") if node is not None else ""
        if name:
            assigned[slot] = name
        else:
            missing.append(slot)
    try:
        correct = bool(hb.bones_are_correctly_assigned())
    except Exception:
        correct = None
    return {"assigned": assigned, "missing": missing, "correct": correct, "spec_version": "1.0"}


def expression_report(arm):
    ext = arm.data.vrm_addon_extension
    if _is_vrm0(arm):
        try:
            groups = ext.vrm0.blend_shape_master.blend_shape_groups
            present, detail = [], []
            for g in groups:
                preset = getattr(g, "preset_name", "") or ""
                name = getattr(g, "name", "") or ""
                detail.append({"preset": preset, "name": name})
                if preset:
                    present.append(preset)
            return {
                "present": sorted(set(present)),
                "vrm_presets_present": [e for e in VRM0_PRESET_EXPRESSIONS if e in present],
                "groups": detail,
                "bound_count": len([d for d in detail if d["preset"]]),
            }
        except Exception as e:
            return {"error": repr(e)}

    try:
        exprs = ext.vrm1.expressions
        d = exprs.all_name_to_expression_dict()
        bound = {}
        for name, e in d.items():
            binds = []
            for b in e.morph_target_binds:
                binds.append(
                    {
                        "mesh": b.node.mesh_object_name if b.node else "",
                        "shape_key": b.index,
                        "weight": round(b.weight, 3),
                    }
                )
            if binds:
                bound[name] = binds
        return {
            "present": sorted(d.keys()),
            "vrm_presets_present": [e for e in VRM_PRESET_EXPRESSIONS if e in d],
            "bound": bound,
            "bound_count": len(bound),
        }
    except Exception as e:
        return {"error": repr(e)}


VRM0_REQUIRED = [
    "hips", "spine", "chest", "neck", "head",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
]


def complete_vrm0_rig(arm, warnings):
    """Insert synthetic VRM0 bones that simple auto-rigs collapse away.

    VRM 0.0 requires ``chest``, ``neck`` and shoulders. UniRig frequently emits
    ``spine -> head`` and ``spine -> upperArm`` with none of those bones. We add
    zero-weight synthetic bones (Chest/Neck/<Side>Shoulder) and rebuild the
    hierarchy so export passes, without touching existing rest matrices.
    """
    assigned = vrm0_assignments(arm)
    if all(k in assigned for k in VRM0_REQUIRED):
        return
    if not all(assigned.get(k) for k in ("spine", "head", "leftUpperArm", "rightUpperArm")):
        warnings.append("cannot complete VRM0 rig: missing spine/head/upper-arm anchors")
        return

    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        eb = arm.data.edit_bones
        spine = eb[assigned["spine"]]
        head = eb[assigned["head"]]
        left_arm = eb[assigned["leftUpperArm"]]
        right_arm = eb[assigned["rightUpperArm"]]

        def ensure(name, head_co, tail_co, parent):
            bone = eb.get(name) or eb.new(name)
            bone.head = head_co
            bone.tail = tail_co
            bone.parent = parent
            bone.use_connect = False
            return bone

        if "chest" in assigned:
            chest = eb[assigned["chest"]]
        else:
            chest = ensure("Chest", spine.head.copy(), spine.tail.copy(), spine)

        if "neck" not in assigned:
            neck = ensure("Neck", chest.tail.copy(), head.head.copy(), chest)
            if (neck.tail - neck.head).length < 1e-6:
                neck.tail = head.head.lerp(head.tail, 0.25)
            head.parent = neck
            head.use_connect = False

        for key, arm_bone, name in (
            ("leftShoulder", left_arm, "LeftShoulder"),
            ("rightShoulder", right_arm, "RightShoulder"),
        ):
            if key in assigned:
                continue
            shoulder = ensure(name, chest.tail.copy(), arm_bone.head.copy(), chest)
            if (shoulder.tail - shoulder.head).length < 1e-6:
                shoulder.tail = arm_bone.head.lerp(arm_bone.tail, 0.2)
            arm_bone.parent = shoulder
            arm_bone.use_connect = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    synthetic = {
        "chest": ("chest", "Chest"),
        "neck": ("neck", "Neck"),
        "leftShoulder": ("leftShoulder", "LeftShoulder"),
        "rightShoulder": ("rightShoulder", "RightShoulder"),
    }
    for entry in arm.data.vrm_addon_extension.vrm0.humanoid.human_bones:
        if entry.bone not in synthetic:
            continue
        if getattr(getattr(entry, "node", None), "bone_name", ""):
            continue
        _, bone_name = synthetic[entry.bone]
        entry.node.bone_name = bone_name
    warnings.append("completed VRM0 rig with synthetic chest/neck/shoulder bones")


def set_vrm0_bone(arm, bone_key, bone_name):
    for entry in arm.data.vrm_addon_extension.vrm0.humanoid.human_bones:
        if entry.bone == bone_key:
            entry.node.bone_name = bone_name
            return True
    return False


def assign_humanoid(arm, *, is_vrm0, allow_non_humanoid, warnings):
    try:
        bpy.context.view_layer.objects.active = arm
        if is_vrm0:
            res = bpy.ops.vrm.assign_vrm0_humanoid_human_bones_automatically(
                armature_object_name=arm.name
            )
        else:
            hb = arm.data.vrm_addon_extension.vrm1.humanoid.human_bones
            hb.allow_non_humanoid_rig = allow_non_humanoid
            res = bpy.ops.vrm.assign_vrm1_humanoid_human_bones_automatically(
                armature_object_name=arm.name
            )
        if res != {"FINISHED"}:
            warnings.append(f"auto humanoid returned {res}")
    except Exception as e:
        warnings.append(f"auto humanoid failed: {e!r}")





def ensure_mtoon1_materials(warnings):
    """Enable MToon1 so the VRM0 exporter downgrades materials *with* textures.

    A glTF-imported Principled BSDF material takes the legacy glTF-shader path
    in the VRM0 exporter, which drops base-color textures. Turning on the
    material's ``mtoon1`` extension routes it through
    ``write_mtoon1_downgraded_material`` and preserves the texture.
    """
    for material in list(bpy.data.materials):
        if not material.use_nodes or not material.node_tree:
            continue
        try:
            ext = material.vrm_addon_extension.mtoon1
            if ext.enabled:
                continue
            if not any(node.type == "BSDF_PRINCIPLED" for node in material.node_tree.nodes):
                continue
            ext.enabled = True
            warnings.append(f"enabled MToon1 for VRM0 export: {material.name}")
        except Exception as e:  # noqa: BLE001 - best effort material conversion
            warnings.append(f"MToon1 conversion failed for {material.name}: {e!r}")


def import_model(path):
    lower = path.lower()
    if lower.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    elif lower.endswith(".vrm"):
        bpy.ops.import_scene.vrm(filepath=path)
    elif lower.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise ValueError("unsupported input: " + path)


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    inp, out = args[0], args[1]
    auto_humanoid = len(args) < 3 or args[2] == "1"
    auto_expr = len(args) >= 4 and args[3] == "1"
    allow_non_humanoid = len(args) >= 5 and args[4] == "1"
    spec_version = args[5] if len(args) >= 6 and args[5] else "0.0"
    is_vrm0 = spec_version == "0.0"

    addon_utils.enable("bl_ext.user_default.vrm", default_set=True, persistent=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    import_model(inp)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        emit(ok=False, error="no armature in input model", input=inp)
        return
    arm = arms[0]

    warnings = []
    ext = arm.data.vrm_addon_extension
    ext.spec_version = spec_version

    if auto_humanoid:
        assign_humanoid(
            arm,
            is_vrm0=is_vrm0,
            allow_non_humanoid=allow_non_humanoid,
            warnings=warnings,
        )
    if is_vrm0:
        complete_vrm0_rig(arm, warnings)
        ensure_mtoon1_materials(warnings)
    if auto_expr and not is_vrm0:
        try:
            bpy.context.view_layer.objects.active = arm
            bpy.ops.vrm.assign_vrm1_expressions_automatically()
        except Exception as e:
            warnings.append(f"auto expressions failed: {e!r}")
    elif auto_expr and is_vrm0:
        warnings.append("auto expressions skipped: VRM0 uses blendShapeMaster, see tasks 4.2/4.3")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    export_res = bpy.ops.export_scene.vrm(filepath=out)

    report = {
        "ok": os.path.exists(out),
        "input": inp,
        "output": out,
        "spec_version": spec_version,
        "size_bytes": os.path.getsize(out) if os.path.exists(out) else -1,
        "export_result": list(export_res),
        "humanoid": humanoid_report(arm),
        "expressions": expression_report(arm),
        "warnings": warnings,
    }
    if not report["ok"]:
        report["error"] = "VRM export produced no file"
    emit(**report)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        emit(ok=False, error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc()[-2000:])
        sys.exit(1)
