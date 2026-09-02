from __future__ import annotations

import configparser
import signal
import time

from src.hl2ss_imports import hl2ss
from src.handlers.base_subscriber import BaseSubscriberProcess
from src.zenoh_utils.sensor_zenoh_reader import SensorZenohReader, SensorPacket
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.serialization.packet_codec import decode
from src.serialization.hl2ss_packet import unwrap_sensor_payload


class EETSubscriber(BaseSubscriberProcess):
    """
    Subscriber for Eye/Gaze Tracking packets with full hl2ss packet payloads.
    """

    def __init__(self, config_file: str):
        super().__init__("EETSubscriber")
        self.config_file = config_file

        config = configparser.ConfigParser()
        config.read(self.config_file)

        section = "EET"
        self.topic = config.get(section, "topic", fallback="Hololens/EET")
        self.max_size = config.getint(section, "sensor_queue_size", fallback=25)

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=self.max_size)

        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )
        self._eet_decoder = hl2ss.decode_eet()

    # ------------------------------------------------------------------
    def _log_frame(self, metadata: dict, eet_frame, packet_info: dict) -> None:
        ts = metadata.get("ts_unix_ns", 0)
        self.logger.info(f"Tracking status at time {ts}")

        pose = packet_info.get("packet_pose")
        if pose is not None and hl2ss.is_valid_pose(pose):
            self.logger.info("Pose\n%s", pose)
        else:
            self.logger.info("Pose unavailable")

        self.logger.info("Calibration valid=%s", bool(eet_frame.calibration_valid))
        self.logger.info(
            "Combined eye gaze: Valid=%s Ray=%s",
            bool(eet_frame.combined_ray_valid),
            {
                "origin": eet_frame.combined_ray.origin.tolist(),
                "direction": eet_frame.combined_ray.direction.tolist(),
            },
        )
        self.logger.info(
            "Left eye gaze: Valid=%s Ray=%s",
            bool(eet_frame.left_ray_valid),
            {"origin": eet_frame.left_ray.origin.tolist(), "direction": eet_frame.left_ray.direction.tolist()},
        )
        self.logger.info(
            "Right eye gaze: Valid=%s Ray=%s",
            bool(eet_frame.right_ray_valid),
            {
                "origin": eet_frame.right_ray.origin.tolist(),
                "direction": eet_frame.right_ray.direction.tolist(),
            },
        )
        self.logger.info(
            "Left eye openness: Valid=%s Value=%s",
            bool(eet_frame.left_openness_valid),
            float(eet_frame.left_openness),
        )
        self.logger.info(
            "Right eye openness: Valid=%s Value=%s",
            bool(eet_frame.right_openness_valid),
            float(eet_frame.right_openness),
        )
        self.logger.info(
            "Vergence distance: Valid=%s Value=%s",
            bool(eet_frame.vergence_distance_valid),
            float(eet_frame.vergence_distance),
        )
        self.logger.info("-" * 60)

    # ------------------------------------------------------------------
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.logger.info(f"Starting EET subscription to topic: {self.topic}")
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
                metadata, payload = decode(packet.message)
                payload, packet_info = unwrap_sensor_payload(metadata, payload)
                if not payload:
                    continue
                eet_frame = self._eet_decoder.decode(payload)
            except Exception as e:
                self.logger.warning(f"Failed to decode EET packet: {e}")
                continue

            self._log_frame(metadata, eet_frame, packet_info)
            self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)

        self.logger.info("Stop event received in EET subscriber loop.")

    # ------------------------------------------------------------------
    def _request_stop(self):
        self.logger.info("Requesting stop of EET subscriber...")
        self._stop_event.set()
        self.buffer.put(None)

    # ------------------------------------------------------------------
    def _subscriber_cleanup(self):
        self.logger.info("Cleaning up EET subscriber...")
        try:
            self._sensor_subscriber.stop()
        except Exception as e:
            self.logger.debug(f"Error stopping sensor subscriber: {e}")
        self.logger.info("Cleanup complete.")
