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


class SpatialInputSubscriber(BaseSubscriberProcess):
    """
    Subscriber for Spatial Input packets encoded with the new wire format.
    Payload is unpacked from a full hl2ss packet and decoded with `decode_si`.
    """

    def __init__(self, config_file: str):
        super().__init__("SpatialInputSubscriber")
        self.config_file = config_file

        config = configparser.ConfigParser()
        config.read(self.config_file)

        section = "SPATIAL_INPUT"
        self.topic = config.get(section, "topic", fallback="Hololens/SpatialInput")
        self.max_size = config.getint(section, "sensor_queue_size", fallback=25)

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=self.max_size)

        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )
        self._si_decoder = hl2ss.decode_si()

    # ------------------------------------------------------------------
    def _log_frame(self, metadata: dict, si_frame) -> None:
        ts = metadata.get("ts_unix_ns", 0)
        self.logger.info(f"Tracking status at time {ts}")

        if si_frame.head_pose_valid:
            hp = si_frame.head_pose
            self.logger.info(
                f"Head pose: Position={hp.position.tolist()} "
                f"Forward={hp.forward.tolist()} Up={hp.up.tolist()}"
            )
        else:
            self.logger.info("No head pose data")

        if si_frame.eye_ray_valid:
            er = si_frame.eye_ray
            self.logger.info(
                f"Eye ray: Origin={er.origin.tolist()} Direction={er.direction.tolist()}"
            )
        else:
            self.logger.info("No eye tracking data")

        if si_frame.hand_left_valid:
            w_idx = int(hl2ss.SI_HandJointKind.Wrist)
            self.logger.info(
                "Left wrist: Position=%s Orientation=%s Radius=%.4f Accuracy=%s",
                si_frame.hand_left.position[w_idx].tolist(),
                si_frame.hand_left.orientation[w_idx].tolist(),
                float(si_frame.hand_left.radius[w_idx]),
                int(si_frame.hand_left.accuracy[w_idx]),
            )
        else:
            self.logger.info("No left hand data")

        if si_frame.hand_right_valid:
            w_idx = int(hl2ss.SI_HandJointKind.Wrist)
            self.logger.info(
                "Right wrist: Position=%s Orientation=%s Radius=%.4f Accuracy=%s",
                si_frame.hand_right.position[w_idx].tolist(),
                si_frame.hand_right.orientation[w_idx].tolist(),
                float(si_frame.hand_right.radius[w_idx]),
                int(si_frame.hand_right.accuracy[w_idx]),
            )
        else:
            self.logger.info("No right hand data")

        self.logger.info("-" * 60)

    # ------------------------------------------------------------------
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.logger.info(f"Starting Spatial Input subscription: {self.topic}")
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
                payload, _pkt = unwrap_sensor_payload(metadata, payload)
                if not payload:
                    continue
                si_frame = self._si_decoder.decode(payload)
            except Exception as e:
                self.logger.warning(f"Failed to decode SI packet: {e}")
                continue

            self._log_frame(metadata, si_frame)
            self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)

        self.logger.info("Stop event received in Spatial Input subscriber loop.")

    # ------------------------------------------------------------------
    def _request_stop(self):
        self.logger.info("Requesting Zenoh reader stop...")
        self._stop_event.set()
        self.buffer.put(None)

    # ------------------------------------------------------------------
    def _subscriber_cleanup(self):
        self.logger.info("Cleaning up Spatial Input subscriber...")
        try:
            self._sensor_subscriber.stop()
        except Exception as e:
            self.logger.debug(f"Error stopping sensor subscriber: {e}")
        self.logger.info("Cleanup complete.")
