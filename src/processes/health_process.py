"""Dedicated health/readiness process.

This process consumes `HealthEvent` from `health_bus` and serves lightweight
HTTP probes for liveness/readiness checks used by orchestration systems.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.config.center import AppConfig
from src.contracts.events import HealthEvent
from src.observability.health_state import HealthSnapshot
from src.runtime.lifecycle import ManagedProcess


class HealthProcess(ManagedProcess):
    """Single health endpoint owner process."""

    def __init__(self, cfg: AppConfig, health_bus):
        super().__init__(name="HealthProcess")
        self.cfg = cfg
        self.health_bus = health_bus

    def run(self) -> None:
        """Run HTTP health server and consume health events from bus."""
        log = logging.getLogger(self.name)
        snapshot = HealthSnapshot()

        class Handler(BaseHTTPRequestHandler):
            """HTTP handler with closure over process-local health snapshot."""

            def do_GET(self):  # noqa: N802
                if self.path in {"/", "/health"}:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                    return
                if self.path == "/ready":
                    code = 200 if snapshot.is_ready() else 503
                    self.send_response(code)
                    self.end_headers()
                    self.wfile.write(json.dumps({k: v.value for k, v in snapshot.services.items()}).encode("utf-8"))
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, fmt, *args):
                # Keep probe endpoint logs quiet during normal operation.
                return

        if self.cfg.observability.health_enabled:
            server = ThreadingHTTPServer(("127.0.0.1", self.cfg.observability.health_port), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            log.info("Health endpoint on 127.0.0.1:%d", self.cfg.observability.health_port)
        else:
            server = None

        while not self.should_stop():
            try:
                ev = self.health_bus.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(ev, HealthEvent):
                snapshot.update(ev.service, ev.state)

        if server is not None:
            server.shutdown()
