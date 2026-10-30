"""Avatar (VRM) generation MCP control plane.

Exposes the offline ``photo -> VRM`` pipeline (mesh generation, rigging,
headless Blender edits, VRM export, validation) as MCP tools so an agent can
drive the whole process without touching any GUI.

See ``openspec/changes/generate-vrm-avatar/`` for the spec and design.
"""
