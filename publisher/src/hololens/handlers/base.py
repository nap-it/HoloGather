"""Base contracts for sensor-specific HoloLens handlers.

Handlers are lightweight strategy objects owned by `HololensStreamerProcess`.
They are *not* processes or threads. Their only role is to isolate stream-
specific knowledge (receiver setup, optional subsystem lifecycle hooks, payload
conversion, and source timestamp extraction).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.contracts.types import SensorType
from src.hololens.packet_contract import HL2SS_PACKET_CONTENT_TYPE, base_packet_metadata, pack_frame


@dataclass(frozen=True)
class HandlerStreamSpec:
    """Static metadata for one logical stream.

    Attributes:
        stream_id: Stable stream identifier used in envelopes and file names.
        sensor_type: Canonical sensor type used in contracts.
        port_name: Name of `hl2ss.StreamPort` enum member.
        publish_topic: Zenoh topic for this stream, when publishing is enabled.
    """

    stream_id: str
    sensor_type: SensorType
    port_name: str
    publish_topic: str


class HololensHandler(ABC):
    """Abstract interface implemented by each HoloLens sensor handler."""

    def __init__(self, spec: HandlerStreamSpec):
        self.spec = spec

    def start_subsystem(self, host: str, timeout_s: float) -> None:
        """Optional pre-start hook (e.g., PV subsystem startup)."""
        return None

    def stop_subsystem(self, host: str, timeout_s: float) -> None:
        """Optional shutdown hook for sensor-specific subsystem teardown."""
        return None

    @abstractmethod
    def configure_receiver(self, host: str):
        """Build and return the `hl2ss_lnm.rx_*` receiver for this stream."""
        raise NotImplementedError

    def to_payload(self, frame: Any) -> bytes:
        """Convert an hl2ss frame object into packet payload bytes."""
        return pack_frame(frame)

    def packet_metadata(self, frame: Any) -> dict[str, Any]:
        """Extract packet-level metadata to ship alongside payload."""
        return base_packet_metadata(frame, port_name=self.spec.port_name)

    def calibration(self, host: str) -> dict[str, Any]:
        """Fetch static calibration data for this stream, when available."""
        return {}

    def content_type(self) -> str:
        """Envelope content-type for this handler payload."""
        return HL2SS_PACKET_CONTENT_TYPE

    def source_timestamp(self, frame: Any, fallback: int) -> int:
        """Extract source timestamp from frame, fallback to provided value."""
        return int(getattr(frame, "timestamp", fallback))
