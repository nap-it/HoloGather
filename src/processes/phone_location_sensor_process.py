"""MQTT phone location sensor process (OwnTracks)."""

from __future__ import annotations

from src.config.center import AppConfig
from src.contracts.types import SensorType
from src.mqtt.phone_location_parser import parse_phone_location
from src.processes.mqtt_sensor_base_process import MqttSensorBaseProcess
from src.runtime.buses import RuntimeBuses


class PhoneLocationSensorProcess(MqttSensorBaseProcess):
    """Consumes OwnTracks phone topic and emits `SensorType.PHONE_LOCATION` events."""

    sensor_type = SensorType.PHONE_LOCATION

    def __init__(self, cfg: AppConfig, buses: RuntimeBuses):
        super().__init__("PhoneLocationSensorProcess", cfg, buses)
        self.topic = cfg.mqtt.phone_location_topic_owntrack
        self.stream_id = f"phone_location_{cfg.hololens.user_id}"
        self.publish_topic = "Hololens/PhoneLocation"

    def parse_message(self, payload: bytes) -> dict | None:
        return parse_phone_location(payload)
