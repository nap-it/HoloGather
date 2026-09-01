"""Zenoh publication services.

This module provides a single-session, multi-publisher architecture:
- `ZenohSessionManager` owns one Zenoh session per process.
- `ZenohPublisherService` is one dispatcher thread that consumes `(topic, bytes)`
  events and publishes through publishers declared on the shared session.

When enabled and available, a single SHM provider is also shared for all topics.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Any

from src.config.center import ZenohConfig
from src.contracts.envelope import SensorEnvelope
from src.serialization.zenoh_codec import encode_zenoh

try:
    import zenoh  # type: ignore
except Exception:  # pragma: no cover
    zenoh = None

try:
    import zenoh.shm as zenoh_shm  # type: ignore
except Exception:  # pragma: no cover
    zenoh_shm = None

try:
    import resource  # type: ignore
except Exception:  # pragma: no cover
    resource = None


PublishEvent = tuple[str, bytes | SensorEnvelope]

MIN_SHM_BACKEND_SIZE = 256 * 1024
SHM_USAGE_FRACTION = 0.8


def _pick_shm_backend_size(requested_size: int) -> int:
    """Choose SHM arena size bounded by `/dev/shm` free space and memlock."""
    size = max(int(requested_size), MIN_SHM_BACKEND_SIZE)

    try:
        stat = os.statvfs("/dev/shm")
        free_bytes = stat.f_frsize * stat.f_bavail
        allowed_by_disk = int(free_bytes * SHM_USAGE_FRACTION)
        size = min(size, allowed_by_disk)
    except Exception:
        # Keep requested size if `/dev/shm` probing fails.
        pass

    if resource is not None:
        try:
            soft_limit, _ = resource.getrlimit(resource.RLIMIT_MEMLOCK)
            if soft_limit != resource.RLIM_INFINITY:
                size = min(size, int(soft_limit))
        except Exception:
            pass

    return max(size, MIN_SHM_BACKEND_SIZE)


class ZenohSessionManager:
    """Own one shared Zenoh session and lazily declared topic publishers.

    A process should create exactly one instance. This avoids repeated session
    setup/teardown and keeps transport-level resource overhead low.
    """

    def __init__(self, cfg: ZenohConfig):
        self.cfg = cfg
        self.log = logging.getLogger("ZenohSessionManager")
        self._lock = threading.Lock()

        self.session = None
        self.publishers: dict[str, Any] = {}
        self.shm_provider = None
        self._shm_arena_size = 0

        if zenoh is None:
            self.log.warning("zenoh runtime unavailable, Zenoh session disabled")
            return

        zcfg = zenoh.Config()
        if cfg.config_file:
            zcfg = zenoh.Config.from_file(cfg.config_file)

        self.session = zenoh.open(zcfg)
        self._setup_shm()

    def _setup_shm(self) -> None:
        """Create one SHM provider shared across all publishers in this session."""
        if not self.cfg.use_shm:
            return
        if zenoh is None or zenoh_shm is None:
            self.log.warning("Zenoh SHM requested but `zenoh.shm` is unavailable; using standard put")
            return

        arena_size = _pick_shm_backend_size(self.cfg.shm_arena_size)
        try:
            self.shm_provider = zenoh_shm.ShmProvider.default_backend(arena_size)
            self._shm_arena_size = arena_size
            self.log.info("Zenoh SHM enabled (shared arena=%d bytes)", arena_size)
        except Exception as exc:
            self.log.warning("Failed to initialize Zenoh SHM (%s), using standard put", exc)
            self.shm_provider = None
            self._shm_arena_size = 0

    def ensure_publisher(self, topic: str):
        """Declare and cache a topic publisher if not already present."""
        with self._lock:
            existing = self.publishers.get(topic)
            if existing is not None:
                return existing
            if self.session is None:
                return None
            publisher = self.session.declare_publisher(topic)
            self.publishers[topic] = publisher
            return publisher

    def preload_publishers(self, topics: tuple[str, ...]) -> None:
        """Pre-declare known topics during startup to fail early on errors."""
        for topic in topics:
            self.ensure_publisher(topic)

    def publish(self, topic: str, data: bytes) -> None:
        """Publish bytes to topic using shared SHM provider when possible."""
        publisher = self.ensure_publisher(topic)
        if publisher is None:
            return

        try:
            if self.shm_provider is not None and len(data) <= self._shm_arena_size:
                sbuf = self.shm_provider.alloc(
                    len(data),
                    policy=zenoh_shm.BlockOn(zenoh_shm.GarbageCollect()),
                )
                sbuf[:] = data
                publisher.put(sbuf)
                return
            publisher.put(data)
        except Exception:
            self.log.exception("Failed publishing payload on topic=%s", topic)

    def close(self) -> None:
        """Release topic publishers and close session."""
        with self._lock:
            for topic, publisher in list(self.publishers.items()):
                try:
                    publisher.undeclare()
                except Exception:
                    self.log.debug("publisher undeclare failed for topic=%s", topic, exc_info=True)
            self.publishers.clear()

            if self.session is not None:
                try:
                    self.session.close()
                except Exception:
                    self.log.debug("session close failed", exc_info=True)
                self.session = None

            self.shm_provider = None
            self._shm_arena_size = 0


class ZenohPublisherService(threading.Thread):
    """Single dispatcher thread for multi-topic publishing on one session.

    Input queue items are `(topic, payload_bytes)`. This keeps capture loops
    non-blocking and avoids one thread/session per topic.
    """

    def __init__(self, topics: tuple[str, ...], out_queue, cfg: ZenohConfig):
        super().__init__(daemon=True)
        self.topics = topics
        self.out_queue = out_queue
        self.cfg = cfg
        # Avoid clashing with `threading.Thread._stop()` internal method.
        self._stop_event = threading.Event()
        self.log = logging.getLogger("ZenohPublisherService")
        self.manager = ZenohSessionManager(cfg)

        # Preload publishers so topic declaration issues surface during startup.
        self.manager.preload_publishers(topics)

    def stop(self) -> None:
        """Signal run loop to exit and wake blocking queue reads."""
        self._stop_event.set()
        try:
            self.out_queue.put_nowait(None)
        except queue.Full:
            # If queue is full, run loop will still observe stop on next dequeue.
            pass

    def run(self) -> None:
        """Consume queued publish events and route them through shared session."""
        while not self._stop_event.is_set():
            item = self.out_queue.get(block=True)
            if item is None:
                if self._stop_event.is_set():
                    break
                continue

            topic, payload = item
            if isinstance(payload, SensorEnvelope):
                payload_bytes = encode_zenoh(payload)
            else:
                payload_bytes = payload
            self.manager.publish(topic, payload_bytes)

    def cleanup(self) -> None:
        """Release all Zenoh resources after the thread is stopped."""
        self.manager.close()
