"""Canonical payload contract for cross-module sensor events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.contracts.types import SensorType


@dataclass(frozen=True)
class SensorEnvelope:
    """Serializable envelope containing metadata and opaque payload bytes."""

    schema_version: int
    sensor_type: SensorType
    stream_id: str
    session_id: str
    seq: int
    ts_unix_ns: int
    ts_mono_ns: int
    source_timestamp: int = 0
    frame_stamp: int = 0
    content_type: str = "application/octet-stream"
    flags: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    calibration: Mapping[str, Any] = field(default_factory=dict)
    payload: bytes = b""
