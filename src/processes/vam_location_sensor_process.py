"""MQTT VAM location sensor process."""

from __future__ import annotations

from src.config.center import AppConfig
from src.contracts.types import SensorType
from src.mqtt.vam_location_parser import parse_vam_location
from src.processes.mqtt_sensor_base_process import MqttSensorBaseProcess
from src.runtime.buses import RuntimeBuses


class VamLocationSensorProcess(MqttSensorBaseProcess):
    """Consumes VAM location MQTT topic and emits `SensorType.VAM_LOCATION` events."""

    sensor_type = SensorType.VAM_LOCATION

    def __init__(self, cfg: AppConfig, buses: RuntimeBuses):
        super().__init__("VamLocationSensorProcess", cfg, buses)
        self.topic = cfg.mqtt.vam_location_topic
        self.stream_id = f"vam_location_{cfg.hololens.user_id}"
        self.publish_topic = "Hololens/VamLocation"

    def parse_message(self, payload: bytes) -> dict | None:
        return parse_vam_location(payload)
