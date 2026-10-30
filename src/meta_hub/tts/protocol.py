"""Length-prefixed frame protocol for the resident speech service (task 1.1-1.3).

Frame layout::

    [4 bytes big-endian header length][UTF-8 JSON header][payload bytes]

The header always carries ``type`` and ``payload_len``; audio chunks carry
raw float32 samples in the payload.  The protocol is tiny on purpose: both
sides only need the standard library.
"""
from __future__ import annotations

import json
import struct
from typing import Any, BinaryIO

_LEN = struct.Struct(">I")
MAX_HEADER = 1 << 20
MAX_PAYLOAD = 64 << 20


class ProtocolError(RuntimeError):
    pass


def read_exact(stream: BinaryIO, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise ProtocolError("connection closed while reading frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def encode_frame(header: dict[str, Any], payload: bytes = b"") -> bytes:
    header = dict(header)
    header["payload_len"] = len(payload)
    raw = json.dumps(header, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_HEADER:
        raise ProtocolError("header too large")
    return _LEN.pack(len(raw)) + raw + payload


def write_frame(stream: BinaryIO, header: dict[str, Any],
                payload: bytes = b"") -> None:
    stream.write(encode_frame(header, payload))
    stream.flush()


def read_frame(stream: BinaryIO) -> tuple[dict[str, Any], bytes]:
    raw_len = read_exact(stream, _LEN.size)
    (header_len,) = _LEN.unpack(raw_len)
    if header_len > MAX_HEADER:
        raise ProtocolError("header too large")
    header = json.loads(read_exact(stream, header_len).decode("utf-8"))
    payload_len = int(header.get("payload_len", 0))
    if payload_len < 0 or payload_len > MAX_PAYLOAD:
        raise ProtocolError("payload too large")
    payload = read_exact(stream, payload_len) if payload_len else b""
    return header, payload


def request_header(text: str, *, prompt_wav: str, prompt_text: str,
                   request_id: str = "") -> dict[str, Any]:
    return {
        "type": "request",
        "request_id": request_id,
        "text": text,
        "prompt_wav": prompt_wav,
        "prompt_text": prompt_text,
    }
