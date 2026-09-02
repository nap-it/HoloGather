"""Runtime supervisor for all publisher worker processes."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from src.config.center import AppConfig
from src.processes.health_process import HealthProcess
from src.processes.hololens_streamer_process import HololensStreamerProcess
from src.processes.metrics_aggregator_process import MetricsAggregatorProcess
from src.processes.phone_location_sensor_process import PhoneLocationSensorProcess
from src.processes.unity_heading_sensor_process import UnityHeadingSensorProcess
from src.processes.unity_imu_sensor_process import UnityImuSensorProcess
from src.processes.vam_location_sensor_process import VamLocationSensorProcess
from src.runtime.buses import RuntimeBuses, create_buses


@dataclass
class ChildSpec:
    """Supervisor-owned process descriptor with restart metadata."""

    name: str
    proc: object
    restarts: int = 0


class PublisherSupervisor:
    """Root runtime orchestrator.

    Responsibilities:
    - build shared buses
    - spawn all worker processes
    - monitor child liveness and restart with bounded retries
    - coordinate cooperative shutdown
    """

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.log = logging.getLogger("supervisor")
        self.buses: RuntimeBuses = create_buses()
        self.children: list[ChildSpec] = []
        self._running = False

    def _build_children(self) -> None:
        """Create the complete runtime graph in dependency-safe order."""
        self.children = []
        if self.cfg.observability.metrics_enabled:
            self.children.append(
                ChildSpec(
                    name="metrics",
                    proc=MetricsAggregatorProcess(self.cfg, self.buses.metrics_bus),
                )
            )
        if self.cfg.observability.health_enabled:
            self.children.append(
                ChildSpec(
                    name="health",
                    proc=HealthProcess(self.cfg, self.buses.health_bus),
                )
            )
        if self.cfg.hololens.enabled:
            self.children.append(
                ChildSpec(
                    name="hololens",
                    proc=HololensStreamerProcess(self.cfg, self.buses),
                )
            )
        if self.cfg.mqtt.enabled and self.cfg.mqtt.vam_location_enabled:
            self.children.append(
                ChildSpec(
                    name="vam_location",
                    proc=VamLocationSensorProcess(self.cfg, self.buses),
                )
            )
        if self.cfg.mqtt.enabled and self.cfg.mqtt.phone_location_enabled:
            self.children.append(
                ChildSpec(
                    name="phone_location",
                    proc=PhoneLocationSensorProcess(self.cfg, self.buses),
                )
            )
        if self.cfg.mqtt.enabled and self.cfg.mqtt.heading_enabled:
            self.children.append(
                ChildSpec(
                    name="unity_heading",
                    proc=UnityHeadingSensorProcess(self.cfg, self.buses),
                )
            )
        if self.cfg.mqtt.enabled and self.cfg.mqtt.orientation_enabled:
            self.children.append(
                ChildSpec(
                    name="unity_imu",
                    proc=UnityImuSensorProcess(self.cfg, self.buses),
                )
            )

    def _log_start_plan(self) -> None:
        """Print a formatted startup plan with enabled/disabled services."""
        plan = [
            (
                "metrics",
                self.cfg.observability.metrics_enabled,
                f"port={self.cfg.observability.metrics_port}",
            ),
            (
                "health",
                self.cfg.observability.health_enabled,
                f"port={self.cfg.observability.health_port}",
            ),
            (
                "hololens",
                self.cfg.hololens.enabled,
                f"address={self.cfg.hololens.address} sensors={list(self.cfg.hololens.sensors)}",
            ),
            (
                "vam_location",
                self.cfg.mqtt.enabled and self.cfg.mqtt.vam_location_enabled,
                f"mqtt={self.cfg.mqtt.host}:{self.cfg.mqtt.port} topic={self.cfg.mqtt.vam_location_topic}",
            ),
            (
                "phone_location",
                self.cfg.mqtt.enabled and self.cfg.mqtt.phone_location_enabled,
                f"mqtt={self.cfg.mqtt.host}:{self.cfg.mqtt.port} topic={self.cfg.mqtt.phone_location_topic_owntrack}",
            ),
            (
                "unity_heading",
                self.cfg.mqtt.enabled and self.cfg.mqtt.heading_enabled,
                f"mqtt={self.cfg.mqtt.host}:{self.cfg.mqtt.port} topic={self.cfg.mqtt.heading_topic}",
            ),
            (
                "unity_imu",
                self.cfg.mqtt.enabled and self.cfg.mqtt.orientation_enabled,
                f"mqtt={self.cfg.mqtt.host}:{self.cfg.mqtt.port} topic={self.cfg.mqtt.orientation_topic}",
            ),
        ]
        self.log.info("Startup service plan:")
        for name, enabled, settings in plan:
            state = "START" if enabled else "SKIP"
            self.log.info(" - [%s] %-13s %s", state, name, settings)

    def _start_all(self) -> None:
        """Start each configured child process."""
        self._build_children()
        self._log_start_plan()
        for child in self.children:
            child.proc.start()
            self.log.info("Started process %s pid=%s", child.name, child.proc.pid)

    def _rebuild_process(self, name: str):
        """Create a fresh process instance by child name."""
        if name == "metrics":
            return MetricsAggregatorProcess(self.cfg, self.buses.metrics_bus)
        if name == "health":
            return HealthProcess(self.cfg, self.buses.health_bus)
        if name == "hololens":
            return HololensStreamerProcess(self.cfg, self.buses)
        if name == "vam_location":
            return VamLocationSensorProcess(self.cfg, self.buses)
        if name == "phone_location":
            return PhoneLocationSensorProcess(self.cfg, self.buses)
        if name == "unity_heading":
            return UnityHeadingSensorProcess(self.cfg, self.buses)
        if name == "unity_imu":
            return UnityImuSensorProcess(self.cfg, self.buses)
        raise ValueError(f"Unknown child process name: {name}")

    def _maybe_restart(self, child: ChildSpec) -> None:
        """Restart a dead process if it still has remaining retry budget."""
        if child.proc.is_alive():
            return
        if child.restarts >= self.cfg.runtime.restart_max_attempts:
            self.log.error("Process %s exceeded restart budget", child.name)
            return

        self.log.warning("Restarting process %s (attempt %d)", child.name, child.restarts + 1)
        time.sleep(self.cfg.runtime.restart_backoff_s)

        # Rebuild child from scratch to avoid stale state and inherited failures.
        child.proc = self._rebuild_process(child.name)
        child.restarts += 1
        child.proc.start()

    def run(self) -> None:
        """Main supervision loop."""
        self._running = True
        self._start_all()
        while self._running:
            for child in self.children:
                self._maybe_restart(child)
            time.sleep(self.cfg.runtime.supervisor_tick_s)

    def stop(self) -> None:
        """Best-effort cooperative shutdown for all children."""
        self._running = False
        for child in self.children:
            try:
                child.proc.stop()
            except Exception:
                self.log.debug("Failed to signal stop for %s", child.name, exc_info=True)

        for child in self.children:
            try:
                child.proc.join(timeout=5.0)
            except Exception:
                self.log.debug("Failed to join %s", child.name, exc_info=True)
