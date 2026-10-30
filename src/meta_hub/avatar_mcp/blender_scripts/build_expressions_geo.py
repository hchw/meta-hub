"""Headless Blender: procedurally build VRM expressions (shape keys) on a mesh.

Dependency-free alternative to Faceit. The head / eyes / mouth are located by
projecting the mesh into an orthonormal frame derived from the mapped humanoid
bones:

* ``up``    = hips -> head (body axis)
* ``lr``    = left_shoulder -> right_shoulder
* ``front`` = foot -> toes (feet point forward)

The head is the top ``body_height / 7`` slab; eye/mouth lines are fractions of
that head height. This is robust to UniRig's generic ``bone_N`` names and to the
model being arbitrarily rotated.

Invoked by ``avatar.build_expressions`` (geo mode)::

    blender.exe --background --python build_expressions_geo.py -- <in> <out> [params-json] [preview-dir]

Prints ``AVATAR_RESULT {json}``.
"""
import bpy
import addon_utils
import json
import math
import os
import sys
import traceback
from mathutils import Vector

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
except NameError:
    pass

from vrm_export import humanoid_report, import_model  # noqa: E402

DEFAULTS = {
    "body_heads": 7.0,        # body height / head height
    "blink": 0.9,
    "mouth_open": 1.0,
    "mouth_width": 1.0,
    "brow": 0.8,
    "eye_s": 0.16,            # eye horizontal offset (fraction of head)
    "eye_u": 0.45,            # eye line below top (fraction of head)
    "eye_ru": 0.13, "eye_rs": 0.16, "eye_rf": 0.40,
    "mouth_u": 0.72,
    "mouth_ru": 0.16, "mouth_rs": 0.22, "mouth_rf": 0.40,
    "min_moved_vertices": 8,
    "render_preview": 1,
}


def emit(**kw):
    print("AVATAR_RESULT " + json.dumps(kw, ensure_ascii=False))


def dot(a, b):
    return a.dot(b)


def bone_world(arm, name):
    b = arm.data.bones.get(name) if name else None
    if b is None:
        return None, None
    return arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local


def slot_bone_name(hb, slot):
    entry = getattr(hb, slot, None)
    if entry is None:
        return ""
    node = getattr(entry, "node", None)
    return getattr(node, "bone_name", "") if node is not None else ""


def orthonormal_frame(arm, hb):
    head_name = slot_bone_name(hb, "head")
    hips_name = slot_bone_name(hb, "hips")
    hh, ht = bone_world(arm, head_name) if head_name else (None, None)
    ph, _ = bone_world(arm, hips_name) if hips_name else (None, None)
    if hh is None:
        return None
    up = (hh - ph) if ph is not None else (ht - hh)
    if up.length < 1e-6:
        return None
    up.normalize()

    lh, _ = bone_world(arm, slot_bone_name(hb, "left_shoulder"))
    rh, _ = bone_world(arm, slot_bone_name(hb, "right_shoulder"))
    if lh is None or rh is None:
        lh, _ = bone_world(arm, slot_bone_name(hb, "left_upper_leg"))
        rh, _ = bone_world(arm, slot_bone_name(hb, "right_upper_leg"))
    if lh is None or rh is None:
        return None
    lr = lh - rh
    lr -= up * dot(lr, up)
    if lr.length < 1e-6:
        return None
    lr.normalize()

    front = None
    for side in ("left", "right"):
        fh, _ = bone_world(arm, slot_bone_name(hb, side + "_foot"))
        th, _ = bone_world(arm, slot_bone_name(hb, side + "_toes"))
        if fh is not None and th is not None and (th - fh).length > 1e-6:
            front = th - fh
            break
    if front is None:
        front = up.cross(lr)
    front -= up * dot(front, up)
    front -= lr * dot(front, lr)
    if front.length < 1e-6:
        front = up.cross(lr)
    front.normalize()
    return up, lr, front


