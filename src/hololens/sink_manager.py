"""Generic `hl2ss_mp` sink lifecycle manager.

`HololensSinkManager` owns the shared producer/consumer pair and sink attach/
detach lifecycle. It does not contain sensor-specific receiver details; those
belong to handler implementations in `src/hololens/handlers`.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Any, Iterable

from src.hololens.hl2ss_imports import hl2ss, hl2ss_mp, hl2ss_mx
from src.hololens.handlers.base import HololensHandler


@dataclass(frozen=True)
class SinkRuntimeConfig:
    """Runtime-only sink manager settings shared by all streams."""

    host: str
    buffer_size: int = 150
    start_timeout_s: float = 10.0
    stop_timeout_s: float = 3.0


class HololensSinkManager:
    """Shared `hl2ss_mp` producer/consumer boundary for handler-owned streams."""

    def __init__(self, runtime: SinkRuntimeConfig, handlers: Iterable[HololensHandler]):
        self.runtime = runtime
        self.handlers = list(handlers)
        self.log = logging.getLogger("HololensSinkManager")

        self.producer = None
        self.consumer = None
        self.manager = None

        self._handlers_by_port: dict[int, HololensHandler] = {}
        self._sinks: dict[int, Any] = {}
        self._started_ports: set[int] = set()

    def _port(self, port_name: str) -> int:
        return int(getattr(hl2ss.StreamPort, port_name))

    def _wait_first_buffered(self, sink: Any) -> None:
        """Wait for the first buffered frame so stream consumers can poll safely."""
        if hl2ss_mx is None:
            return
        t0 = time.time()
        while time.time() - t0 < self.runtime.start_timeout_s:
            try:
                status = sink.get_buffered_frame(-1)[0]
                if status == hl2ss_mx.Status.OK:
                    return
            except Exception:
                time.sleep(0.001)
                continue
            time.sleep(0.001)

    def _build_handler_port_map(self) -> None:
        self._handlers_by_port.clear()
        for handler in self.handlers:
            port = self._port(handler.spec.port_name)
            if port in self._handlers_by_port:
                raise ValueError(
                    f"duplicate handler port detected: {handler.spec.port_name} ({port})"
                )
            self._handlers_by_port[port] = handler

    def start(self) -> None:
        """Start shared producer/consumer and attach one sink per configured handler."""
        if not self.handlers:
            self.log.info("No HoloLens handlers enabled; sink manager idle")
            return

        self._build_handler_port_map()

        self.producer = hl2ss_mp.producer()
        self.consumer = hl2ss_mp.consumer()
        self.manager = mp.Manager()

        for handler in self.handlers:
            handler.start_subsystem(self.runtime.host, self.runtime.start_timeout_s)

        for port, handler in sorted(self._handlers_by_port.items()):
            receiver = handler.configure_receiver(self.runtime.host)
            self.producer.configure(port, receiver)

        for port in sorted(self._handlers_by_port):
            self.producer.initialize(port, self.runtime.buffer_size)
            self.producer.start(port)
            sink = self.consumer.create_sink(self.producer, port, self.manager, semaphore=...)
            sink.get_attach_response()
            self._wait_first_buffered(sink)
            self._sinks[port] = sink
            self._started_ports.add(port)

        self.log.info(
            "hl2ss started with streams=%s",
            [handler.spec.stream_id for _, handler in sorted(self._handlers_by_port.items())],
        )

    def stop(self) -> None:
        """Detach sinks, stop ports, and execute handler-specific subsystem shutdown."""
        if self.producer is None:
            return

        for sink in list(self._sinks.values()):
            try:
                sink.detach()
            except Exception:
                self.log.debug("sink detach failed", exc_info=True)

        for port in sorted(self._started_ports):
            try:
                self.producer.stop(port)
            except Exception:
                self.log.debug("producer stop failed for port=%s", port, exc_info=True)

        # Stop subsystems only after ports are torn down.
        for handler in self.handlers:
            try:
                handler.stop_subsystem(self.runtime.host, self.runtime.stop_timeout_s)
            except Exception:
                self.log.debug(
                    "handler subsystem stop failed for stream=%s",
                    handler.spec.stream_id,
                    exc_info=True,
                )

        if self.manager is not None:
            self.manager.shutdown()
            self.manager = None

        self._sinks.clear()
        self._started_ports.clear()
        self._handlers_by_port.clear()
        self.consumer = None
        self.producer = None

    def get_port(self, port_name: str) -> int:
        """Resolve `hl2ss.StreamPort` integer from enum member name."""
        return self._port(port_name)

    def get_sink(self, port: int):
        """Return sink for port if available."""
        return self._sinks.get(port)

    def get_handler(self, port: int) -> HololensHandler | None:
        """Return handler for a configured port."""
        return self._handlers_by_port.get(port)

    def iter_ports(self) -> tuple[int, ...]:
        """Return started ports in deterministic order."""
        return tuple(sorted(self._started_ports))
