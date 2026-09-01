"""Helpers for extracting raw sensor payload from full hl2ss packet envelopes."""

from __future__ import annotations

from typing import Any

from src.hl2ss_imports import hl2ss


def unwrap_sensor_payload(envelope: dict[str, Any], payload: bytes) -> tuple[bytes, dict[str, Any]]:
    """Return sensor payload bytes and packet context metadata.

    New publisher contract sends `content_type=application/x-hl2ss.packet` where
    payload is `hl2ss.pack_packet(packet)` bytes.
    """
    if envelope.get("content_type") != "application/x-hl2ss.packet":
        return payload, {}
    packet = hl2ss.unpack_packet(payload)
    out = {
        "packet_timestamp": int(getattr(packet, "timestamp", 0)),
        "packet_has_pose": bool(getattr(packet, "pose", None) is not None),
        "packet_pose": getattr(packet, "pose", None),
    }
    raw = getattr(packet, "payload", b"")
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw), out
    return b"", out
