"""Microphone stream handler."""

from __future__ import annotations

from src.contracts.types import SensorType
from src.hololens.handlers.base import HandlerStreamSpec, HololensHandler
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm


class MicrophoneHandler(HololensHandler):
    """Handler for `hl2ss.StreamPort.MICROPHONE`."""

    def __init__(
        self,
        *,
        user_id: str,
        port_name: str,
        publish_topic: str,
        profile_name: str,
        chunk_name: str,
        level_name: str,
        decoded: bool,
    ):
        super().__init__(
            HandlerStreamSpec(
                stream_id=f"microphone_{user_id}",
                sensor_type=SensorType.MICROPHONE,
                port_name=port_name,
                publish_topic=publish_topic,
            )
        )
        self.profile_name = profile_name
        self.chunk_name = chunk_name
        self.level_name = level_name
        self.decoded = decoded

    def configure_receiver(self, host: str):
        """Configure microphone receiver from typed config options."""
        port = int(getattr(hl2ss.StreamPort, self.spec.port_name))
        profile = getattr(hl2ss.AudioProfile, self.profile_name)
        chunk = getattr(hl2ss.ChunkSize, self.chunk_name)
        level = getattr(hl2ss.AACLevel, self.level_name)
        return hl2ss_lnm.rx_microphone(
            host,
            port,
            chunk=chunk,
            profile=profile,
            level=level,
            decoded=False,
        )
