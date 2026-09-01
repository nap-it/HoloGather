from __future__ import annotations

import signal
import time
from collections import deque

import numpy as np
import cv2
import configparser
import os

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.zenoh_utils.sensor_zenoh_reader import SensorZenohReader, SensorPacket
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.serialization.packet_codec import decode


class DepthCorrelatedSubscriber(BaseSubscriberProcess):
    """
    Subscriber for depth-correlated packets (aligned float32 depth map).
    Payload is raw float32 bytes; shape is in metadata as 'h' and 'w'.
    Saves a colourised depth visualisation to ./recordings/ inside the container.
    """

    def __init__(self, config_file: str, save_video: bool = True):
        super().__init__("DepthCorrelatedSubscriber")
        self.config_file = config_file
        self.save_video = save_video

        config = configparser.ConfigParser()
        config.read(self.config_file)

        section = "DEPTH_CORRELATOR"
        self.topic = config.get(section, "topic", fallback="Hololens/DepthCorrelated")
        self.max_size = config.getint(section, "sensor_queue_size", fallback=10)

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=self.max_size)

        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )

        self._last_log_t = 0.0
        self._last_stats_frame_count = 0
        self._count = 0
        self._dt_s_window: deque = deque(maxlen=300)
        self._valid_ratio_window: deque = deque(maxlen=300)
        self._high_dt_drop_count = 0
        self._low_coverage_count = 0
        self.max_dt_s_warn = config.getfloat(section, "max_dt_s_warn", fallback=0.06)
        self.min_valid_ratio_warn = config.getfloat(section, "min_valid_ratio_warn", fallback=0.02)
        self.expected_width = config.getint("CAMERA", "width", fallback=0)
        self.expected_height = config.getint("CAMERA", "height", fallback=0)

        self.writer = None
        self.save_dir = "/root/app/recordings"
        os.makedirs(self.save_dir, exist_ok=True)
        filename = f"depth_debug_{int(time.time())}.avi"
        self.output_filepath = os.path.join(self.save_dir, filename)

    # ------------------------------------------------------------------
    def _log_stats(self, a: np.ndarray, a_valid: np.ndarray, dt_s: float) -> None:
        now = time.time()
        if now - self._last_log_t <= 1.0:
            return

        frames_in_window = self._count - self._last_stats_frame_count
        elapsed = now - self._last_log_t if self._last_log_t > 0 else 1.0
        fps = frames_in_window / max(elapsed, 1e-6)

        dt_ms_mean = (np.mean(self._dt_s_window) * 1000.0) if self._dt_s_window else 0.0
        dt_ms_max = (np.max(self._dt_s_window) * 1000.0) if self._dt_s_window else 0.0
        valid_ratio_mean = np.mean(self._valid_ratio_window) if self._valid_ratio_window else 0.0

        if a_valid.size > 0:
            mn, mx, mean = np.min(a_valid), np.max(a_valid), np.mean(a_valid)
            self.logger.info(
                f"#{self._count} shape={a.shape} fps={fps:.1f} "
                f"dt_ms(mean/max)={dt_ms_mean:.1f}/{dt_ms_max:.1f} "
                f"valid={valid_ratio_mean*100:.1f}% "
                f"z(min/mean/max)={mn:.3f}/{mean:.3f}/{mx:.3f} "
                f"warn(dt>{self.max_dt_s_warn:.3f}s)={self._high_dt_drop_count} "
                f"warn(valid<{self.min_valid_ratio_warn*100:.1f}%)={self._low_coverage_count}"
            )
        else:
            self.logger.info(
                f"#{self._count} shape={a.shape} fps={fps:.1f} "
                f"dt_ms(mean/max)={dt_ms_mean:.1f}/{dt_ms_max:.1f} "
                f"valid={valid_ratio_mean*100:.1f}% (no valid depth values)"
            )

        if self.expected_width > 0 and self.expected_height > 0 and (
            a.shape[1] != self.expected_width or a.shape[0] != self.expected_height
        ):
            self.logger.warning(
                f"Aligned depth shape mismatch: got {a.shape}, "
                f"expected ({self.expected_height}, {self.expected_width})"
            )

        self._last_stats_frame_count = self._count
        self._last_log_t = now

    # ------------------------------------------------------------------
    def _write_video_frame(
        self, a: np.ndarray, a_valid: np.ndarray, dt_s: float, valid_ratio: float
    ) -> None:
        vis_data = a.copy()
        finite = np.isfinite(a)
        vis_data[~finite] = 0.0

        if a_valid.size > 0:
            mx_val = float(np.percentile(a_valid, 99))
            if mx_val > 0:
                vis_data = np.clip(vis_data / mx_val, 0.0, 1.0)

        vis_u8 = (vis_data * 255).astype(np.uint8)
        vis_color = cv2.applyColorMap(vis_u8, cv2.COLORMAP_TURBO)
        overlay = f"frame={self._count} dt={dt_s*1000.0:.1f}ms valid={valid_ratio*100.0:.1f}%"
        cv2.putText(
            vis_color, overlay, (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
        )

        if self.writer is None:
            h, w = vis_color.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self.writer = cv2.VideoWriter(self.output_filepath, fourcc, 5.0, (w, h))
            if not self.writer.isOpened():
                self.logger.error(f"Could not open video writer: {self.output_filepath}")

        if self.writer is not None and self.writer.isOpened():
            self.writer.write(vis_color)

    # ------------------------------------------------------------------
    def _process_packet(self, packet: SensorPacket) -> None:
        try:
            metadata, payload = decode(packet.message)
        except Exception as e:
            self.logger.error(f"Failed to deserialize correlated packet: {e}")
            return

        h = metadata.get("metadata", {}).get("h", 0)
        w = metadata.get("metadata", {}).get("w", 0)
        if h == 0 or w == 0 or len(payload) != h * w * 4:
            self.logger.warning(f"Invalid depth payload: h={h} w={w} bytes={len(payload)}")
            return

        aligned = np.frombuffer(payload, dtype=np.float32).reshape((h, w))
        self._count += 1

        finite = np.isfinite(aligned)
        valid_mask = finite & (aligned > 0.0)
        a_valid = aligned[valid_mask]
        valid_ratio = float(np.count_nonzero(valid_mask)) / float(aligned.size) if aligned.size else 0.0
        dt_s = float(metadata.get("metadata", {}).get("dt", 0.0))

        self._dt_s_window.append(dt_s)
        self._valid_ratio_window.append(valid_ratio)

        if dt_s > self.max_dt_s_warn:
            self._high_dt_drop_count += 1
        if valid_ratio < self.min_valid_ratio_warn:
            self._low_coverage_count += 1

        self._log_stats(aligned, a_valid, dt_s)

        if self.save_video:
            self._write_video_frame(aligned, a_valid, dt_s, valid_ratio)

    # ------------------------------------------------------------------
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.logger.info(f"Subscribing to Zenoh topic: {self.topic}")
        if self.save_video:
            self.logger.info(f"Saving visualisation to: {self.output_filepath}")

        self._sensor_subscriber.run()

        while not self._stop_event.is_set():
            if self.buffer.is_empty():
                time.sleep(0.001)
                continue
            packet = self.buffer.get()
            if packet is not None:
                self._emit_packet_airtime_ms(packet)
                self._process_packet(packet)

        self.logger.info("Stop event received.")

    # ------------------------------------------------------------------
    def _request_stop(self):
        self.logger.info("Stopping...")
        self._stop_event.set()
        self.buffer.put(None)

    # ------------------------------------------------------------------
    def _subscriber_cleanup(self):
        try:
            self._sensor_subscriber.stop()
        except Exception as e:
            self.logger.debug(f"Error stopping sensor subscriber: {e}")

        if self.writer:
            self.writer.release()
            self.logger.info(f"Video saved to {self.output_filepath}")

        self.logger.info("Cleanup complete.")
