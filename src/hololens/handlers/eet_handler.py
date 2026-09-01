"""Extended eye-tracking stream handler."""

from __future__ import annotations

from typing import Any

from src.contracts.types import SensorType
from src.hololens.handlers.base import HandlerStreamSpec, HololensHandler
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm
from src.hololens.packet_contract import parse_eet_metadata


class EETHandler(HololensHandler):
    """Handler for `hl2ss.StreamPort.EXTENDED_EYE_TRACKER`."""

    def __init__(
        self,
        *,
        user_id: str,
        port_name: str,
        publish_topic: str,
        fps: int,
        decoded: bool,
    ):
        super().__init__(
            HandlerStreamSpec(
                stream_id=f"eet_{user_id}",
                sensor_type=SensorType.EET,
                port_name=port_name,
                publish_topic=publish_topic,
            )
        )
        self.fps = fps
        self.decoded = decoded

    def configure_receiver(self, host: str):
        """Configure extended eye-tracker receiver."""
        port = int(getattr(hl2ss.StreamPort, self.spec.port_name))
        return hl2ss_lnm.rx_eet(host, port, fps=self.fps, decoded=False)

    def packet_metadata(self, frame: Any) -> dict[str, Any]:
        out = super().packet_metadata(frame)
        payload = getattr(frame, "payload", None)
        if isinstance(payload, (bytes, bytearray, memoryview)):
            out.update(parse_eet_metadata(bytes(payload)))
        return out
