"""VLC stream handler for one VLC camera stream."""

from __future__ import annotations

from typing import Any

from src.contracts.types import SensorType
from src.hololens.handlers.base import HandlerStreamSpec, HololensHandler
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm
from src.hololens.packet_contract import fetch_calibration, parse_vlc_metadata


class VLCHandler(HololensHandler):
    """Handler for one RM VLC camera stream."""

    def __init__(
        self,
        *,
        user_id: str,
        camera_name: str,
        port_name: str,
        publish_topic: str,
        profile_name: str,
        divisor: int,
        gop_size: int,
        decoded: bool,
    ):
        super().__init__(
            HandlerStreamSpec(
                stream_id=f"vlc_{camera_name}_{user_id}",
                sensor_type=SensorType.VLC,
                port_name=port_name,
                publish_topic=publish_topic,
            )
        )
        self.profile_name = profile_name
        self.divisor = divisor
        self.gop_size = gop_size
        self.decoded = decoded

    def configure_receiver(self, host: str):
        """Configure VLC receiver with codec settings from config center."""
        port = int(getattr(hl2ss.StreamPort, self.spec.port_name))
        profile = getattr(hl2ss.VideoProfile, self.profile_name)
        options = {hl2ss.H26xEncoderProperty.CODECAPI_AVEncMPVGOPSize: self.gop_size}
        return hl2ss_lnm.rx_rm_vlc(
            host,
            port,
            divisor=self.divisor,
            profile=profile,
            options=options,
            decoded=False,
        )

    def packet_metadata(self, frame: Any) -> dict[str, Any]:
        out = super().packet_metadata(frame)
        payload = getattr(frame, "payload", None)
        if isinstance(payload, (bytes, bytearray, memoryview)):
            out.update(parse_vlc_metadata(bytes(payload)))
        return out

    def calibration(self, host: str) -> dict[str, Any]:
        return fetch_calibration(host, port_name=self.spec.port_name)
