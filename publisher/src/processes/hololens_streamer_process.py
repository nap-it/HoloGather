"""HoloLens capture worker process.

This process owns live HoloLens ingestion and keeps high-rate frame traffic
local to the process boundary. Sensor-specific details are delegated to handler
classes, while this process handles orchestration, envelope creation, optional
recording, and optional Zenoh publication.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import time
from pathlib import Path
from collections import defaultdict, deque
from statistics import mean
from typing import Any

from src.config.center import AppConfig
from src.contracts.envelope import SensorEnvelope
from src.contracts.events import HealthEvent
from src.contracts.types import HealthState, SensorType
from src.hololens.handlers.base import HololensHandler
from src.hololens.handlers.depth_handler import DepthHandler
from src.hololens.handlers.eet_handler import EETHandler
from src.hololens.handlers.imu_handler import IMUHandler
from src.hololens.handlers.microphone_handler import MicrophoneHandler
from src.hololens.handlers.pv_handler import PVHandler
from src.hololens.handlers.spatial_input_handler import SpatialInputHandler
from src.hololens.handlers.vlc_handler import VLCHandler
from src.hololens.sink_manager import HololensSinkManager, SinkRuntimeConfig
from src.observability.metrics_emitter import emit_metric
from src.publish.zenoh_publisher import ZenohPublisherService
from src.runtime.buses import RuntimeBuses
from src.runtime.lifecycle import ManagedProcess
from src.storage.reader import StreamReader
from src.storage.recorder import StreamRecorder
from src.sync.replay_scheduler import ReplayScheduler
from src.sync.replay_anchor import session_replay_anchor_ns, shared_playback_epoch_ns


VLC_CAMERA_KEYS = ("leftfront", "leftleft", "rightfront", "rightright")
IMU_KEYS = ("accelerometer", "gyroscope", "magnetometer")


class HololensStreamerProcess(ManagedProcess):
    """Process that captures frames from configured HoloLens handlers."""

    def __init__(self, cfg: AppConfig, buses: RuntimeBuses):
        super().__init__(name="HololensStreamerProcess")
        self.cfg = cfg
        self.buses = buses
        self._last_frame_stamp: dict[str, int] = {}

    def _sensor_tokens(self, name: str) -> tuple[str, ...]:
        """Return matching sensor tokens for `name` (supports `name:...`)."""
        out: list[str] = []
        for token in self.cfg.hololens.sensors:
            if token == name or token.startswith(f"{name}:"):
                out.append(token)
        return tuple(out)

    def _is_sensor_enabled(self, name: str) -> bool:
        """Check if sensor name is enabled by unified sensor list."""
        return len(self._sensor_tokens(name)) > 0

    def _sensor_option_values(self, name: str, key: str) -> tuple[str, ...]:
        """Parse option values from tokens like `name:key=a,b,c` or `name:key=a,b,c`."""
        out: list[str] = []
        for token in self._sensor_tokens(name):
            if ":" not in token:
                continue
            opt_expr = token.split(":", 1)[1].strip()
            if not opt_expr or "=" not in opt_expr:
                continue
            opt_key, opt_val = opt_expr.split("=", 1)
            if opt_key.strip().lower() != key.lower():
                continue
            out.extend(v.strip().lower() for v in opt_val.split(",") if v.strip())
        return tuple(out)

    def _selected_imu_labels(self) -> tuple[str, ...]:
        """Resolve requested IMU sensors from `hololens_imu:sensor=...` tokens."""
        raw = self._sensor_option_values("hololens_imu", "sensor")
        if not raw or "all" in raw:
            return IMU_KEYS

        mapping = {
            "accelerometer": "accelerometer",
            "rm_imu_accelerometer": "accelerometer",
            "gyroscope": "gyroscope",
            "rm_imu_gyroscope": "gyroscope",
            "magnetometer": "magnetometer",
            "rm_imu_magnetometer": "magnetometer",
        }
        selected: list[str] = []
        for item in raw:
            canon = mapping.get(item)
            if canon is not None and canon not in selected:
                selected.append(canon)
        return tuple(selected)

    def _selected_vlc_cameras(self) -> tuple[str, ...]:
        """Resolve requested VLC cameras from `hololens_vlc:sensor=...` tokens."""
        raw = self._sensor_option_values("hololens_vlc", "sensor")
        if not raw or "all" in raw:
            return VLC_CAMERA_KEYS

        mapping = {
            "leftfront": "leftfront",
            "rm_vlc_leftfront": "leftfront",
            "leftleft": "leftleft",
            "rm_vlc_leftleft": "leftleft",
            "rightfront": "rightfront",
            "rm_vlc_rightfront": "rightfront",
            "rightright": "rightright",
            "rm_vlc_rightright": "rightright",
        }
        selected: list[str] = []
        for item in raw:
            canon = mapping.get(item)
            if canon is not None and canon not in selected:
                selected.append(canon)
        return tuple(selected)

    def _build_handlers(self) -> list[HololensHandler]:
        """Instantiate enabled sensor handlers from centralized config."""
        handlers: list[HololensHandler] = []

        if self._is_sensor_enabled("hololens_camera") and self.cfg.hololens.camera.enabled:
            handlers.append(
                PVHandler(
                    user_id=self.cfg.hololens.user_id,
                    port_name=self.cfg.hololens.camera.stream_port_name,
                    publish_topic=self.cfg.hololens.camera.publish_topic,
                    width=self.cfg.hololens.camera.width,
                    height=self.cfg.hololens.camera.height,
                    framerate=self.cfg.hololens.camera.framerate,
                    divisor=self.cfg.hololens.camera.divisor,
                    profile_name=self.cfg.hololens.camera.profile,
                    gop_size=self.cfg.hololens.camera.gop_size,
                )
            )

        if self._is_sensor_enabled("hololens_depth") and self.cfg.hololens.depth.enabled:
            handlers.append(
                DepthHandler(
                    user_id=self.cfg.hololens.user_id,
                    depth_sensor_name=self.cfg.hololens.depth.depth_sensor,
                    publish_topic=self.cfg.hololens.depth.publish_topic,
                )
            )

        if self._is_sensor_enabled("hololens_microphone") and self.cfg.hololens.microphone.enabled:
            handlers.append(
                MicrophoneHandler(
                    user_id=self.cfg.hololens.user_id,
                    port_name=self.cfg.hololens.microphone.stream_port_name,
                    publish_topic=self.cfg.hololens.microphone.publish_topic,
                    profile_name=self.cfg.hololens.microphone.profile,
                    chunk_name=self.cfg.hololens.microphone.chunk,
                    level_name=self.cfg.hololens.microphone.level,
                    decoded=self.cfg.hololens.microphone.decoded,
                )
            )

        if self._is_sensor_enabled("hololens_eet") and self.cfg.hololens.eet.enabled:
            handlers.append(
                EETHandler(
                    user_id=self.cfg.hololens.user_id,
                    port_name=self.cfg.hololens.eet.stream_port_name,
                    publish_topic=self.cfg.hololens.eet.publish_topic,
                    fps=self.cfg.hololens.eet.fps,
                    decoded=self.cfg.hololens.eet.decoded,
                )
            )

        if self._is_sensor_enabled("hololens_si") and self.cfg.hololens.spatial_input.enabled:
            handlers.append(
                SpatialInputHandler(
                    user_id=self.cfg.hololens.user_id,
                    port_name=self.cfg.hololens.spatial_input.stream_port_name,
                    publish_topic=self.cfg.hololens.spatial_input.publish_topic,
                    decoded=self.cfg.hololens.spatial_input.decoded,
                )
            )

        if self._is_sensor_enabled("hololens_imu") and self.cfg.hololens.imu.enabled:
            selected_imu = self._selected_imu_labels()
            if "accelerometer" in selected_imu:
                handlers.append(
                    IMUHandler(
                        user_id=self.cfg.hololens.user_id,
                        imu_label="accelerometer",
                        port_name=self.cfg.hololens.imu.accelerometer.stream_port_name,
                        publish_topic=self.cfg.hololens.imu.accelerometer.publish_topic,
                        mode_name=self.cfg.hololens.imu.accelerometer.mode,
                        decoded=self.cfg.hololens.imu.decoded,
                    )
                )
            if "gyroscope" in selected_imu:
                handlers.append(
                    IMUHandler(
                        user_id=self.cfg.hololens.user_id,
                        imu_label="gyroscope",
                        port_name=self.cfg.hololens.imu.gyroscope.stream_port_name,
                        publish_topic=self.cfg.hololens.imu.gyroscope.publish_topic,
                        mode_name=self.cfg.hololens.imu.gyroscope.mode,
                        decoded=self.cfg.hololens.imu.decoded,
                    )
                )
            if "magnetometer" in selected_imu:
                handlers.append(
                    IMUHandler(
                        user_id=self.cfg.hololens.user_id,
                        imu_label="magnetometer",
                        port_name=self.cfg.hololens.imu.magnetometer.stream_port_name,
                        publish_topic=self.cfg.hololens.imu.magnetometer.publish_topic,
                        mode_name=self.cfg.hololens.imu.magnetometer.mode,
                        decoded=self.cfg.hololens.imu.decoded,
                    )
                )

        if self._is_sensor_enabled("hololens_vlc") and self.cfg.hololens.vlc.enabled:
            selected_cameras = self._selected_vlc_cameras()
            for camera_name in selected_cameras:
                camera_cfg = getattr(self.cfg.hololens.vlc, camera_name)
                handlers.append(
                    VLCHandler(
                        user_id=self.cfg.hololens.user_id,
                        camera_name=camera_name,
                        port_name=camera_cfg.stream_port_name,
                        publish_topic=camera_cfg.publish_topic,
                        profile_name=self.cfg.hololens.vlc.profile,
                        divisor=self.cfg.hololens.vlc.divisor,
                        gop_size=self.cfg.hololens.vlc.gop_size,
                        decoded=self.cfg.hololens.vlc.decoded,
                    )
                )

        return handlers

    def _new_envelope(
        self,
        sensor_type: SensorType,
        stream_id: str,
        seq: int,
        payload: bytes,
        *,
        source_timestamp: int,
        frame_stamp: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
        calibration: dict[str, Any] | None = None,
    ) -> SensorEnvelope:
        """Create canonical envelope for one outbound frame event."""
        now_ns = time.time_ns()
        return SensorEnvelope(
            schema_version=1,
            sensor_type=sensor_type,
            stream_id=stream_id,
            session_id=self.cfg.session.session_id,
            seq=seq,
            ts_unix_ns=now_ns,
            ts_mono_ns=time.monotonic_ns(),
            source_timestamp=source_timestamp,
            frame_stamp=frame_stamp,
            content_type=content_type,
            metadata=metadata or {},
            calibration=calibration or {},
            payload=payload,
        )

    def _record_file_name(self, stream_id: str) -> str:
        """Return stable record file name for one stream."""
        if stream_id.startswith("pv_"):
            return f"HololensCamera_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("depth_"):
            return f"HololensDepth_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("microphone_"):
            return f"HololensMicrophone_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("eet_"):
            return f"HololensEET_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("spatial_input_"):
            return f"HololensSI_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("imu_accelerometer_"):
            return f"HololensACCELEROMETER_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("imu_gyroscope_"):
            return f"HololensGYROSCOPE_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("imu_magnetometer_"):
            return f"HololensMAGNETOMETER_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("vlc_leftfront_"):
            return f"HololensVLC_leftfront_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("vlc_leftleft_"):
            return f"HololensVLC_leftleft_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("vlc_rightfront_"):
            return f"HololensVLC_rightfront_{self.cfg.hololens.user_id}.hlp2"
        if stream_id.startswith("vlc_rightright_"):
            return f"HololensVLC_rightright_{self.cfg.hololens.user_id}.hlp2"
        return f"{stream_id}.hlp2"

    def _setup_recorders(self, handlers: list[HololensHandler]) -> dict[str, StreamRecorder]:
        """Create per-stream recorders when record mode is active."""
        recorders: dict[str, StreamRecorder] = {}
        if not (self.cfg.recording.enabled and self.cfg.settings.mode == "record"):
            return recorders

        for handler in handlers:
            path = f"{self.cfg.settings.data_dir}/{self._record_file_name(handler.spec.stream_id)}"
            recorders[handler.spec.stream_id] = StreamRecorder(
                path,
                compression=self.cfg.recording.compression,
            )
        return recorders

    def _setup_publishers(
        self, handlers: list[HololensHandler]
    ) -> tuple[dict[str, str], queue.Queue | None, ZenohPublisherService | None]:
        """Create one shared Zenoh dispatcher for all enabled stream topics."""
        stream_topics: dict[str, str] = {}
        if not self.cfg.zenoh.enabled:
            return stream_topics, None, None

        for handler in handlers:
            stream_topics[handler.spec.stream_id] = handler.spec.publish_topic

        topics = tuple(sorted(set(stream_topics.values())))
        queue_size = max(64, len(topics) * 16)
        try:
            queue_size = max(queue_size, int(os.getenv("HOLO_PUBLISHER_ZENOH_QUEUE_SIZE", "0")))
        except Exception:
            pass
        out_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        publisher = ZenohPublisherService(topics, out_queue, self.cfg.zenoh)
        publisher.start()
        return stream_topics, out_queue, publisher

    def _emit_rolling_metrics(
        self,
        incoming_ts: defaultdict[str, deque[float]],
        outgoing_ts: defaultdict[str, deque[float]],
        processing_ms: defaultdict[str, deque[float]],
    ) -> None:
        """Emit per-stream rolling gauges for FPS and processing time."""
        all_streams = set(incoming_ts) | set(outgoing_ts) | set(processing_ms)
        for stream_id in sorted(all_streams):
            emit_metric(
                self.buses.metrics_bus,
                self.name,
                stream_id,
                "fps_in",
                "gauge",
                self._calc_fps(incoming_ts[stream_id]),
            )
            emit_metric(
                self.buses.metrics_bus,
                self.name,
                stream_id,
                "fps_out",
                "gauge",
                self._calc_fps(outgoing_ts[stream_id]),
            )
            proc_samples = processing_ms[stream_id]
            emit_metric(
                self.buses.metrics_bus,
                self.name,
                stream_id,
                "processing_ms",
                "gauge",
                float(mean(proc_samples)) if proc_samples else 0.0,
            )

    def _open_reader_with_fallback(self, file_path: Path) -> tuple[StreamReader | None, SensorEnvelope | None]:
        """Open one stream reader and decode first record using supported compression candidates."""
        for compression in (self.cfg.recording.compression, "none"):
            reader: StreamReader | None = None
            try:
                reader = StreamReader(str(file_path), compression=compression)
                first = reader.read()
                if first is None:
                    reader.close()
                    return None, None
                if compression != self.cfg.recording.compression:
                    logging.getLogger(self.name).warning(
                        "Replay file %s required fallback compression=%s (configured=%s)",
                        file_path,
                        compression,
                        self.cfg.recording.compression,
                )
                return reader, first
            except Exception:
                if reader is not None:
                    try:
                        reader.close()
                    except Exception:
                        pass
                continue
        return None, None

    def _has_required_replay_files(self, data_dir: Path, handlers: list[HololensHandler]) -> bool:
        """Return True if directory contains all stream files for the enabled handlers."""
        required = {self._record_file_name(handler.spec.stream_id) for handler in handlers}
        present = {p.name for p in data_dir.glob("*.hlp2")}
        return required.issubset(present)

    def _recording_folder_key(self, folder_name: str) -> tuple[int, str]:
        """Sort key for timestamped recording folders."""
        m = re.match(r"^(?:hololens_)?recording_(?:\d+_)?(\d{8}_\d{6}|\d+)$", folder_name)
        if not m:
            return (0, folder_name)
        ts = m.group(1)
        if "_" in ts:
            return (1, ts)  # YYYYMMDD_HHMMSS keeps lexical ordering.
        return (2, ts.zfill(20))  # Numeric timestamps.

    def _resolve_simulation_data_dir(self, handlers: list[HololensHandler]) -> Path:
        """Resolve replay folder from configured path using requested precedence rules."""
        root = Path(self.cfg.settings.data_dir)
        candidates: list[Path] = [root]

        recordings_dir = root / "recordings"
        if recordings_dir.is_dir():
            candidates.append(recordings_dir)

        # If the provided path (or `<path>/recordings`) has dated recording folders, pick the latest.
        recording_folders: list[Path] = []
        for base in (root, recordings_dir):
            if not base.is_dir():
                continue
            for item in base.iterdir():
                if not item.is_dir():
                    continue
                if item.name.startswith("hololens_recording_") or item.name.startswith("recording_"):
                    recording_folders.append(item)
        recording_folders.sort(key=lambda p: self._recording_folder_key(p.name), reverse=True)
        candidates.extend(recording_folders)

        for candidate in candidates:
            if candidate.is_dir() and self._has_required_replay_files(candidate, handlers):
                return candidate

        # Fallback for partial datasets: prefer newest recording folder when present.
        fallback_candidates = recording_folders + [c for c in candidates if c not in recording_folders]
        for candidate in fallback_candidates:
            if candidate.is_dir():
                return candidate
        return root

    def _run_simulation(
        self,
        handlers: list[HololensHandler],
        stream_topics: dict[str, str],
        publish_queue: queue.Queue | None,
    ) -> None:
        """Replay stream files from `settings.data_dir` with monotonic pacing."""
        log = logging.getLogger(self.name)
        data_dir = self._resolve_simulation_data_dir(handlers)
        log.info("Simulation replay source directory: %s", data_dir)

        # stream_id -> {"reader": StreamReader, "next_env": SensorEnvelope}
        sources: dict[str, dict[str, object]] = {}
        for handler in handlers:
            stream_id = handler.spec.stream_id
            file_path = data_dir / self._record_file_name(stream_id)
            if not file_path.exists():
                log.warning("Simulation file missing for stream=%s path=%s", stream_id, file_path)
                continue
            reader, first_env = self._open_reader_with_fallback(file_path)
            if reader is None or first_env is None:
                log.warning("Could not read replay data for stream=%s path=%s", stream_id, file_path)
                continue
            sources[stream_id] = {"reader": reader, "next_env": first_env}

        if not sources:
            raise RuntimeError(
                f"simulation mode requested, but no readable .hlp2 files were found in {data_dir}"
            )

        # Anchor to the SESSION-WIDE earliest sample (across every stream in the
        # recording), shared by all replay processes, so cross-stream offsets
        # (e.g. camera starting seconds after the GPS) are preserved. Fall back to
        # this process's own earliest sample only if the session scan fails.
        first_event_mono_ns = session_replay_anchor_ns(
            data_dir, self.cfg.recording.compression
        )
        if first_event_mono_ns is None:
            first_event_mono_ns = min(
                int(source["next_env"].ts_mono_ns) for source in sources.values()
            )
        scheduler = ReplayScheduler(
            playback_start_mono_ns=shared_playback_epoch_ns(
                self.cfg.session.session_start_mono_ns
            ),
            first_event_mono_ns=first_event_mono_ns,
        )
        log.info(
            "Replay anchor=%d epoch=%d (shared session timeline)",
            first_event_mono_ns, scheduler.playback_start_mono_ns,
        )

        incoming_ts: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))
        outgoing_ts: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))
        processing_ms: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))
        next_metrics_emit = time.monotonic() + 1.0

        while not self.should_stop() and sources:
            stream_id = min(
                sources.keys(),
                key=lambda sid: int(sources[sid]["next_env"].ts_mono_ns),  # type: ignore[union-attr]
            )
            source = sources[stream_id]
            env: SensorEnvelope = source["next_env"]  # type: ignore[assignment]

            scheduler.wait_until(env)
            packet_start_ns = time.perf_counter_ns()
            incoming_ts[stream_id].append(time.monotonic())

            topic = stream_topics.get(stream_id)
            if publish_queue is not None and topic is not None:
                try:
                    publish_queue.put_nowait((topic, env))
                except queue.Full:
                    emit_metric(
                        self.buses.metrics_bus,
                        self.name,
                        stream_id,
                        "zenoh_queue_drops",
                        "counter",
                        1.0,
                    )

            emit_metric(
                self.buses.metrics_bus,
                self.name,
                stream_id,
                "frames_out",
                "counter",
                1.0,
            )
            outgoing_ts[stream_id].append(time.monotonic())
            processing_ms[stream_id].append((time.perf_counter_ns() - packet_start_ns) / 1_000_000.0)

            reader: StreamReader = source["reader"]  # type: ignore[assignment]
            next_env = reader.read()
            if next_env is None:
                reader.close()
                del sources[stream_id]
            else:
                source["next_env"] = next_env

            now_mono = time.monotonic()
            if now_mono >= next_metrics_emit:
                self._emit_rolling_metrics(incoming_ts, outgoing_ts, processing_ms)
                next_metrics_emit = now_mono + 1.0
            self.buses.health_bus.put(
                HealthEvent(self.name, HealthState.READY, heartbeat_unix_ns=time.time_ns())
            )

        for source in sources.values():
            reader = source.get("reader")
            if isinstance(reader, StreamReader):
                reader.close()

    def _run_live(
        self,
        handlers: list[HololensHandler],
        stream_topics: dict[str, str],
        publish_queue: queue.Queue | None,
        recorders: dict[str, StreamRecorder],
    ) -> None:
        """Run live HoloLens capture from `hl2ss` sinks."""
        calibration_by_stream: dict[str, dict[str, Any]] = {}
        disable_calibration = os.getenv("HOLO_PUBLISHER_DISABLE_CALIBRATION", "0").strip() in {"1", "true", "yes"}
        if not disable_calibration:
            for handler in handlers:
                try:
                    calibration_by_stream[handler.spec.stream_id] = handler.calibration(
                        self.cfg.hololens.address
                    )
                except Exception:
                    logging.getLogger(self.name).debug(
                        "Calibration fetch failed for stream=%s", handler.spec.stream_id, exc_info=True
                    )
                    calibration_by_stream[handler.spec.stream_id] = {}

        sink_mgr = HololensSinkManager(
            SinkRuntimeConfig(
                host=self.cfg.hololens.address,
                buffer_size=self.cfg.hololens.sink_buffer,
            ),
            handlers,
        )
        sink_mgr.start()

        incoming_ts: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))
        outgoing_ts: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))
        processing_ms: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=60))
        seq_by_stream: defaultdict[str, int] = defaultdict(int)
        next_metrics_emit = time.monotonic() + 1.0

        try:
            while not self.should_stop():
                now_ns = time.time_ns()
                now_mono = time.monotonic()
                did_work = False

                for port in sink_mgr.iter_ports():
                    sink = sink_mgr.get_sink(port)
                    handler = sink_mgr.get_handler(port)
                    if sink is None or handler is None:
                        continue
                    try:
                        acquired = sink.acquire(block=False)
                    except Exception:
                        continue
                    if not acquired:
                        continue

                    frame_stamp, frame = sink.get_most_recent_frame()
                    if frame is None:
                        continue

                    stream_id = handler.spec.stream_id
                    if int(frame_stamp) <= self._last_frame_stamp.get(stream_id, -1):
                        continue
                    packet_start_ns = time.perf_counter_ns()
                    incoming_ts[stream_id].append(time.monotonic())

                    payload = handler.to_payload(frame)
                    if not payload:
                        continue

                    self._last_frame_stamp[stream_id] = int(frame_stamp)
                    env = self._new_envelope(
                        handler.spec.sensor_type,
                        stream_id=stream_id,
                        seq=seq_by_stream[stream_id],
                        payload=payload,
                        source_timestamp=handler.source_timestamp(frame, now_ns),
                        frame_stamp=int(frame_stamp),
                        content_type=handler.content_type(),
                        metadata=handler.packet_metadata(frame),
                        calibration=calibration_by_stream.get(stream_id, {}),
                    )
                    seq_by_stream[stream_id] += 1

                    recorder = recorders.get(stream_id)
                    if recorder is not None:
                        recorder.write(env)

                    topic = stream_topics.get(stream_id)
                    if publish_queue is not None and topic is not None:
                        try:
                            publish_queue.put_nowait((topic, env))
                        except queue.Full:
                            emit_metric(
                                self.buses.metrics_bus,
                                self.name,
                                stream_id,
                                "zenoh_queue_drops",
                                "counter",
                                1.0,
                            )

                    emit_metric(
                        self.buses.metrics_bus,
                        self.name,
                        stream_id,
                        "frames_out",
                        "counter",
                        1.0,
                    )
                    outgoing_ts[stream_id].append(time.monotonic())
                    processing_ms[stream_id].append((time.perf_counter_ns() - packet_start_ns) / 1_000_000.0)
                    did_work = True

                if now_mono >= next_metrics_emit:
                    self._emit_rolling_metrics(incoming_ts, outgoing_ts, processing_ms)
                    next_metrics_emit = now_mono + 1.0

                self.buses.health_bus.put(HealthEvent(self.name, HealthState.READY, heartbeat_unix_ns=now_ns))
                if not did_work:
                    time.sleep(0.001)
        finally:
            sink_mgr.stop()

    def _calc_fps(self, ts: deque[float]) -> float:
        """Compute rolling FPS from recent monotonic timestamps."""
        if len(ts) < 2:
            return 0.0
        duration = ts[-1] - ts[0]
        if duration <= 0:
            return 0.0
        return (len(ts) - 1) / duration

    def run(self) -> None:
        """Main capture loop.

        The sink manager owns device connection/startup for configured handlers.
        This loop is generic: it polls sinks, delegates payload conversion to
        handlers, then forwards envelopes to recording/publishing sinks.
        """
        handlers = self._build_handlers()
        recorders = self._setup_recorders(handlers)
        stream_topics, publish_queue, publisher_service = self._setup_publishers(handlers)

        self.buses.health_bus.put(HealthEvent(self.name, HealthState.READY, heartbeat_unix_ns=time.time_ns()))

        try:
            if self.cfg.settings.mode == "simulation":
                self._run_simulation(handlers, stream_topics, publish_queue)
            else:
                self._run_live(handlers, stream_topics, publish_queue, recorders)
        finally:
            self.buses.health_bus.put(HealthEvent(self.name, HealthState.STOPPING, heartbeat_unix_ns=time.time_ns()))
            for recorder in recorders.values():
                recorder.close()
            if publisher_service is not None:
                publisher_service.stop()
                publisher_service.join(timeout=2.0)
                publisher_service.cleanup()
