"""Unity IMU (orientation) subscriber."""

from __future__ import annotations

import configparser
import signal
import time

import msgpack  # type: ignore

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.serialization.packet_codec import decode
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.zenoh_utils.sensor_zenoh_reader import SensorPacket, SensorZenohReader


class UnityImuSubscriber(BaseSubscriberProcess):
    """Subscribes to Zenoh Unity IMU data and prints yaw/pitch/roll."""

    def __init__(self, config_file: str):
        super().__init__("UnityImuSubscriber")
        self.config_file = config_file

        config = configparser.ConfigParser()
        config.read(self.config_file)

        section = "UNITY_IMU"
        self.topic = config.get(section, "topic", fallback="Hololens/UnityIMU")
        self.max_size = config.getint(section, "sensor_queue_size", fallback=25)

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=self.max_size)
        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )

    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.logger.info("Starting Unity IMU subscription on topic: %s", self.topic)
        self._sensor_subscriber.run()

        while not self._stop_event.is_set():
            self._flush_rolling_metrics()
            if self.buffer.is_empty():
                time.sleep(0.001)
                continue

            packet = self.buffer.get()
            if packet is None:
                continue
            self._emit_packet_airtime_ms(packet)
            t0 = time.perf_counter()

            try:
                _metadata, payload = decode(packet.message)
                data = msgpack.unpackb(payload, raw=False)
            except Exception as exc:
                self.logger.warning("Failed to decode Unity IMU packet: %s", exc)
                continue
            finally:
                self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)

            yaw = data.get("yaw")
            pitch = data.get("pitch")
            roll = data.get("roll")
            if yaw is None or pitch is None or roll is None:
                self.logger.warning("Unity IMU payload missing required fields: %s", data)
                continue
            self.logger.info("UnityIMU yaw=%.2f pitch=%.2f roll=%.2f", float(yaw), float(pitch), float(roll))

    def _request_stop(self):
        self.logger.info("Requesting Unity IMU subscriber stop...")
        self._stop_event.set()
        self.buffer.put(None)

    def _subscriber_cleanup(self):
        self.logger.info("Cleaning up Unity IMU subscriber...")
        try:
            self._sensor_subscriber.stop()
        except Exception as exc:
            self.logger.debug("Error stopping sensor subscriber: %s", exc)
        self.logger.info("Cleanup complete.")
