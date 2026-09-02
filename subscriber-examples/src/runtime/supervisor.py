"""Runtime supervisor for all subscriber worker processes."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, List
from multiprocessing import Queue, Process

from src.utils.config import AppConfig, SensorSpec
from src.handlers.base_subscriber import BaseSubscriberProcess
from src.factory import SubscriberFactory
from src.processes.metrics_aggregator import MetricsAggregatorProcess


@dataclass
class ChildSpec:
    """Supervisor-owned process descriptor with restart metadata."""
    name: str
    proc: object
    restarts: int = 0
    spec: Optional[SensorSpec] = None


class SubscriberSupervisor:
    """Root runtime orchestrator for subscribers.

    Responsibilities:
    - Parse config for required sensors
    - Spawn all subscriber processes (including aux processes like FastAPI)
    - Monitor child liveness and restart with bounded retries
    - Coordinate cooperative shutdown
    """

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.log = logging.getLogger("supervisor")
        self.children: list[ChildSpec] = []
        self._running = False
        self.audio_queue: Optional[Queue] = None
        self.fastapi_process: Optional[Process] = None
        self.metrics_bus = Queue()

    def _build_children(self) -> None:
        """Create the complete runtime graph for subscribers."""
        self.children = []
        
        # Add Metrics Aggregator
        agg_proc = MetricsAggregatorProcess(self.cfg, self.metrics_bus)
        # We wrap it in a ChildSpec without a spec for restarts
        self.children.append(ChildSpec(name="metrics_aggregator", proc=agg_proc, spec=None))

        specs = self.cfg.sensors_all()
        
        if not specs:
            self.log.warning("No subscribers defined in config.")
            return

        has_microphone = any(
            s.name.lower().strip() in ('hololens_microphone', 'microphone', 'hl2_microphone')
            for s in specs
        )

        # Start auxiliary processes first
        if has_microphone:
            from src.utils.fastapi_server import run_fastapi_server
            self.audio_queue = Queue(maxsize=100)
            self.log.info("Created shared audio queue for microphone subscriber")
            self.fastapi_process = Process(
                target=run_fastapi_server, 
                args=(self.audio_queue,),
                daemon=True
            )
            # We don't manage fastapi_process under ChildSpec with restarts for simplicity,
            # but we will start it in _start_all and stop it in stop().
        
        # Build main subscriber children
        for spec in specs:
            try:
                sub = SubscriberFactory.create_subscriber(spec, self.cfg, audio_queue=self.audio_queue)
                if sub is not None:
                    # Inject metrics bus
                    if hasattr(sub, "set_metrics_bus"):
                        sub.set_metrics_bus(self.metrics_bus)
                    child_name = spec.name
                    if spec.params.get("sensor"):
                        child_name = f"{spec.name}:{spec.params.get('sensor')}"
                    self.children.append(ChildSpec(name=child_name, proc=sub, spec=spec))
            except Exception as e:
                self.log.error(f"Could not prepare subscriber '{spec.name}': {e}", exc_info=True)

    def _start_all(self) -> None:
        """Start each configured child process."""
        self._build_children()
        
        if self.fastapi_process:
            self.fastapi_process.start()
            self.log.info(f"Started FastAPI server (PID {self.fastapi_process.pid}) on http://localhost:4000")

        self.log.info(f"Startup plan: {[c.name for c in self.children]}")
        for child in self.children:
            child.proc.start()
            self.log.info("Started subscriber process %s pid=%s", child.name, child.proc.pid)

    def _rebuild_process(self, child: ChildSpec) -> object:
        """Create a fresh process instance for a previously crashed subscriber."""
        if child.name == "metrics_aggregator":
            return MetricsAggregatorProcess(self.cfg, self.metrics_bus)
            
        if child.spec is None:
            raise ValueError(f"Cannot rebuild process {child.name} without a SensorSpec")
        sub = SubscriberFactory.create_subscriber(child.spec, self.cfg, audio_queue=self.audio_queue)
        if hasattr(sub, "set_metrics_bus"):
            sub.set_metrics_bus(self.metrics_bus)
        return sub

    def _maybe_restart(self, child: ChildSpec) -> None:
        """Restart a dead process if it still has remaining retry budget."""
        if child.proc.is_alive():
            return
        
        # In subscriber examples, we might not have a configurable restart max via AppConfig
        # as the publisher did, so we use a hardcoded fallback.
        max_restarts = getattr(self.cfg.runtime, "restart_max_attempts", 5) if hasattr(self.cfg, "runtime") else 5
        backoff_s = getattr(self.cfg.runtime, "restart_backoff_s", 2.0) if hasattr(self.cfg, "runtime") else 2.0

        if child.restarts >= max_restarts:
            self.log.error("Process %s exceeded restart budget. It will not be restarted.", child.name)
            return

        self.log.warning("Restarting process %s (attempt %d)", child.name, child.restarts + 1)
        time.sleep(backoff_s)

        child.proc = self._rebuild_process(child)
        child.restarts += 1
        child.proc.start()

    def run(self) -> None:
        """Main supervision loop."""
        self._running = True
        self._start_all()
        
        supervisor_tick_s = getattr(self.cfg.runtime, "supervisor_tick_s", 1.0) if hasattr(self.cfg, "runtime") else 1.0

        while self._running:
            for child in self.children:
                self._maybe_restart(child)
                
            # If all are unrecoverable or died, we might want to shut down,
            # but for a continuous supervisor, we typically stay alive. 
            time.sleep(supervisor_tick_s)

    def stop(self) -> None:
        """Best-effort cooperative shutdown for all children."""
        self._running = False
        
        # Stop auxiliary process
        if self.fastapi_process and self.fastapi_process.is_alive():
            self.log.info("Stopping FastAPI server...")
            self.fastapi_process.terminate()
            self.fastapi_process.join(timeout=3)
            
        # Signal stop to all subscribers
        for child in self.children:
            try:
                child.proc.stop()
            except Exception:
                self.log.debug("Failed to signal stop for %s", child.name, exc_info=True)

        # Wait for termination
        for child in self.children:
            try:
                child.proc.join(timeout=5.0)
            except Exception:
                self.log.debug("Failed to join %s", child.name, exc_info=True)
