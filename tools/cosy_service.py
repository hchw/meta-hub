#!/usr/bin/env python3
"""Resident CosyVoice service (design D11, task 1.1).

Run this inside the CosyVoice venv.  The model is loaded exactly once and then
served over a local TCP socket; every request streams audio chunks back so the
caller can start playback before synthesis finishes.

    /path/to/CosyVoice/.venv/bin/python tools/cosy_service.py --port 7712

``--fake`` replaces the model with a tiny sine generator, which keeps the
protocol and the client testable without a GPU.
"""
from __future__ import annotations

import argparse
import math
import os
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Iterator

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from meta_hub.tts.protocol import ProtocolError, read_frame, write_frame  # noqa: E402


class FakeBackend:
    sample_rate = 22050

    def __init__(self, chunks: int = 4, chunk_seconds: float = 0.25,
                 delay: float = 0.05) -> None:
        self.chunks = chunks
        self.chunk_seconds = chunk_seconds
        self.delay = delay

    def stream(self, text: str, prompt_wav: str,
               prompt_text: str) -> Iterator[tuple[int, "object"]]:
        import numpy as np
        total = max(1, len(text.strip()))
        for seq in range(self.chunks):
            n = int(self.sample_rate * self.chunk_seconds)
            t = (np.arange(n, dtype=np.float32) + seq * n) / self.sample_rate
            freq = 220.0 + 10.0 * total
            data = (0.1 * np.sin(2 * math.pi * freq * t)).astype(np.float32)
            time.sleep(self.delay)
            yield self.sample_rate, data


class CosyVoiceBackend:
    def __init__(self, cosy_repo: str, model: str) -> None:
        self.cosy_repo = cosy_repo
        os.chdir(cosy_repo)
        sys.path.append("third_party/Matcha-TTS")
        sys.path.append(cosy_repo)
        from cosyvoice.cli.cosyvoice import AutoModel  # type: ignore
        self.cosy = AutoModel(model_dir=model)
        self.sample_rate = int(self.cosy.sample_rate)
        print(f"cosy_service: model loaded once from {model}", flush=True)

    def stream(self, text: str, prompt_wav: str,
               prompt_text: str) -> Iterator[tuple[int, "object"]]:
        import numpy as np
        for item in self.cosy.inference_zero_shot(
            text, prompt_text, prompt_wav, stream=True,
        ):
            audio = item["tts_speech"]
            array = audio.detach().cpu().numpy() if hasattr(audio, "detach") else audio
            array = np.asarray(array, dtype=np.float32).reshape(-1)
            yield self.sample_rate, array


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server: "SpeechServer" = self.server  # type: ignore[assignment]
        sock: socket.socket = self.request
        sock.settimeout(120.0)
        stream = sock.makefile("rwb")
        with stream:
            try:
                while True:
                    header, _ = read_frame(stream)
                    if header.get("type") != "request":
                        write_frame(stream, {"type": "error",
                                             "message": "expected request"})
                        return
                    request_id = header.get("request_id", "")
                    text = str(header.get("text", ""))
                    try:
                        with server.model_lock:
                            sent = 0
                            for sr, array in server.backend.stream(
                                text,
                                str(header.get("prompt_wav", "")),
                                str(header.get("prompt_text", "")),
                            ):
                                if sent == 0:
                                    write_frame(stream, {
                                        "type": "start", "request_id": request_id,
                                        "sample_rate": int(sr),
                                    })
                                write_frame(stream, {
                                    "type": "chunk", "request_id": request_id,
                                    "seq": sent, "sample_rate": int(sr),
                                }, array.tobytes())
                                sent += 1
                    except Exception as exc:  # report, keep serving
                        write_frame(stream, {"type": "error", "request_id": request_id,
                                             "message": f"{type(exc).__name__}: {exc}"})
                        continue
                    write_frame(stream, {"type": "done", "request_id": request_id,
                                         "chunks": sent})
            except (ProtocolError, OSError, ConnectionError):
                return


class SpeechServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], backend) -> None:
        super().__init__(address, Handler)
        self.backend = backend
        self.model_lock = threading.Lock()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7712)
    ap.add_argument("--model", default="pretrained_models/CosyVoice2-0.5B")
    ap.add_argument("--cosy-repo", default=os.environ.get(
        "META_HUB_COSY_REPO", "/home/hebl/project/dh-services/CosyVoice"))
    ap.add_argument("--fake", action="store_true", help="use a sine backend")
    args = ap.parse_args(argv)

    backend = FakeBackend() if args.fake else CosyVoiceBackend(args.cosy_repo, args.model)
    server = SpeechServer((args.host, args.port), backend)
    print(f"cosy_service: listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
