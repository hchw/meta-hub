#!/usr/bin/env python3
"""Enable VNyan's per-VMC-layer 'Track Blendshapes' flag.

VNyan ignores /VMC/Ext/Blend/Val on a layer whose ``trackBlendshapes`` is 0.
That looks like "bones work but face never moves".

Close VNyan first, run this, then start VNyan again.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_GLOB = "/mnt/c/Users/*/AppData/LocalLow/Suvidriel/VNyan/settings.json"


def vnyan_running() -> bool:
    try:
        out = subprocess.run(
            ["/mnt/c/Windows/System32/tasklist.exe", "/FI", "IMAGENAME eq VNyan.exe"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
        return "VNyan.exe" in out
    except Exception:
        return False


def find_settings() -> list[Path]:
    return [p for p in Path("/").glob(DEFAULT_GLOB.lstrip("/")) if p.exists()]


def patch(path: Path, port: str, value: float, dry_run: bool) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    changed = []
    for i, layer in enumerate(data.get("VMCLayers", [])):
        if port and str(layer.get("port")) != port:
            continue
        old = layer.get("trackBlendshapes")
        layer["trackBlendshapes"] = value
        changed.append(f"VMCLayers[{i}] port={layer.get('port')} "
                       f"trackBlendshapes {old!r} -> {value}")
    if not changed:
        return [f"no matching VMC layer for port {port!r}"]
    if dry_run:
        return changed
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, path.with_name(f"settings.json.bak-{stamp}"))
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    # VNyan keeps an identical .dat snapshot; keep it in sync when present.
    dat = path.with_name("settings.json.dat")
    if dat.exists():
        dat.write_text(text, encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="3334", help="VMC layer port (default 3334)")
    ap.add_argument("--value", type=float, default=1.0)
    ap.add_argument("--settings", type=Path, action="append")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="patch even if VNyan is running (it may overwrite on exit)")
    args = ap.parse_args()

    if vnyan_running() and not args.force and not args.dry_run:
        print("VNyan.exe is running. Close it first (or pass --force, but it may "
              "overwrite settings on exit).", file=sys.stderr)
        return 2

    paths = args.settings or find_settings()
    if not paths:
        print("settings.json not found under /mnt/c/Users/*/AppData/LocalLow/Suvidriel/VNyan/",
              file=sys.stderr)
        return 1
    for path in paths:
        print(f"# {path}")
        for line in patch(path, args.port, args.value, args.dry_run):
            print("  " + line)
    if not args.dry_run:
        print("\nNow start VNyan again and re-send: "
              "python tools/vmc_probe.py --port 3334 --profile vrm1 --blend aa")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
