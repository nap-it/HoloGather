"""Base MQTT sensor worker process.

VAM location and Unity heading processes inherit from this class and only override
payload parsing behavior. Connection/retry lifecycle, recording, and shared bus
emission remain centralized here.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import time
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from statistics import mean

from src.config.center import AppConfig
from src.contracts.envelope import SensorEnvelope
from src.contracts.events import HealthEvent
from src.contracts.types import HealthState, SensorType
from src.mqtt.client_service import MqttClientService
from src.observability.metrics_emitter import emit_metric
from src.publish.zenoh_publisher import ZenohPublisherService
from src.runtime.buses import RuntimeBuses
from src.runtime.lifecycle import ManagedProcess
from src.serialization.payload_codec import encode_payload
from src.storage.reader import StreamReader
from src.storage.recorder import StreamRecorder
from src.sync.replay_scheduler import ReplayScheduler
from src.sync.replay_anchor import session_replay_anchor_ns, shared_playback_epoch_ns


class MqttSensorBaseProcess(ManagedProcess, ABC):
    """Reusable process skeleton for MQTT-driven sensors."""

    sensor_type: SensorType
    topic: str
    stream_id: str
    publish_topic: str

    def __init__(self, name: str, cfg: AppConfig, buses: RuntimeBuses):
        super().__init__(name=name)
        self.cfg = cfg
        self.buses = buses
        self.seq = 0
        self.latest: dict | None = None

    @abstractmethod
    def parse_message(self, payload: bytes) -> dict | None:
        """Parse raw MQTT payload into structured dict or `None` on failure."""
        raise NotImplementedError

    def _build_envelope(self, payload: dict) -> SensorEnvelope:
        """Create canonical envelope from parsed MQTT payload.

        `ts_unix_ns` is the Jetson receipt time. When the parser preserved the
        source measurement time (e.g. OwnTracks `tst`), it is carried in
        `source_timestamp` (ns) so downstream consumers can align the stream to
        the true measurement instant instead of the receipt time.
        """
        now_ns = time.time_ns()
        try:
            source_ts = int(payload.get("source_ts_ns", 0)) if isinstance(payload, dict) else 0
        except (TypeError, ValueError):
            source_ts = 0
        return SensorEnvelope(
            schema_version=1,
            sensor_type=self.sensor_type,
            stream_id=self.stream_id,
            session_id=self.cfg.session.session_id,
            seq=self.seq,
            ts_unix_ns=now_ns,
            ts_mono_ns=time.monotonic_ns(),
            source_timestamp=source_ts,
            content_type="application/msgpack",
            payload=encode_payload(payload),
        )

    def _recording_folder_key(self, folder_name: str) -> tuple[int, str]:
        """Sort key for timestamped recording folders."""
        m = re.match(r"^(?:hololens_)?recording_(?:\d+_)?(\d{8}_\d{6}|\d+)$", folder_name)
        if not m:
            return (0, folder_name)
        ts = m.group(1)
        if "_" in ts:
            return (1, ts)
        return (2, ts.zfill(20))

    def _resolve_simulation_record_file(self) -> Path | None:
        """Resolve replay file for this MQTT stream in the configured data tree."""
        root = Path(self.cfg.settings.data_dir)
        candidates: list[Path] = [root]

        recordings_dir = root / "recordings"
        if recordings_dir.is_dir():
            candidates.append(recordings_dir)

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

        filename = f"{self.stream_id}.hlp2"
        for candidate in candidates:
            path = candidate / filename
            if path.exists():
                return path
        return None

    def _open_reader_with_fallback(self, file_path: Path) -> tuple[StreamReader | None, SensorEnvelope | None]:
        """Open stream reader with compression fallback and read first frame."""
        log = logging.getLogger(self.name)
        for compression in (self.cfg.recording.compression, "none"):
            reader: StreamReader | None = None
            try:
                reader = StreamReader(str(file_path), compression=compression)
                first = reader.read()
                if first is None:
                    reader.close()
                    return None, None
                if compression != self.cfg.recording.compression:
                    log.warning(
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

    def _emit_metrics(
        self,
        incoming_ts: deque[float],
        outgoing_ts: deque[float],
        processing_samples_ms: deque[float],
    ) -> None:
        """Emit rolling metrics for this MQTT stream."""
        emit_metric(
            self.buses.metrics_bus,
            self.name,
            self.stream_id,
            "fps_in",
            "gauge",
            self._calc_fps(incoming_ts),
        )
        emit_metric(
            self.buses.metrics_bus,
            self.name,
            self.stream_id,
            "fps_out",
            "gauge",
            self._calc_fps(outgoing_ts),
        )
        emit_metric(
            self.buses.metrics_bus,
            self.name,
            self.stream_id,
            "processing_ms",
            "gauge",
            float(mean(processing_samples_ms)) if processing_samples_ms else 0.0,
        )

    def _run_simulation(
        self,
        *,
        publish_queue: queue.Queue | None,
        incoming_ts: deque[float],
        outgoing_ts: deque[float],
        processing_samples_ms: deque[float],
    ) -> None:
        """Replay MQTT-derived stream from recorded `.hlp2` events."""
        log = logging.getLogger(self.name)
        file_path = self._resolve_simulation_record_file()
        if file_path is None:
            log.warning(
                "Simulation replay disabled for %s: no replay file found (standby mode).",
                self.stream_id,
            )
            self._run_simulation_standby(incoming_ts, outgoing_ts, processing_samples_ms)
            return

        reader, next_env = self._open_reader_with_fallback(file_path)
        if reader is None or next_env is None:
            log.warning(
                "Simulation replay disabled for %s: replay file is unreadable path=%s (standby mode).",
                self.stream_id,
                file_path,
            )
            self._run_simulation_standby(incoming_ts, outgoing_ts, processing_samples_ms)
            return

        log.info("Simulation replay source for %s: %s", self.stream_id, file_path)
        # Anchor to the SESSION-WIDE earliest sample (shared across all replay
        # processes via a deterministic scan of the recording folder) instead of
        # THIS stream's own first event — otherwise each MQTT stream is zeroed to
        # its own start and loses its true offset to the camera/depth/other GPS.
        anchor_mono_ns = session_replay_anchor_ns(
            file_path.parent, self.cfg.recording.compression
        )
        if anchor_mono_ns is None:
            anchor_mono_ns = int(next_env.ts_mono_ns)
        scheduler = ReplayScheduler(
            playback_start_mono_ns=shared_playback_epoch_ns(
                self.cfg.session.session_start_mono_ns
            ),
            first_event_mono_ns=anchor_mono_ns,
        )
        log.info(
            "Replay anchor=%d epoch=%d for %s (shared session timeline)",
            anchor_mono_ns, scheduler.playback_start_mono_ns, self.stream_id,
        )
        next_metrics_emit = time.monotonic() + 1.0

        try:
            while not self.should_stop() and next_env is not None:
                scheduler.wait_until(next_env)
                packet_start_ns = time.perf_counter_ns()
                incoming_ts.append(time.monotonic())

                if publish_queue is not None:
                    try:
                        publish_queue.put_nowait((self.publish_topic, next_env))
                    except queue.Full:
                        emit_metric(
                            self.buses.metrics_bus,
                            self.name,
                            self.stream_id,
                            "zenoh_queue_drops",
                            "counter",
                            1.0,
                        )

                emit_metric(self.buses.metrics_bus, self.name, self.stream_id, "frames_out", "counter", 1.0)
                outgoing_ts.append(time.monotonic())
                processing_samples_ms.append((time.perf_counter_ns() - packet_start_ns) / 1_000_000.0)

                self.seq = max(self.seq, int(next_env.seq) + 1)
                next_env = reader.read()

                now_mono = time.monotonic()
                if now_mono >= next_metrics_emit:
                    self._emit_metrics(incoming_ts, outgoing_ts, processing_samples_ms)
                    next_metrics_emit = now_mono + 1.0
                self.buses.health_bus.put(
                    HealthEvent(self.name, HealthState.READY, heartbeat_unix_ns=time.time_ns())
                )
        finally:
            reader.close()

    def _run_simulation_standby(
        self,
        incoming_ts: deque[float],
        outgoing_ts: deque[float],
        processing_samples_ms: deque[float],
    ) -> None:
        """Keep process healthy in simulation when optional replay data is absent."""
        next_metrics_emit = time.monotonic() + 1.0
        while not self.should_stop():
            now_mono = time.monotonic()
            if now_mono >= next_metrics_emit:
                self._emit_metrics(incoming_ts, outgoing_ts, processing_samples_ms)
                next_metrics_emit = now_mono + 1.0
            self.buses.health_bus.put(
                HealthEvent(self.name, HealthState.READY, heartbeat_unix_ns=time.time_ns())
            )
            time.sleep(0.2)

    def run(self) -> None:
        """Connect MQTT, consume one latest payload at a time, emit contracts."""
        log = logging.getLogger(self.name)
        recorder = None
        if self.cfg.recording.enabled and self.cfg.settings.mode == "record":
            path = f"{self.cfg.settings.data_dir}/{self.stream_id}.hlp2"
            recorder = StreamRecorder(path, compression=self.cfg.recording.compression)

        publish_queue = None
        publisher_service = None
        if self.cfg.zenoh.enabled:
            queue_size = 64
            try:
                queue_size = max(queue_size, int(os.getenv("HOLO_PUBLISHER_ZENOH_QUEUE_SIZE", "0")))
            except Exception:
                pass
            publish_queue = queue.Queue(maxsize=queue_size)
            publisher_service = ZenohPublisherService((self.publish_topic,), publish_queue, self.cfg.zenoh)
            publisher_service.start()

        incoming_ts: deque[float] = deque(maxlen=60)
        outgoing_ts: deque[float] = deque(maxlen=60)
        processing_samples_ms: deque[float] = deque(maxlen=60)
        next_metrics_emit = time.monotonic() + 1.0

        service = None

        self.buses.health_bus.put(HealthEvent(self.name, HealthState.READY, heartbeat_unix_ns=time.time_ns()))

        try:
            if self.cfg.settings.mode == "simulation":
                self._run_simulation(
                    publish_queue=publish_queue,
                    incoming_ts=incoming_ts,
                    outgoing_ts=outgoing_ts,
                    processing_samples_ms=processing_samples_ms,
                )
                return

            service = MqttClientService(
                host=self.cfg.mqtt.host,
                port=self.cfg.mqtt.port,
                username=self.cfg.mqtt.username,
                password=self.cfg.mqtt.password,
            )

            def _callback(_client, _userdata, msg):
                packet_start_mono_ns = time.perf_counter_ns()
                parsed = self.parse_message(msg.payload)
                if parsed is None:
                    return
                incoming_ts.append(time.monotonic())
                self.latest = {"payload": parsed, "start_mono_ns": packet_start_mono_ns}

            service.connect()
            service.subscribe(self.topic, _callback)
            log.info("Subscribed to topic=%s", self.topic)

            while not self.should_stop():
                if self.latest is None:
                    now_mono = time.monotonic()
                    if now_mono >= next_metrics_emit:
                        self._emit_metrics(incoming_ts, outgoing_ts, processing_samples_ms)
                        next_metrics_emit = now_mono + 1.0
                    time.sleep(0.05)
                    continue

                latest_packet = self.latest
                payload_dict = latest_packet["payload"]
                packet_start_ns = int(latest_packet["start_mono_ns"])

                env = self._build_envelope(payload_dict)
                self.seq += 1

                if recorder is not None:
                    recorder.write(env)

                if publish_queue is not None:
                    try:
                        publish_queue.put_nowait((self.publish_topic, env))
                    except queue.Full:
                        emit_metric(
                            self.buses.metrics_bus,
                            self.name,
                            self.stream_id,
                            "zenoh_queue_drops",
                            "counter",
                            1.0,
                        )

                emit_metric(self.buses.metrics_bus, self.name, self.stream_id, "frames_out", "counter", 1.0)
                outgoing_ts.append(time.monotonic())
                processing_samples_ms.append((time.perf_counter_ns() - packet_start_ns) / 1_000_000.0)

                now_mono = time.monotonic()
                if now_mono >= next_metrics_emit:
                    self._emit_metrics(incoming_ts, outgoing_ts, processing_samples_ms)
                    next_metrics_emit = now_mono + 1.0

                self.buses.health_bus.put(HealthEvent(self.name, HealthState.READY, heartbeat_unix_ns=time.time_ns()))
                self.latest = None
        finally:
            if recorder is not None:
                recorder.close()
            if publisher_service is not None:
                publisher_service.stop()
                publisher_service.join(timeout=2.0)
                publisher_service.cleanup()
            if service is not None:
                service.stop()
            self.buses.health_bus.put(HealthEvent(self.name, HealthState.STOPPING, heartbeat_unix_ns=time.time_ns()))

    @staticmethod
    def _calc_fps(ts: deque[float]) -> float:
        """Compute rolling FPS from recent monotonic timestamps."""
        if len(ts) < 2:
            return 0.0
        duration = ts[-1] - ts[0]
        if duration <= 0.0:
            return 0.0
        return (len(ts) - 1) / duration
