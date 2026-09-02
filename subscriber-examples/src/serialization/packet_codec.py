"""
Lightweight packet codec for hl2ss sensor streams.

Wire format:
    [4 bytes BE: header_len] [msgpack header dict] [raw payload bytes]

The header is the publisher's msgpack-encoded ``SensorEnvelope`` metadata.
The payload is either:
- legacy raw sensor bytes (encoded video, depth, audio, etc.), or
- `hl2ss.pack_packet(...)` bytes when `content_type=application/x-hl2ss.packet`.

Common header keys
------------------
schema_version  : int   envelope schema identifier
sensor_type     : str   canonical sensor type
stream_id       : str   stream/device instance
session_id      : str   acquisition session identifier
seq             : int   per-stream sequence number
ts_unix_ns      : int   publisher wall-clock timestamp
ts_mono_ns      : int   publisher monotonic timestamp
source_timestamp: int   source timing when available
frame_stamp     : int   source frame counter when available
content_type    : str   payload representation
flags           : int   status flags
metadata        : dict  per-sample metadata
calibration     : dict  optional stream calibration

Per-sensor extra keys are documented in each handler.
"""

from __future__ import annotations

import struct
from typing import Optional

import msgpack
import numpy as np

_HDR_FMT  = '>I'   # unsigned 32-bit big-endian  (4 bytes)
_HDR_SIZE = 4


# ---------------------------------------------------------------------------
# Core encode / decode
# ---------------------------------------------------------------------------

def encode(metadata: dict, payload: bytes) -> bytes:
    """Pack (metadata, payload) into the wire format."""
    header = msgpack.packb(metadata, use_bin_type=True)
    return struct.pack(_HDR_FMT, len(header)) + header + (
        payload if isinstance(payload, (bytes, bytearray)) else bytes(payload)
    )


def decode(data: bytes) -> tuple[dict, bytes]:
    """Unpack wire bytes into (metadata dict, raw payload bytes)."""
    header_len = struct.unpack(_HDR_FMT, data[:_HDR_SIZE])[0]
    offset = _HDR_SIZE + header_len
    metadata = msgpack.unpackb(data[_HDR_SIZE:offset], raw=False)
    return metadata, data[offset:]


# ---------------------------------------------------------------------------
# Small helpers used by both publisher handlers and (future) subscribers
# ---------------------------------------------------------------------------

def pose_to_list(pose) -> Optional[list]:
    """Convert a 4×4 numpy pose matrix to a flat list of 16 floats for msgpack."""
    if pose is None:
        return None
    try:
        return pose.flatten().tolist()
    except Exception:
        return None


def list_to_pose(lst) -> Optional[np.ndarray]:
    """Reconstruct a (4, 4) float32 numpy array from a 16-element list."""
    if lst is None:
        return None
    return np.array(lst, dtype=np.float32).reshape(4, 4)


def ndarray_to_meta(arr: np.ndarray, key_prefix: str) -> dict:
    """
    Return a dict with raw bytes + shape + dtype for a numpy array.
    Keys:  <key_prefix>       -> bytes
           <key_prefix>_shape -> list[int]
           <key_prefix>_dtype -> str
    """
    return {
        key_prefix:              arr.tobytes(),
        key_prefix + "_shape":   list(arr.shape),
        key_prefix + "_dtype":   str(arr.dtype),
    }


def meta_to_ndarray(meta: dict, key_prefix: str) -> Optional[np.ndarray]:
    """Reconstruct a numpy array from the keys written by ndarray_to_meta."""
    raw   = meta.get(key_prefix)
    shape = meta.get(key_prefix + "_shape")
    dtype = meta.get(key_prefix + "_dtype")
    if raw is None or shape is None or dtype is None:
        return None
    return np.frombuffer(raw, dtype=np.dtype(dtype)).reshape(shape)
