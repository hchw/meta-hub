"""Stage 1 (cloud API): image -> textured 3D mesh via Hyper3D Rodin.

Rodin returns a static (unrigged) GLB/FBX. Rig it with ``avatar.rig`` (UniRig)
and export with ``avatar.export_vrm``; no vendor emits VRM directly.

Auth: ``RODIN_API_KEY`` (Hyper3D API access is gated to the Business plan).
Flow: POST /rodin -> POST /status -> POST /download -> fetch signed URL.
"""
from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .env import settings, to_windows

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DONE_STATES = {"Done"}
FAILED_STATES = {"Failed"}


def _read_json(req: urllib.request.Request, timeout: float) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw[:2000]}
        return exc.code, parsed


def _post_json(url: str, payload: dict, api_key: str, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    return _read_json(req, timeout)


def _post_multipart(
    url: str,
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    api_key: str,
    timeout: float,
) -> tuple[int, dict]:
    boundary = "----rodin" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\nContent-Type: {ctype}\r\n\r\n'
        ).encode()
    )
    chunks.append(file_path.read_bytes())
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url,
        data=b"".join(chunks),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    return _read_json(req, timeout)


def _download(url: str, dest: Path, timeout: float) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "meta-hub-avatar/0.1"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as fh:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
    tmp.replace(dest)


def generate_mesh(
    image_path: str,
    output_dir: str | None = None,
    *,
    tier: str | None = None,
    texture_mode: str | None = None,
    geometry_format: str = "glb",
    mesh_mode: str = "Raw",
    poll_interval: float = 5.0,
    max_wait: float = 1500.0,
    timeout: float = 120.0,
) -> dict:
    """Submit a Rodin Gen-2.5 image-to-3D job and download the textured mesh."""
    src = Path(image_path).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"input image not found: {src}"}
    if src.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        return {
            "ok": False,
            "error": f"unsupported image suffix: {src.suffix}",
            "hint": f"supported: {sorted(SUPPORTED_IMAGE_SUFFIXES)}",
        }
    api_key = settings.rodin_api_key
    if not api_key:
        return {
            "ok": False,
            "error": "RODIN_API_KEY is not set",
            "hint": (
                "export RODIN_API_KEY=... (Hyper3D API access is on the Business plan). "
                "Cheaper test route: fal.ai/fal-ai/hyper3d/rodin or replicate.com/hyper3d/rodin."
            ),
        }

    base = settings.rodin_base_url.rstrip("/")
    tier = tier or settings.rodin_tier
    out_dir = Path(output_dir) if output_dir else Path(settings.path("rodin", src.stem))
    out_dir.mkdir(parents=True, exist_ok=True)

    fields = {
        "tier": tier,
        "mesh_mode": mesh_mode,
        "geometry_file_format": geometry_format,
    }
    if texture_mode:
        fields["texture_mode"] = texture_mode

    status, sub = _post_multipart(
        f"{base}/rodin", fields, "images", src, api_key, timeout
    )
    if status not in (200, 201) or sub.get("error") or not sub.get("uuid"):
        return {
            "ok": False,
            "stage": "submit",
            "http_status": status,
            "response": sub,
            "tier": tier,
            "hint": "401/403 usually means the API key lacks API access; 402 means out of credits",
        }

    task_uuid = sub["uuid"]
    subscription_key = (sub.get("jobs") or {}).get("subscription_key")
    if not subscription_key:
        return {
            "ok": False,
            "stage": "submit",
            "error": "generation response has no jobs.subscription_key",
            "response": sub,
        }

    states: list[str] = []
    deadline = time.time() + max_wait
    while time.time() < deadline:
        status, st = _post_json(
            f"{base}/status", {"subscription_key": subscription_key}, api_key, timeout
        )
        if status not in (200, 201):
            return {
                "ok": False,
                "stage": "status",
                "http_status": status,
                "response": st,
                "task_uuid": task_uuid,
            }
        states = [job.get("status", "") for job in (st.get("jobs") or [])]
        if any(state in FAILED_STATES for state in states):
            return {
                "ok": False,
                "stage": "generate",
                "error": "Rodin job failed",
                "states": states,
                "response": st,
                "task_uuid": task_uuid,
            }
        if states and all(state in DONE_STATES for state in states):
            break
        time.sleep(poll_interval)
    else:
        return {
            "ok": False,
            "stage": "poll",
            "error": f"timed out after {max_wait}s",
            "states": states,
            "task_uuid": task_uuid,
        }

    status, dl = _post_json(
        f"{base}/download", {"task_uuid": task_uuid}, api_key, timeout
    )
    items = dl.get("list") or []
    if status not in (200, 201) or not items:
        return {
            "ok": False,
            "stage": "download",
            "http_status": status,
            "response": dl,
            "task_uuid": task_uuid,
        }

    suffix = geometry_format.lower()
    item = next(
        (i for i in items if str(i.get("name", "")).lower().endswith(suffix)), items[0]
    )
    dest = out_dir / (item.get("name") or f"{src.stem}.{geometry_format}")
    try:
        _download(item["url"], dest, timeout=max(timeout, 600))
    except (OSError, urllib.error.URLError) as exc:
        return {
            "ok": False,
            "stage": "fetch",
            "error": f"{type(exc).__name__}: {exc}",
            "task_uuid": task_uuid,
        }

    return {
        "ok": True,
        "mesh_glb": str(dest),
        "mesh_glb_windows": to_windows(str(dest)),
        "size_bytes": dest.stat().st_size,
        "task_uuid": task_uuid,
        "tier": tier,
        "consumed": sub.get("consumed"),
        "files": [i.get("name") for i in items],
        "source_image": str(src),
        "output_dir": str(out_dir),
        "next": "avatar.rig -> avatar.export_vrm (spec_version='0.0')",
    }


if __name__ == "__main__":
    import sys

    image = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(generate_mesh(image, out), ensure_ascii=False, indent=2))
