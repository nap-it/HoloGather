from __future__ import annotations

import fractions
import logging
import threading
import time

import av
import cv2
import numpy as np

from src.utils.over_writable_fifo import OverWritableFIFO


class VideoStreaming:
    """
    Encode video frames and push them to MediaMTX via RTSP using PyAV.

    Replaces the previous FFmpeg-subprocess + UDP MPEG-TS approach which
    accumulated latency in three buffer layers (CBR rate-control buffer,
    OS pipe, UDP FIFO). PyAV with CRF + RTSP push eliminates all of them:
    each frame is encoded and sent immediately without intermediate buffering.

    Public API: __init__(...), start_service(), queue_frame(frame), join()
    """

    def __init__(
        self,
        host: str,
        port: int,
        path: str,
        stream_name: str,
        buffer_size: int = 2,
        fps: int = 30,
        gop_size: int | None = None,
        rtsp_port: int = 8554,
    ):
        """
        :param host:        MediaMTX host (e.g. "127.0.0.1").
        :param port:        Unused (kept for API compatibility).
        :param path:        MediaMTX stream path (e.g. "pv_camera").
        :param stream_name: Label used in logs.
        :param buffer_size: Frame queue depth (overwritable; keeps only newest frames).
        :param fps:         Target encoder framerate.
        :param gop_size:    Keyframe interval in frames; defaults to 1 second.
        :param rtsp_port:   MediaMTX RTSP port (default 8554).
        """
        self.stream_name = stream_name
        self._rtsp_url = f"rtsp://{host}:{rtsp_port}/{path.lstrip('/')}"
        self._fps = max(1, int(fps))
        self._gop = int(gop_size) if gop_size is not None else self._fps

        self.frame_queue: OverWritableFIFO = OverWritableFIFO(buffer_size)

        self._stop_evt = threading.Event()
        self.server_thread: threading.Thread | None = None

        self._container: av.container.OutputContainer | None = None
        self._stream = None
        self._stream_start: float = 0.0
        self._last_pts: int = -1
        self._started_encoder = False
        self._next_retry_after: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_service(self) -> bool:
        try:
            self.server_thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name=f"rtsp-out-{self.stream_name}",
            )
            self.server_thread.start()
            logging.info(
                "[%s] RTSP streaming thread started -> %s",
                self.stream_name,
                self._rtsp_url,
            )
            return True
        except Exception as e:
            logging.error("[%s] Error starting streaming thread: %s", self.stream_name, e, exc_info=True)
            return False

    def queue_frame(self, frame) -> None:
        """Queue a frame (BGR numpy array or JPEG bytes)."""
        self.frame_queue.put(frame)

    def join(self) -> None:
        self._stop_evt.set()
        if self.server_thread is not None:
            self.server_thread.join(timeout=3.0)
        self._close_container()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop_evt.is_set():
            if self.frame_queue.is_empty():
                time.sleep(0.001)
                continue

            frame = self.frame_queue.get()
            if frame is None:
                continue

            # Accept JPEG bytes as well as numpy BGR arrays.
            if isinstance(frame, (bytes, bytearray, memoryview)):
                npbuf = np.frombuffer(frame, dtype=np.uint8)
                decoded = cv2.imdecode(npbuf, cv2.IMREAD_COLOR)
                if decoded is None:
                    logging.warning("[%s] Dropped frame: JPEG decode failed.", self.stream_name)
                    continue
                frame_bgr = decoded
            else:
                frame_bgr = frame

            if (
                frame_bgr is None
                or not hasattr(frame_bgr, "shape")
                or len(frame_bgr.shape) != 3
                or frame_bgr.shape[2] != 3
            ):
                logging.warning("[%s] Dropped frame: invalid frame shape.", self.stream_name)
                continue

            if time.monotonic() < self._next_retry_after:
                continue

            h, w = frame_bgr.shape[:2]

            if not self._started_encoder:
                self._open_rtsp(w, h)
                if not self._started_encoder:
                    continue

            self._encode_and_send(frame_bgr)

    def _open_rtsp(self, width: int, height: int) -> None:
        self._close_container()
        try:
            container = av.open(
                self._rtsp_url,
                mode="w",
                format="rtsp",
                options={"rtsp_transport": "tcp"},
            )
            stream = container.add_stream("libx264", rate=self._fps)
            stream.width = width
            stream.height = height
            stream.pix_fmt = "yuv420p"
            # time_base must be set before first encode so PTS units are unambiguous.
            stream.time_base = fractions.Fraction(1, self._fps)
            stream.codec_context.options = {
                "preset": "veryfast",
                "profile": "baseline",   # no B-frames, max decoder compatibility
                "tune": "zerolatency",
                "crf": "23",             # VBR: no rate-control buffer, immediate encode
                "sc_threshold": "0",     # disable scene-change forced keyframes
                "keyint_min": str(max(1, self._fps // 3)),
                "refs": "1",             # 1 reference frame — lower decode latency
                "bf": "0",               # no B-frames
                "x264-params": "repeat-headers=1:open-gop=0",
                # repeat-headers=1 embeds SPS/PPS in every IDR so viewers that
                # join mid-stream or reconnect sync immediately.
                # open-gop=0 ensures each GOP is independently decodeable.
            }
            stream.codec_context.gop_size = self._gop

            self._container = container
            self._stream = stream
            self._stream_start = time.monotonic()
            self._last_pts = -1
            self._started_encoder = True
            logging.info(
                "[%s] RTSP session opened -> %s (%dx%d @ %dfps)",
                self.stream_name,
                self._rtsp_url,
                width,
                height,
                self._fps,
            )
        except Exception as e:
            logging.error("[%s] Failed to open RTSP session: %s", self.stream_name, e)
            self._container = None
            self._stream = None
            self._started_encoder = False
            self._next_retry_after = time.monotonic() + 2.0

    def _encode_and_send(self, bgr_frame: np.ndarray) -> None:
        try:
            # Wall-clock PTS: if mux() stalled and frames were dropped from the
            # queue, the PTS gap accurately reflects real elapsed time. The player
            # treats the gap as lost frames and moves on immediately — no latency
            # accumulates. Sequential PTS (the old approach) hid dropped frames and
            # caused the player to fall behind live over time (slow+jump pattern).
            elapsed = time.monotonic() - self._stream_start
            pts = int(elapsed * self._fps)
            pts = max(pts, self._last_pts + 1)  # guarantee monotonic
            self._last_pts = pts

            av_frame = av.VideoFrame.from_ndarray(bgr_frame, format="bgr24")
            av_frame.pts = pts
            for packet in self._stream.encode(av_frame):
                self._container.mux(packet)
        except Exception as e:
            logging.error("[%s] RTSP send error: %s — reconnecting.", self.stream_name, e)
            self._close_container()
            self._next_retry_after = time.monotonic() + 1.0

    def _close_container(self) -> None:
        if self._container is not None:
            try:
                # Flush encoder.
                if self._stream is not None:
                    for packet in self._stream.encode(None):
                        self._container.mux(packet)
            except Exception:
                pass
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
            self._stream = None
            self._started_encoder = False
            logging.info("[%s] RTSP session closed.", self.stream_name)
