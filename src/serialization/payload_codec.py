"""Generic payload encoding helpers."""

from __future__ import annotations

import msgpack


def encode_payload(payload: object) -> bytes:
    """Encode arbitrary Python object into msgpack bytes."""
    if isinstance(payload, bytes):
        return payload
    return msgpack.packb(payload, use_bin_type=True)


def decode_payload(payload: bytes) -> object:
    """Decode msgpack payload, fallback to raw bytes on parse failure."""
    try:
        return msgpack.unpackb(payload, raw=False)
    except Exception:
        return payload
