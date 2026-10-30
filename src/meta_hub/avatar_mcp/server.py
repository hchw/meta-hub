"""MCP server exposing the avatar generation pipeline as tools.

Run over stdio::

    python -m meta_hub.avatar_mcp.server

Tool names use the ``avatar.`` prefix (design D7).
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp.server.mcpserver import MCPServer

from . import blender as _blender
from . import mesh as _mesh
from . import rig as _rig
from . import rodin as _rodin
from . import vrm as _vrm
from .env import settings, to_windows

SERVER_NAME = "avatar-generation"
SERVER_VERSION = "0.1.0"

server = MCPServer(
    SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Offline digital-human (VRM) generation pipeline. Drive it stage by "
        "stage: generate_mesh -> rig -> blender_run/build_expressions -> "
        "export_vrm -> validate. All tools return structured JSON with either "
        "an artifact path or a locatable error."
    ),
)

logger = __import__("logging").getLogger("avatar_mcp")


@server.tool(
    name="avatar.ping",
    description="Health check: returns the server name/version and resolved work dir.",
)
def ping() -> dict:
    return {
        "ok": True,
        "service": SERVER_NAME,
        "version": SERVER_VERSION,
        "work_dir": settings.work_dir,
        "work_dir_windows": to_windows(settings.work_dir),
    }


@server.tool(
    name="avatar.env",
    description=(
        "Report the resolved toolchain paths (TripoSR/UniRig venvs, Blender exe, "
        "work dir) and whether each executable currently exists."
    ),
)
def env_report() -> dict:
    import os

    def probe(path: str) -> dict:
        return {"path": path, "exists": bool(path and os.path.exists(path))}

    return {
        "ok": True,
        "triposr_repo": probe(settings.triposr_repo),
        "triposr_python": probe(settings.triposr_python),
        "unirig_repo": probe(settings.unirig_repo),
        "unirig_python": probe(settings.unirig_python),
        "blender_exe": probe(settings.blender_exe),
        "hf_home": settings.hf_home,
 "rodin_api_key_set": bool(settings.rodin_api_key),
 "rodin_base_url": settings.rodin_base_url,
 "rodin_tier": settings.rodin_tier,
        "work_dir": settings.work_dir,
        "work_dir_windows": to_windows(settings.work_dir),
    }


@server.tool(
    name="avatar.generate_mesh",
    description=(
        "Generate a 3D mesh (GLB) from a reference photo with TripoSR. Returns "
        "the GLB path and size, or a locatable error."
    ),
)
def generate_mesh(
    image_path: str,
    output_dir: str | None = None,
    foreground_ratio: float = 0.85,
    mc_resolution: int = 256,
    no_remove_bg: bool = False,
) -> dict:
    """image_path: absolute path to a person photo (PNG/JPG)."""
    return _mesh.generate_mesh(
        image_path,
        output_dir,
        foreground_ratio=foreground_ratio,
        mc_resolution=mc_resolution,
        no_remove_bg=no_remove_bg,
    )
@server.tool(
 name="avatar.generate_mesh_api",
 description=(
 "Generate a textured 3D mesh from a photo with a cloud API. "
 "provider='hyper3d' submits a Rodin Gen-2.5 job, polls it, and downloads "
 "the GLB. Requires RODIN_API_KEY. Returns the GLB path or a locatable error."
 ),
)
def generate_mesh_api(
 image_path: str,
 output_dir: str | None = None,
 provider: str = "hyper3d",
 tier: str | None = None,
 texture_mode: str | None = None,
 geometry_format: str = "glb",
) -> dict:
 """image_path: absolute path to a person photo; provider: currently hyper3d."""
 if provider != "hyper3d":
  return {"ok": False, "error": f"unsupported provider: {provider}", "hint": "supported: hyper3d"}
 return _rodin.generate_mesh(
  image_path, output_dir, tier=tier, texture_mode=texture_mode,
  geometry_format=geometry_format,
 )
@server.tool(
    name="avatar.rig",
    description=(
        "Rig a mesh (GLB/OBJ/FBX) with UniRig: predict a skeleton then skinning "
        "weights. Returns the rigged FBX and, when possible, a merged rigged GLB."
    ),
)
def rig(
    mesh_path: str,
    output_dir: str | None = None,
    seed: int = 12345,
    faces_target_count: int = 50000,
) -> dict:
    """mesh_path: absolute path to the mesh produced by avatar.generate_mesh."""
    return _rig.rig(
        mesh_path, output_dir, seed=seed, faces_target_count=faces_target_count
    )
@server.tool(
    name="avatar.blender_run",
    description=(
        "Run a bpy script under headless Blender on the Windows host (WSL "
        "interop). Pass the script path and args; /mnt paths in args are "
        "translated to Windows paths automatically. Returns structured output."
    ),
)
def blender_run(
    script: str,
    args: list[str] | None = None,
    factory_startup: bool = False,
    timeout: float = 1800,
) -> dict:
    """script: WSL path to a .py file; args: forwarded after `--`."""
    return _blender.blender_run(
        script, args, factory_startup=factory_startup, timeout=timeout
    )
@server.tool(
    name="avatar.export_vrm",
    description=(
        "Import a rigged model (FBX/GLB) in headless Blender, optionally auto-map "
        "VRM humanoid bones/expressions, and export a VRM. Defaults to VRM 0.0 "
        "(required by VSeeFace); pass spec_version='1.0' for VRM 1.0. Returns the "
        "VRM path plus a bone/expression report."
    ),
)
def export_vrm(
    model_path: str,
    output_vrm: str | None = None,
    auto_humanoid: bool = True,
    auto_expressions: bool = False,
    allow_non_humanoid: bool = False,
    spec_version: str = "0.0",
) -> dict:
    return _vrm.export_vrm(
        model_path, output_vrm,
        auto_humanoid=auto_humanoid,
        auto_expressions=auto_expressions,
        allow_non_humanoid=allow_non_humanoid,
        spec_version=spec_version,
    )


@server.tool(
    name="avatar.build_expressions",
    description=(
        "Assign VRM expressions on a rigged model (auto, optionally importing "
        "ARKit-named shape keys) and export a VRM. Returns the expression set."
    ),
)
def build_expressions(
    model_path: str,
    output_vrm: str | None = None,
    mode: str = "geo",
    params: dict | None = None,
    previews: bool = True,
) -> dict:
    return _vrm.build_expressions(
        model_path, output_vrm, mode=mode, params=params, previews=previews
    )


@server.tool(
    name="avatar.validate",
    description=(
        "Validate a VRM: import in headless Blender and report humanoid bone "
        "mapping, VRM preset expressions, and geometry/volume stats."
    ),
)
def validate(vrm_path: str) -> dict:
    return _vrm.validate(vrm_path)


def main() -> None:
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()
