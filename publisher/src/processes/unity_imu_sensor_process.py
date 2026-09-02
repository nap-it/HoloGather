"""MQTT Unity IMU (orientation) sensor process."""

from __future__ import annotations

from src.config.center import AppConfig
from src.contracts.types import SensorType
from src.mqtt.unity_imu_parser import parse_unity_imu
from src.processes.mqtt_sensor_base_process import MqttSensorBaseProcess
from src.runtime.buses import RuntimeBuses


class UnityImuSensorProcess(MqttSensorBaseProcess):
    """Consumes Unity orientation topic and emits yaw/pitch/roll payloads."""

    sensor_type = SensorType.HEADING

    def __init__(self, cfg: AppConfig, buses: RuntimeBuses):
        super().__init__("UnityImuSensorProcess", cfg, buses)
        self.topic = cfg.mqtt.orientation_topic
        self.stream_id = f"unity_imu_{cfg.hololens.user_id}"
        self.publish_topic = "Hololens/UnityIMU"

    def parse_message(self, payload: bytes) -> dict | None:
        """Delegate parsing to unity orientation parser."""
        return parse_unity_imu(payload)
