"""Minimal MQTT client adapter around paho-mqtt."""

from __future__ import annotations


class MqttClientService:
    """Small wrapper that encapsulates MQTT connect/subscribe/stop lifecycle."""

    def __init__(self, host: str, port: int, username: str = "", password: str = ""):
        try:
            import paho.mqtt.client as mqtt  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "paho-mqtt is required for MQTT sensor processes; install dependencies from requirements.txt"
            ) from exc

        self.client = mqtt.Client()
        if username and password:
            self.client.username_pw_set(username, password)
        self.host = host
        self.port = port

    def connect(self) -> None:
        """Connect to broker and start paho network loop thread."""
        self.client.connect(self.host, self.port)
        self.client.loop_start()

    def subscribe(self, topic: str, callback):
        """Register callback and subscribe to one topic."""
        self.client.message_callback_add(topic, callback)
        self.client.subscribe(topic)

    def stop(self) -> None:
        """Stop paho loop and disconnect gracefully."""
        self.client.loop_stop()
        self.client.disconnect()
