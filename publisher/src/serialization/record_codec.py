"""Append-only record codec for local stream files.

Record format:
    [4-byte magic][4-byte header len][4-byte payload len][msgpack header][payload]
"""

from __future__ import annotations

import struct
from dataclasses import asdict
from typing import BinaryIO

import msgpack

from src.contracts.envelope import SensorEnvelope
from src.contracts.types import SensorType

MAGIC = b"HLP2"
PRELUDE_FMT = ">4sII"
PRELUDE_SIZE = struct.calcsize(PRELUDE_FMT)


def encode_record(env: SensorEnvelope) -> bytes:
    """Encode one envelope to binary record bytes."""
    d = asdict(env)
    payload = d.pop("payload")
    d["sensor_type"] = env.sensor_type.value
    header = msgpack.packb(d, use_bin_type=True)
    prelude = struct.pack(PRELUDE_FMT, MAGIC, len(header), len(payload))
    return prelude + header + payload


def decode_record(blob: bytes) -> SensorEnvelope:
    """Decode one binary record blob into `SensorEnvelope`."""
    magic, header_len, payload_len = struct.unpack(PRELUDE_FMT, blob[:PRELUDE_SIZE])
    if magic != MAGIC:
        raise ValueError("invalid record magic")
    header_start = PRELUDE_SIZE
    header_end = header_start + header_len
    payload_end = header_end + payload_len
    d = msgpack.unpackb(blob[header_start:header_end], raw=False)
    payload = blob[header_end:payload_end]
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


def read_record(fh: BinaryIO) -> SensorEnvelope | None:
    """Read and decode one record from binary file handle."""
    prelude = fh.read(PRELUDE_SIZE)
    if not prelude or len(prelude) < PRELUDE_SIZE:
        return None
    magic, header_len, payload_len = struct.unpack(PRELUDE_FMT, prelude)
    if magic != MAGIC:
        raise ValueError("invalid record magic")
    header = fh.read(header_len)
    payload = fh.read(payload_len)
    return decode_record(prelude + header + payload)
