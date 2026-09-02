"""Unity heading subscriber."""

from __future__ import annotations

import configparser
import signal
import time

import msgpack  # type: ignore

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.serialization.packet_codec import decode
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.zenoh_utils.sensor_zenoh_reader import SensorPacket, SensorZenohReader


class HeadingSubscriber(BaseSubscriberProcess):
    """Subscribes to Zenoh heading data and prints decoded value."""

    def __init__(self, config_file: str):
        super().__init__("HeadingSubscriber")
        self.config_file = config_file

        config = configparser.ConfigParser()
        config.read(self.config_file)

        section = "HEADING"
        self.topic = config.get(section, "topic", fallback="Hololens/Heading")
        self.max_size = config.getint(section, "sensor_queue_size", fallback=25)

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=self.max_size)
        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )

    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.logger.info("Starting heading subscription on topic: %s", self.topic)
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
                self.logger.warning("Failed to decode heading packet: %s", exc)
                continue
            finally:
                self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)

            heading = data.get("heading")
            if heading is None:
                self.logger.warning("Heading payload missing 'heading' field: %s", data)
                continue
            self.logger.info("Heading=%.2f", float(heading))

    def _request_stop(self):
        self.logger.info("Requesting heading subscriber stop...")
        self._stop_event.set()
        self.buffer.put(None)

    def _subscriber_cleanup(self):
        self.logger.info("Cleaning up heading subscriber...")
        try:
            self._sensor_subscriber.stop()
        except Exception as exc:
            self.logger.debug("Error stopping sensor subscriber: %s", exc)
        self.logger.info("Cleanup complete.")
