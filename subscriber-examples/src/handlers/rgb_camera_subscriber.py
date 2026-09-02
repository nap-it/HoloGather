from __future__ import annotations

import os
import sys
import cv2
import logging
import configparser
import signal
import time
import numpy as np

from src.hl2ss_imports import hl2ss

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.zenoh_utils.sensor_zenoh_reader import SensorZenohReader, SensorPacket
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.serialization.packet_codec import decode
from src.serialization.hl2ss_packet import unwrap_sensor_payload
from src.utils.video_streaming import VideoStreaming


class RGBCameraSubscriber(BaseSubscriberProcess):
    """
    Subscriber for PV camera packets encoded with the new wire format.
    Decodes raw H265/H264 payload using hl2ss.decode_pv.
    """

    def __init__(self, config_file: str):
        super().__init__("RGBCameraSubscriber")
        self.config_file = config_file

        self.config = configparser.ConfigParser()
        self.config.read(self.config_file)

        section = "CAMERA"
        self.topic = self.config.get(section, "topic", fallback="Hololens/RGBCamera")
        self.host = self.config.get(section, "host", fallback="0.0.0.0")
        self.rtsp_port = self.config.getint(section, "rtsp_port", fallback=8554)
        self.path = self.config.get(section, "path", fallback="pv_camera")
        self.stream_name = self.config.get(section, "stream_name", fallback="pv_camera")
        self.max_size = self.config.getint(section, "sensor_queue_size", fallback=120)
        self.video_stream_buffer_size = self.config.getint(section, "video_stream_buffer_size", fallback=2)
        self.stream_fps = self.config.getint(section, "stream_fps", fallback=30)
        
        prof_str = self.config.get(section, "profile", fallback="H265_MAIN")
        self.profile = getattr(hl2ss.VideoProfile, prof_str, hl2ss.VideoProfile.H265_MAIN)
        self._profile_candidates = [self.profile]
        for candidate_name in ("H265_MAIN", "H264_MAIN"):
            candidate = getattr(hl2ss.VideoProfile, candidate_name, None)
            if candidate is not None and candidate not in self._profile_candidates:
                self._profile_candidates.append(candidate)
        self._active_profile_idx = 0

        # Respect configured queue size; tiny queues amplify packet loss artifacts.
        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=max(32, self.max_size))

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

        # Lazy-initialised once we know the video profile from the first packet.
        self._pv_decoder = None
        self._decode_resync_count = 0
        self._artifact_drop_count = 0
        self._rolling_gray_ratio = 0.0
        self._last_seq: int | None = None
        self._need_keyframe = True
        self._recovery_start_time: float = 0.0
        self._recovery_drop_count = 0
        self._consecutive_artifact_count = 0

    def _create_pv_decoder(self):
        profile = self._profile_candidates[self._active_profile_idx]
        self._pv_decoder = hl2ss.decode_pv(profile)

    def _is_likely_artifact_frame(self, img: np.ndarray) -> bool:
        """Heuristic filter for transient gray/blocky decoder artifacts."""
        if img is None or img.size == 0:
            return True

        # Downsample for speed; artifact checks do not need full resolution.
        small = img[::4, ::4]
        b = small[..., 0].astype(np.int16)
        g = small[..., 1].astype(np.int16)
        r = small[..., 2].astype(np.int16)

        # Artifact frames tend to be mostly gray (channels very similar) with low texture.
        near_gray = (np.abs(r - g) < 12) & (np.abs(g - b) < 12) & (np.abs(r - b) < 12)
        gray_ratio = float(np.mean(near_gray))
        luma = 0.114 * b + 0.587 * g + 0.299 * r
        luma_std = float(np.std(luma))

        # Use a rolling baseline so legitimately low-saturation scenes are less likely to be dropped.
        self._rolling_gray_ratio = 0.95 * self._rolling_gray_ratio + 0.05 * gray_ratio
        gray_jump = gray_ratio - self._rolling_gray_ratio

        # Conservative threshold tuned to catch heavy decoder corruption.
        return gray_ratio > 0.90 and luma_std < 28.0 and gray_jump > 0.20

    def _iter_nal_payloads(self, payload: bytes):
        """Yield NAL payloads from Annex-B or AVCC length-prefixed framing."""
        n = len(payload)

        # 1) Annex-B start code framing.
        i = 0
        starts: list[int] = []
        while i + 3 < n:
            if payload[i : i + 3] == b"\x00\x00\x01":
                starts.append(i + 3)
                i += 3
                continue
            if i + 4 < n and payload[i : i + 4] == b"\x00\x00\x00\x01":
                starts.append(i + 4)
                i += 4
                continue
            i += 1
        if starts:
            starts.append(n)
            for idx in range(len(starts) - 1):
                s, e = starts[idx], starts[idx + 1]
                if s < e:
                    yield payload[s:e]
            return

        # 2) AVCC framing with 4-byte big-endian NAL lengths.
        i = 0
        while i + 4 <= n:
            nal_len = int.from_bytes(payload[i : i + 4], byteorder="big", signed=False)
            i += 4
            if nal_len <= 0:
                break
            end = i + nal_len
            if end > n:
                break
            nal = payload[i:end]
            if nal:
                yield nal
            i = end

    def _is_keyframe_payload(self, payload: bytes) -> bool:
        """Best-effort keyframe detection for H264/H265 Annex-B payloads."""
        found_any = False
        for nal in self._iter_nal_payloads(payload):
            found_any = True
            if len(nal) < 2:
                continue
            # H264: type is lower 5 bits of first byte.
            h264_type = nal[0] & 0x1F
            if h264_type in (5, 7, 8):  # IDR, SPS, PPS
                return True
            # H265: type is bits [1..6] of first byte.
            h265_type = (nal[0] >> 1) & 0x3F
            if h265_type in (19, 20, 21, 32, 33, 34):  # IDR/CRA + VPS/SPS/PPS
                return True
        if not found_any:
            # If framing was not parsed, avoid indefinite starvation in recovery mode.
            return True
        return False

    # ------------------------------------------------------------------
    def _process_packet(self, packet: SensorPacket, packet_count: int) -> bool:
        """Decode one packet and push a JPEG frame to the video stream. Returns True on success."""
        try:
            metadata, payload = decode(packet.message)
        except Exception as e:
            self.logger.warning(f"Failed to decode packet: {e}")
            return False
        payload, _pkt = unwrap_sensor_payload(metadata, payload)
        if not payload:
            return False

        seq = metadata.get("seq")
        if isinstance(seq, int):
            if self._last_seq is not None and seq > self._last_seq + 1:
                gap = seq - self._last_seq - 1
                self._need_keyframe = True
                self._pv_decoder = None
                self._recovery_drop_count = 0
                self._recovery_start_time = time.monotonic()
                self.logger.warning(
                    "Detected RGB packet gap (dropped=%d, prev_seq=%d, seq=%d). Waiting for keyframe.",
                    gap,
                    self._last_seq,
                    seq,
                )
            self._last_seq = seq

        if self._need_keyframe and not self._is_keyframe_payload(payload):
            self._recovery_drop_count += 1
            elapsed = time.monotonic() - self._recovery_start_time
            # Time-based deadline: wait at most 500ms for a keyframe regardless of FPS.
            # The publisher uses gop_size=2, so a keyframe is always within 2 frames —
            # a frame-count threshold breaks at low FPS (60 frames = 10s at 6fps).
            if elapsed < 0.5:
                if self._recovery_drop_count <= 3:
                    self.logger.debug(
                        "Skipping non-keyframe RGB packet during decoder recovery (#%d, %.0fms elapsed).",
                        self._recovery_drop_count,
                        elapsed * 1000,
                    )
                return False
            self.logger.warning(
                "Recovery deadline reached for RGB keyframe (#%d dropped, %.0fms); forcing decode.",
                self._recovery_drop_count,
                elapsed * 1000,
            )
            self._need_keyframe = False

        if self._pv_decoder is None:
            try:
                self._create_pv_decoder()
            except Exception as e:
                self.logger.error(f"Could not create PV decoder: {e}")
                return False

        try:
            pv_frame = self._pv_decoder.decode(payload, "bgr24")
        except AttributeError:
            # PyAV returned None for this packet — normal during decoder warm-up
            # (codec needs a few packets before it produces output). Keep the decoder
            # alive; nuking it here would restart the warm-up cycle and cause cascading breaks.
            return False
        except Exception as e:
            self._decode_resync_count += 1
            if self._decode_resync_count <= 3 or self._decode_resync_count % 100 == 0:
                self.logger.warning(
                    "PV decoder resync #%d (expected transient after keyframe loss): %s",
                    self._decode_resync_count,
                    e,
                )
            # After repeated failures, rotate profile to recover from H264/H265 mismatch.
            if self._decode_resync_count % 30 == 0 and len(self._profile_candidates) > 1:
                self._active_profile_idx = (self._active_profile_idx + 1) % len(self._profile_candidates)
                self.logger.debug(
                    "Rotating PV decoder profile candidate to index=%d after repeated resyncs.",
                    self._active_profile_idx,
                )
            self._pv_decoder = None
            self._need_keyframe = True
            return False

        if pv_frame is None or pv_frame.image is None:
            return False

        img = pv_frame.image
        self._need_keyframe = False
        if self._is_likely_artifact_frame(img):
            self._artifact_drop_count += 1
            self._consecutive_artifact_count += 1
            if self._artifact_drop_count <= 3 or self._artifact_drop_count % 50 == 0:
                self.logger.warning(
                    "Dropping likely artifact RGB frame #%d (consecutive=%d)",
                    self._artifact_drop_count,
                    self._consecutive_artifact_count,
                )
            # Only destroy decoder after sustained corruption (3+ consecutive artifact frames).
            # A single transient frame keeps the decoder alive so the stream resumes immediately.
            if self._consecutive_artifact_count >= 3:
                self._pv_decoder = None
                self._need_keyframe = True
                self._consecutive_artifact_count = 0
            return False

        self._consecutive_artifact_count = 0
        self.video_stream.queue_frame(img)

        if packet_count % 100 == 0:
            self.logger.debug(f"Frame #{packet_count} | ts={metadata.get('ts_unix_ns')} | shape={img.shape}")
        return True

    # ------------------------------------------------------------------
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.logger.info(f"Starting Zenoh subscription to topic: {self.topic}")
        self._sensor_subscriber.run()

        self.logger.info("Starting video streaming service...")
        self.video_stream.start_service()

        packet_count = 0

        while not self._stop_event.is_set():
            self._flush_rolling_metrics()
            if self.buffer.is_empty():
                time.sleep(0.001)
                continue
            packet = self.buffer.get()
            if packet is not None:
                self._emit_packet_airtime_ms(packet)
                t0 = time.perf_counter()
                if self._process_packet(packet, packet_count):
                    packet_count += 1
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
