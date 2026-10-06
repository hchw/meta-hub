"""Feasibility measurement (task 4.3): sample GPU load and pipeline cadence.

Produces a small report of GPU utilization / peak memory and the expression
send rate over a window, so the "three components at once" run is recorded
rather than eyeballed.
"""
from __future__ import annotations
import statistics
import subprocess
import time


def _nvidia_smi() -> tuple[float, float] | None:
    for exe in ("nvidia-smi", "nvidia-smi.exe"):
        try:
            out = subprocess.check_output(
                [exe, "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                text=True, timeout=5,
            ).strip()
        except Exception:
            continue
        line = out.splitlines()[0]
        try:
            u, m = (float(x.strip()) for x in line.split(",")[:2])
            return u, m
        except Exception:
            continue
    return None


def sample_gpu(seconds: float = 20.0, interval: float = 0.5) -> dict:
    util: list[float] = []
    mem: list[float] = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        s = _nvidia_smi()
        if s:
            util.append(s[0])
            mem.append(s[1])
        time.sleep(interval)
    return {
        "samples": len(util),
        "gpu_util_avg_pct": round(statistics.mean(util), 1) if util else None,
        "gpu_util_peak_pct": round(max(util), 1) if util else None,
        "gpu_mem_avg_mb": round(statistics.mean(mem), 1) if mem else None,
        "gpu_mem_peak_mb": round(max(mem), 1) if mem else None,
    }


def report(seconds: float = 20.0) -> str:
    stats = sample_gpu(seconds)
    lines = [f"# meta-hub feasibility report ({time.strftime('%Y-%m-%d %H:%M:%S')})", ""]
    for k, v in stats.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)
