"""Spatial input stream handler."""

from __future__ import annotations

from typing import Any

from src.contracts.types import SensorType
from src.hololens.handlers.base import HandlerStreamSpec, HololensHandler
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm
from src.hololens.packet_contract import parse_si_metadata


class SpatialInputHandler(HololensHandler):
    """Handler for `hl2ss.StreamPort.SPATIAL_INPUT`."""

    def __init__(
        self,
        *,
        user_id: str,
        port_name: str,
        publish_topic: str,
        decoded: bool,
    ):
        super().__init__(
            HandlerStreamSpec(
                stream_id=f"spatial_input_{user_id}",
                sensor_type=SensorType.SPATIAL_INPUT,
                port_name=port_name,
                publish_topic=publish_topic,
            )
        )
        self.decoded = decoded

    def configure_receiver(self, host: str):
        """Configure spatial input receiver."""
        port = int(getattr(hl2ss.StreamPort, self.spec.port_name))
        return hl2ss_lnm.rx_si(host, port, decoded=False)

    def packet_metadata(self, frame: Any) -> dict[str, Any]:
        out = super().packet_metadata(frame)
        payload = getattr(frame, "payload", None)
        if isinstance(payload, (bytes, bytearray, memoryview)):
            out.update(parse_si_metadata(bytes(payload)))
        return out
