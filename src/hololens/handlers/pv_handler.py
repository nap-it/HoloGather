"""Personal Video stream handler.

This module contains all PV-specific behavior so `sink_manager` stays generic:
- PV subsystem start/stop
- PV receiver configuration
- PV payload extraction
"""

from __future__ import annotations

import threading
from typing import Any

from src.contracts.types import SensorType
from src.hololens.handlers.base import HandlerStreamSpec, HololensHandler
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm
from src.hololens.packet_contract import fetch_calibration, parse_pv_metadata


class PVHandler(HololensHandler):
    """Handler for `hl2ss.StreamPort.PERSONAL_VIDEO`."""

    def __init__(
        self,
        *,
        user_id: str,
        port_name: str,
        publish_topic: str,
        width: int,
        height: int,
        framerate: int,
        divisor: int,
        profile_name: str,
        gop_size: int,
        enable_mrc: bool = False,
        shared: bool = False,
    ):
        super().__init__(
            HandlerStreamSpec(
                stream_id=f"pv_{user_id}",
                sensor_type=SensorType.PV,
                port_name=port_name,
                publish_topic=publish_topic,
            )
        )
        self.width = width
        self.height = height
        self.framerate = framerate
        self.divisor = divisor
        self.profile_name = profile_name
        self.gop_size = gop_size
        self.enable_mrc = enable_mrc
        self.shared = shared

    def start_subsystem(self, host: str, timeout_s: float) -> None:
        """Start PV subsystem before attaching PV receiver."""
        pv_port = int(getattr(hl2ss.StreamPort, self.spec.port_name))

        def worker() -> None:
            hl2ss_lnm.start_subsystem_pv(
                host,
                pv_port,
                enable_mrc=self.enable_mrc,
                shared=self.shared,
            )

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=timeout_s)

    def stop_subsystem(self, host: str, timeout_s: float) -> None:
        """Stop PV subsystem during stream teardown."""
        pv_port = int(getattr(hl2ss.StreamPort, self.spec.port_name))

        def worker() -> None:
            hl2ss_lnm.stop_subsystem_pv(host, pv_port)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=timeout_s)

    def configure_receiver(self, host: str):
        """Configure PV receiver using handler-owned camera settings."""
        port = int(getattr(hl2ss.StreamPort, self.spec.port_name))
        profile = getattr(hl2ss.VideoProfile, self.profile_name)
        return hl2ss_lnm.rx_pv(
            host,
            port,
            width=self.width,
            height=self.height,
            framerate=self.framerate,
            divisor=self.divisor,
            profile=profile,
            options={hl2ss.H26xEncoderProperty.CODECAPI_AVEncMPVGOPSize: self.gop_size},
            decoded_format=None,
        )

    def packet_metadata(self, frame: Any) -> dict[str, Any]:
        out = super().packet_metadata(frame)
        payload = getattr(frame, "payload", None)
        if isinstance(payload, (bytes, bytearray, memoryview)):
            out.update(parse_pv_metadata(bytes(payload)))
        return out

    def calibration(self, host: str) -> dict[str, Any]:
        return fetch_calibration(
            host,
            port_name=self.spec.port_name,
            pv_width=self.width,
            pv_height=self.height,
            pv_framerate=self.framerate,
        )
