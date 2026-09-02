"""Zenoh wire codec for `SensorEnvelope`.

Format:
    [4-byte big-endian header length][msgpack header dict][payload bytes]
"""

from __future__ import annotations

import struct
from dataclasses import asdict

import msgpack

from src.contracts.envelope import SensorEnvelope
from src.contracts.types import SensorType

_HDR_FMT = ">I"
_HDR_SIZE = 4


def encode_zenoh(env: SensorEnvelope) -> bytes:
    """Encode envelope into compact Zenoh transport frame."""
    d = asdict(env)
    d.pop("payload", None)
    d["sensor_type"] = env.sensor_type.value
    header = msgpack.packb(d, use_bin_type=True)
    return struct.pack(_HDR_FMT, len(header)) + header + env.payload


def decode_zenoh(data: bytes) -> SensorEnvelope:
    """Decode Zenoh transport frame into canonical `SensorEnvelope`."""
    header_len = struct.unpack(_HDR_FMT, data[:_HDR_SIZE])[0]
    offset = _HDR_SIZE + header_len
    d = msgpack.unpackb(data[_HDR_SIZE:offset], raw=False)
    payload = data[offset:]
    return SensorEnvelope(
        schema_version=int(d["schema_version"]),
        sensor_type=SensorType(d["sensor_type"]),
        stream_id=str(d["stream_id"]),
        session_id=str(d["session_id"]),
        seq=int(d["seq"]),
        ts_unix_ns=int(d["ts_unix_ns"]),
        ts_mono_ns=int(d["ts_mono_ns"]),
        source_timestamp=int(d.get("source_timestamp", 0)),
        frame_stamp=int(d.get("frame_stamp", 0)),
        content_type=str(d.get("content_type", "application/octet-stream")),
        flags=int(d.get("flags", 0)),
        metadata=d.get("metadata", {}),
        calibration=d.get("calibration", {}),
        payload=payload,
    )
