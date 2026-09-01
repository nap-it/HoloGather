"""IMU stream handler for one IMU source type."""

from __future__ import annotations

from typing import Any

from src.contracts.types import SensorType
from src.hololens.handlers.base import HandlerStreamSpec, HololensHandler
from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm
from src.hololens.packet_contract import fetch_calibration, parse_imu_metadata


class IMUHandler(HololensHandler):
    """Handler for one IMU stream (accelerometer/gyroscope/magnetometer)."""

    def __init__(
        self,
        *,
        user_id: str,
        imu_label: str,
        port_name: str,
        publish_topic: str,
        mode_name: str,
        decoded: bool,
    ):
        super().__init__(
            HandlerStreamSpec(
                stream_id=f"imu_{imu_label}_{user_id}",
                sensor_type=SensorType.IMU,
                port_name=port_name,
                publish_topic=publish_topic,
            )
        )
        self.mode_name = mode_name
        self.decoded = decoded

    def configure_receiver(self, host: str):
        """Configure IMU receiver with configured stream mode."""
        port = int(getattr(hl2ss.StreamPort, self.spec.port_name))
        mode = getattr(hl2ss.StreamMode, self.mode_name)
        return hl2ss_lnm.rx_rm_imu(host, port, mode=mode, decoded=False)

    def packet_metadata(self, frame: Any) -> dict[str, Any]:
        out = super().packet_metadata(frame)
        payload = getattr(frame, "payload", None)
        if isinstance(payload, (bytes, bytearray, memoryview)):
            out.update(parse_imu_metadata(bytes(payload)))
        return out

    def calibration(self, host: str) -> dict[str, Any]:
        return fetch_calibration(host, port_name=self.spec.port_name)
