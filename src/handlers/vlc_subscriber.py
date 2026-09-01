from __future__ import annotations

import os
import sys
import cv2
import logging
import configparser
import signal
import time

from src.hl2ss_imports import hl2ss

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.zenoh_utils.sensor_zenoh_reader import SensorZenohReader, SensorPacket
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.serialization.packet_codec import decode
from src.serialization.hl2ss_packet import unwrap_sensor_payload
from src.utils.video_streaming import VideoStreaming


class VLCSubscriber(BaseSubscriberProcess):
    """
    Subscriber for VLC camera packets encoded with the new wire format.
    Decodes raw H265/H264 payload using hl2ss.decode_rm_vlc.
    """

    def __init__(self, config_file: str, vlc_type: str = "leftleft"):
        super().__init__("VLCSubscriber")
        self.config_file = config_file
        self.vlc_type = vlc_type.lower()

        self.config = configparser.ConfigParser()
        self.config.read(self.config_file)

        section = "VLC"
        self.topic = self.config.get(section, "topic", fallback="Hololens/VLC")
        self.topic += "/" + self.vlc_type.strip()
        self.host = self.config.get(section, "host", fallback="0.0.0.0")

        self.rtsp_port = self.config.getint(section, "rtsp_port", fallback=8554)
        path_base = self.config.get(section, "path", fallback="vlc_camera")
        stream_base = self.config.get(section, "stream_name", fallback="vlc_camera")
        self.path = f"{path_base}_{self.vlc_type}"
        self.stream_name = f"{stream_base}_{self.vlc_type}"
        self.max_size = self.config.getint(section, "sensor_queue_size", fallback=25)
        self.video_stream_buffer_size = self.config.getint(section, "video_stream_buffer_size", fallback=2)
        self.stream_fps = self.config.getint(section, "stream_fps", fallback=30)
        
        prof_str = self.config.get(section, "profile", fallback="H265_MAIN")
        self.profile = getattr(hl2ss.VideoProfile, prof_str, hl2ss.VideoProfile.H265_MAIN)

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=2)

        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )

        self.video_stream = VideoStreaming(
            host=self.host,
            port=0,
            path=self.path,
            stream_name=self.stream_name,
            buffer_size=self.video_stream_buffer_size,
            fps=self.stream_fps,
            rtsp_port=self.rtsp_port,
        )

        self.logger.info(f"VLC path: {self.path}")

        # Lazy-initialised on first packet (needs profile from metadata).
        self._vlc_decoder = None
        self._packet_count = 0
        self._decode_resync_count = 0

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

        if self._vlc_decoder is None:
            try:
                self._vlc_decoder = hl2ss.decode_rm_vlc(self.profile)
            except Exception as e:
                self.logger.error(f"Could not create VLC decoder: {e}")
                return

        try:
            vlc_frame = self._vlc_decoder.decode(payload)
        except AttributeError:
            # PyAV returned None for this packet — normal during decoder warm-up.
            # Keep the decoder alive to avoid cascading reset cycles.
            return
        except Exception as e:
            self._decode_resync_count += 1
            if self._decode_resync_count <= 3 or self._decode_resync_count % 100 == 0:
                self.logger.warning(
                    "VLC decoder resync #%d (expected transient after keyframe loss): %s",
                    self._decode_resync_count,
                    e,
                )
            self._vlc_decoder = None
            return

        img = vlc_frame.image
        if img is None:
            return

        # VLC frames are grayscale (H x W); VideoStreaming requires BGR (H x W x 3)
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        self.video_stream.queue_frame(img)

        self._packet_count += 1
        if self._packet_count % 100 == 0:
            self.logger.debug(
                f"Camera {self.vlc_type} | frame #{self._packet_count} | ts={metadata.get('ts_unix_ns')}"
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