def gauss(du, ds, df, ru, rs, rf):
    return math.exp(-0.5 * ((du / ru) ** 2 + (ds / rs) ** 2 + (df / rf) ** 2))


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    if len(args) < 2:
        emit(ok=False, error="usage: <in> <out> [params-json] [preview-dir]")
        return
    inp, out = args[0], args[1]
    params = dict(DEFAULTS)
    if len(args) >= 3 and args[2].strip():
        try:
            params.update(json.loads(args[2]))
        except json.JSONDecodeError as e:
            emit(ok=False, error=f"bad params json: {e}")
            return
    preview_dir = args[3] if len(args) >= 4 else ""

    addon_utils.enable("bl_ext.user_default.vrm", default_set=True, persistent=True)
    bpy.ops.wm.read_homefile(use_empty=True)
    import_model(inp)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not arms or not meshes:
        emit(ok=False, error="need an armature and a mesh")
        return
    arm = arms[0]
    mesh_obj = max(meshes, key=lambda o: len(o.data.vertices))
    mesh = mesh_obj.data
    bpy.context.view_layer.objects.active = arm

    hb = arm.data.vrm_addon_extension.vrm1.humanoid.human_bones
    bpy.ops.vrm.assign_vrm1_humanoid_human_bones_automatically(
        armature_object_name=arm.name
    )
    frame = orthonormal_frame(arm, hb)
    if frame is None:
        emit(ok=False, error="could not derive an orthonormal frame from humanoid bones",
             humanoid=humanoid_report(arm))
        return
    up, lr, front = frame

    mw = mesh_obj.matrix_world
    mwi = mw.inverted()
    base_world = [mw @ vv.co for vv in mesh.vertices]
    # Coordinates in the bone frame: (U, S, F) = (up, left-right, front).
    U = [dot(p, up) for p in base_world]
    S = [dot(p, lr) for p in base_world]
    Fv = [dot(p, front) for p in base_world]

    u_max = max(U)
    body_h = max(U) - min(U)
    H = max(body_h / params["body_heads"], 1e-3)

    head_idx = [i for i, u in enumerate(U) if u >= u_max - H]
    if not head_idx:
        emit(ok=False, error="empty head slab")
        return
    s_hc = sum(S[i] for i in head_idx) / len(head_idx)
    f_hc = sum(Fv[i] for i in head_idx) / len(head_idx)
    f_max = max(Fv[i] for i in head_idx)

    u_hc = u_max - 0.5 * H
    u_eye = u_max - params["eye_u"] * H
    u_mouth = u_max - params["mouth_u"] * H
    eye_off = params["eye_s"] * H
    eye_s_list = [s_hc - eye_off, s_hc + eye_off]
    f_face = f_max - 0.12 * H

    def to_world(u, s, f):
        return up * u + lr * s + front * f

    head_center = to_world(u_hc, s_hc, f_hc)

    def eye_w(u, s, f):
        return max(
            gauss(u - u_eye, s - es, f - f_face,
                  params["eye_ru"] * H, params["eye_rs"] * H, params["eye_rf"] * H)
            for es in eye_s_list
        )

    def mouth_w(u, s, f):
        return gauss(u - u_mouth, s - s_hc, f - f_face,
                     params["mouth_ru"] * H, params["mouth_rs"] * H,
                     params["mouth_rf"] * H)

    def brow_w(u, s, f):
        return gauss(u - (u_eye + 0.14 * H), s - s_hc, f - f_face,
                     0.14 * H, 0.42 * H, 0.40 * H)

    # Expressions are built in frame space as (dU, dS, dF) per vertex.
    def gen_blink(side=None):
        d = {}
        targets = eye_s_list if side is None else (
            [eye_s_list[0]] if side == "L" else [eye_s_list[1]])
        for i in range(len(base_world)):
            w = max(gauss(U[i] - u_eye, S[i] - es, Fv[i] - f_face,
                          params["eye_ru"] * H, params["eye_rs"] * H,
                          params["eye_rf"] * H) for es in targets)
            if w < 1e-4:
                continue
            dU = -(U[i] - u_eye) * params["blink"] * w
            if abs(dU) > 1e-6:
                d[i] = (dU, 0.0, 0.0)
        return d

    def gen_mouth(open_amt=0.0, width_amt=0.0, pucker=0.0, corner_up=0.0):
        d = {}
        for i in range(len(base_world)):
            w = mouth_w(U[i], S[i], Fv[i])
            if w < 1e-4:
                continue
            du = U[i] - u_mouth
            ds = S[i] - s_hc
            dU = dS = dF = 0.0
            if open_amt:
                lower = max(0.0, -du / (params["mouth_ru"] * H))
                dU += -params["mouth_open"] * open_amt * w * (0.3 + 0.7 * lower) * 0.16 * H
            if width_amt:
                dS += math.copysign(1.0, ds if abs(ds) > 1e-9 else 1.0) * \
                    params["mouth_width"] * width_amt * w * 0.08 * H
            if pucker:
                dS += -math.copysign(1.0, ds if abs(ds) > 1e-9 else 1.0) * w * pucker * 0.06 * H
                dF += -w * pucker * 0.04 * H
            if corner_up:
                corner = math.exp(-((abs(ds) - 0.18 * H) / (0.10 * H)) ** 2)
                dU += corner * w * corner_up * 0.07 * H
            if abs(dU) + abs(dS) + abs(dF) > 1e-6:
                d[i] = (dU, dS, dF)
        return d

    def gen_brow(up_amt=0.0, down_amt=0.0, inner=0.0):
        d = {}
        for i in range(len(base_world)):
            w = brow_w(U[i], S[i], Fv[i])
            if w < 1e-4:
                continue
            ds = S[i] - s_hc
            dU = (up_amt - down_amt) * w * params["brow"] * 0.06 * H
            if inner:
                inner_w = math.exp(-((abs(ds) - 0.10 * H) / (0.12 * H)) ** 2)
                dU += inner * inner_w * w * params["brow"] * 0.05 * H
            if abs(dU) > 1e-6:
                d[i] = (dU, 0.0, 0.0)
        return d

    def gen_look(axis, amt):
        d = {}
        for i in range(len(base_world)):
            w = eye_w(U[i], S[i], Fv[i])
            if w < 1e-4:
                continue
            if axis == "u":
                d[i] = (amt * 0.05 * H * w, 0.0, 0.0)
            else:
                d[i] = (0.0, amt * 0.05 * H * w, 0.0)
        return d

    def combine(*parts):
        out_d = {}
        for part in parts:
            for i, delta in part.items():
                a = out_d.get(i, (0.0, 0.0, 0.0))
                out_d[i] = (a[0] + delta[0], a[1] + delta[1], a[2] + delta[2])
        return out_d

    def scale(part, f):
        return {i: (a * f, b * f, c * f) for i, (a, b, c) in part.items()}

    expressions = {
        "blink": gen_blink(),
        "blinkLeft": gen_blink("L"),
        "blinkRight": gen_blink("R"),
        "aa": gen_mouth(open_amt=1.0),
        "oh": gen_mouth(open_amt=0.75, pucker=0.25),
        "ou": gen_mouth(pucker=1.0, open_amt=0.2),
        "ih": gen_mouth(width_amt=0.8, open_amt=0.2),
        "ee": gen_mouth(width_amt=1.0, open_amt=0.3),
        "happy": combine(gen_mouth(corner_up=1.0, open_amt=0.15), scale(gen_blink(), 0.35)),
        "relaxed": gen_mouth(corner_up=0.35, open_amt=0.05),
        "angry": combine(gen_brow(down_amt=1.0), gen_mouth(corner_up=-0.5, open_amt=0.1)),
        "sad": combine(gen_brow(inner=1.0, down_amt=0.3), gen_mouth(corner_up=-0.35)),
        "surprised": combine(gen_mouth(open_amt=1.0), gen_brow(up_amt=1.0)),
        "lookUp": gen_look("u", 1.0),
        "lookDown": gen_look("u", -1.0),
        "lookLeft": gen_look("s", -1.0),
        "lookRight": gen_look("s", 1.0),
    }

    if mesh.shape_keys:
        mesh_obj.shape_key_clear()
    basis = mesh_obj.shape_key_add(name="Basis", from_mix=False)
    for i, vv in enumerate(mesh.vertices):
        basis.data[i].co = vv.co

    name_to_expr = arm.data.vrm_addon_extension.vrm1.expressions.all_name_to_expression_dict()
    stats, skipped = {}, {}
    for name, deltas in expressions.items():
        if len(deltas) < params["min_moved_vertices"]:
            skipped[name] = f"only {len(deltas)} vertices moved"
            continue
        kb = mesh_obj.shape_key_add(name=name, from_mix=False)
        max_delta = 0.0
        for i, (dU, dS, dF) in deltas.items():
            delta = up * dU + lr * dS + front * dF
            kb.data[i].co = mwi @ (base_world[i] + delta)
            max_delta = max(max_delta, delta.length)
        expr = name_to_expr.get(name)
        if expr is not None:
            expr.morph_target_binds.add()
            bind = expr.morph_target_binds[-1]
            bind.node.mesh_object_name = mesh_obj.name
            bind.index = kb.name
            bind.weight = 1.0
        stats[name] = {"vertices": len(deltas),
                       "max_delta": round(max_delta, 5),
                       "pct_of_head": round(100 * max_delta / H, 2)}

    previews = []
    if preview_dir and params.get("render_preview"):
        try:
            previews = render_previews(mesh_obj, head_center, up, lr, front, H,
                                       preview_dir, list(stats))
        except Exception as e:
            skipped["_preview"] = repr(e)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    export_res = bpy.ops.export_scene.vrm(filepath=out)
    report = {
        "ok": os.path.exists(out),
        "input": inp,
        "output": out,
        "size_bytes": os.path.getsize(out) if os.path.exists(out) else -1,
        "shape_keys": [kb.name for kb in mesh.shape_keys.key_blocks] if mesh.shape_keys else [],
        "expressions_built": stats,
        "skipped": skipped,
        "humanoid": humanoid_report(arm),
        "head_height": round(H, 4),
        "body_height": round(body_h, 4),
        "axes": {"up": [round(x, 3) for x in up],
                 "lr": [round(x, 3) for x in lr],
                 "front": [round(x, 3) for x in front]},
        "previews": previews,
        "export_result": list(export_res),
    }
    if not report["ok"]:
        report["error"] = "VRM export produced no file"
    emit(**report)


def render_previews(mesh_obj, head_center, up, lr, front, H, preview_dir, names):
    os.makedirs(preview_dir, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    try:
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "SINGLE"
    except Exception:
        pass

    cam_data = bpy.data.cameras.new("PreviewCam")
    cam = bpy.data.objects.new("PreviewCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    outputs = []
    key_blocks = mesh_obj.data.shape_keys.key_blocks if mesh_obj.data.shape_keys else []
    views = {
        "front": front,
        "side": lr,
        "threequarter": (front + lr * 0.7).normalized(),
    }
    for view_name, view_dir in views.items():
        cam.location = head_center + view_dir * (2.4 * H) + up * (0.15 * H)
        direction = head_center - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        for name in names:
            for kb in key_blocks:
                kb.value = 1.0 if kb.name == name else 0.0
            path = os.path.join(preview_dir, f"{name}_{view_name}.png")
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            outputs.append(path)
    for kb in key_blocks:
        kb.value = 0.0
    return outputs


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        emit(ok=False, error=f"{type(e).__name__}: {e}",
             traceback=traceback.format_exc()[-3000:])
        sys.exit(1)
