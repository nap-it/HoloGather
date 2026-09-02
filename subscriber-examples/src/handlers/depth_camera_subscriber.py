from __future__ import annotations

import os
import sys
import cv2
import configparser
import numpy as np
import signal
import time

from src.hl2ss_imports import hl2ss

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.zenoh_utils.sensor_zenoh_reader import SensorZenohReader, SensorPacket
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.serialization.packet_codec import decode
from src.serialization.hl2ss_packet import unwrap_sensor_payload
from src.utils.video_streaming import VideoStreaming


class DepthCameraSubscriber(BaseSubscriberProcess):
    """
    Subscriber for depth camera packets encoded with the new wire format.
    Supports both RM_DEPTH_AHAT and RM_DEPTH_LONGTHROW — decoder is chosen
    lazily from the 'ds' field in the first packet metadata.
    """

    def __init__(self, config_file: str):
        super().__init__("DepthCameraSubscriber")
        self.config_file = config_file

        self.config = configparser.ConfigParser()
        self.config.read(self.config_file)

        section = "DEPTH_CAMERA"
        self.topic = self.config.get(section, "topic", fallback="Hololens/DepthCamera")
        self.host = self.config.get(section, "host", fallback="0.0.0.0")
        self.port = self.config.getint(section, "port", fallback=3201)
        self.path = self.config.get(section, "path", fallback="depth_camera")
        self.stream_name = self.config.get(section, "stream_name", fallback="depth_camera")
        self.max_size = self.config.getint(section, "sensor_queue_size", fallback=25)
        self.video_stream_buffer_size = self.config.getint(section, "video_stream_buffer_size", fallback=2)
        self.stream_fps = self.config.getint(section, "stream_fps", fallback=5)
        self.depth_sensor = self.config.get(section, "depth_sensor", fallback="RM_DEPTH_LONGTHROW")

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=2)

        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )

        self.video_stream = VideoStreaming(
            host=self.host,
            port=self.port,
            path=self.path,
            stream_name=self.stream_name,
            buffer_size=self.video_stream_buffer_size,
            fps=self.stream_fps,
        )

        # Lazy-initialised on the first packet.
        self._depth_decoder = None
        self._packet_count = 0

    # ------------------------------------------------------------------
    def _make_depth_decoder(self, ds_str: str):
        """Select the right hl2ss depth decoder from the sensor port string."""
        if str(hl2ss.StreamPort.RM_DEPTH_AHAT) in ds_str:
            return hl2ss.decode_rm_depth_ahat(
                hl2ss.DepthProfile.SAME, hl2ss.VideoProfile.H265_MAIN
            )
        # Default: LongThrow uses PNG-encoded composite image.
        return hl2ss.decode_rm_depth_longthrow(hl2ss.VideoProfile.H264_BASE)

    # ------------------------------------------------------------------
    def _process_packet(self, packet: SensorPacket) -> None:
        try:
            metadata, payload = decode(packet.message)
        except Exception as e:
            self.logger.warning(f"Failed to decode packet: {e}")
            return
        payload, _pkt = unwrap_sensor_payload(metadata, payload)
        if not payload:
            return

        if self._depth_decoder is None:
            self._depth_decoder = self._make_depth_decoder(self.depth_sensor)

        try:
            depth_frame = self._depth_decoder.decode(payload)
        except Exception as e:
            self.logger.warning(f"Depth decode error: {e}")
            return

        depth_img = depth_frame.depth.astype(np.float32)
        depth_norm = cv2.normalize(depth_img, None, 0, 255, cv2.NORM_MINMAX)
        depth_vis = np.uint8(depth_norm)

        ab = depth_frame.ab
        if ab is not None:
            ab_norm = cv2.normalize(ab, None, 0, 255, cv2.NORM_MINMAX)
            vis = cv2.applyColorMap(np.uint8(ab_norm), cv2.COLORMAP_JET)
        else:
            vis = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)

        self.video_stream.queue_frame(vis)

        self._packet_count += 1
        if self._packet_count % 100 == 0:
            self.logger.debug(
                f"Frame #{self._packet_count} | ts={metadata.get('ts_unix_ns')} | ds={metadata.get('metadata', {}).get('ds')}"
            )

    # ------------------------------------------------------------------
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.logger.info(f"Starting Zenoh subscription to topic: {self.topic}")
        self._sensor_subscriber.run()

        self.logger.info("Starting video streaming service...")
        self.video_stream.start_service()

        while not self._stop_event.is_set():
            self._flush_rolling_metrics()
            if self.buffer.is_empty():
                time.sleep(0.001)
                continue
            packet = self.buffer.get()
            if packet is not None:
                self._emit_packet_airtime_ms(packet)
                t0 = time.perf_counter()
                self._process_packet(packet)
                self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)

        self.logger.info("Stop event received in subscriber loop.")

    # ------------------------------------------------------------------
    def _request_stop(self):
        self.logger.info("Requesting Zenoh reader stop...")
        self._stop_event.set()
        self.buffer.put(None)

    # ------------------------------------------------------------------
    def _subscriber_cleanup(self):
        self.logger.info("Cleaning up subscriber...")
        try:
            self._sensor_subscriber.stop()
        except Exception as e:
            self.logger.debug(f"Error stopping sensor subscriber: {e}")
        try:
            self.video_stream.join()
        except Exception as e:
            self.logger.debug(f"Error stopping video stream: {e}")
        self.logger.info("Cleanup complete.")
