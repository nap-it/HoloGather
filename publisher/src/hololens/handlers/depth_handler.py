"""Depth stream handler.

All depth-specific receiver and payload logic lives here, including long-throw
vs AHAT receiver selection. This keeps `sink_manager` and processes generic.
"""

from __future__ import annotations

from typing import Any

from src.contracts.types import SensorType
from src.hololens.handlers.base import HandlerStreamSpec, HololensHandler
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm
from src.hololens.packet_contract import fetch_calibration, parse_depth_metadata


class DepthHandler(HololensHandler):
    """Handler for depth camera streams (long throw or AHAT)."""

    def __init__(self, *, user_id: str, depth_sensor_name: str, publish_topic: str):
        super().__init__(
            HandlerStreamSpec(
                stream_id=f"depth_{user_id}",
                sensor_type=SensorType.DEPTH,
                port_name=depth_sensor_name,
                publish_topic=publish_topic,
            )
        )

    def configure_receiver(self, host: str):
        """Create the matching depth receiver for configured depth port."""
        port = int(getattr(hl2ss.StreamPort, self.spec.port_name))
        if port == int(hl2ss.StreamPort.RM_DEPTH_LONGTHROW):
            return hl2ss_lnm.rx_rm_depth_longthrow(host, port, decoded=False)
        return hl2ss_lnm.rx_rm_depth_ahat(host, port, decoded=False)

    def packet_metadata(self, frame: Any) -> dict[str, Any]:
        out = super().packet_metadata(frame)
        payload = getattr(frame, "payload", None)
        if isinstance(payload, (bytes, bytearray, memoryview)):
            out.update(parse_depth_metadata(bytes(payload)))
        return out

    def calibration(self, host: str) -> dict[str, Any]:
        return fetch_calibration(host, port_name=self.spec.port_name)
