#!/usr/bin/env python3
"""Ask a vision model to describe a local image (bypasses Pi's text-only session)."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from meta_hub.agent.pi import load_pi_llm  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--prompt", default=(
        "Describe the avatar's pose precisely. Focus on shoulders, elbows, "
        "forearms, hands, and which way the palms face. Be concise."))
    ap.add_argument("--model", default="google/gemini-3.5-flash")
    args = ap.parse_args(argv)
    path = Path(args.image)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    cfg = load_pi_llm()
    body = {
        "model": args.model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": args.prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{data}"}},
            ],
        }],
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        cfg.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
            "Accept": "application/json",
            "User-Agent": "meta-hub/0.1 vision-check",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            answer = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(errors="replace"), file=sys.stderr)
        return 1
    msg = answer["choices"][0]["message"]
    print(msg.get("content") or msg.get("reasoning_content") or answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
