"""MQTT heading sensor process."""

from __future__ import annotations

from src.config.center import AppConfig
from src.contracts.types import SensorType
from src.mqtt.unity_heading_parser import parse_heading
from src.processes.mqtt_sensor_base_process import MqttSensorBaseProcess
from src.runtime.buses import RuntimeBuses


class UnityHeadingSensorProcess(MqttSensorBaseProcess):
    """Consumes heading MQTT topic and emits `SensorType.HEADING` events."""

    sensor_type = SensorType.HEADING

    def __init__(self, cfg: AppConfig, buses: RuntimeBuses):
        super().__init__("UnityHeadingSensorProcess", cfg, buses)
        self.topic = cfg.mqtt.heading_topic
        self.stream_id = f"unity_heading_{cfg.hololens.user_id}"
        self.publish_topic = "Hololens/Heading"

    def parse_message(self, payload: bytes) -> dict | None:
        """Delegate parsing to heading-specific parser."""
        return parse_heading(payload)
