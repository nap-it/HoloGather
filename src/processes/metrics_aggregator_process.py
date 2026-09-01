"""Dedicated metrics consumer process.

Workers emit `MetricEvent` to `metrics_bus`; this process is the only consumer
and exposes Prometheus metrics endpoint.
"""

from __future__ import annotations

import logging
import queue
import time
from collections import defaultdict

from prometheus_client import Counter, Gauge, start_http_server

from src.config.center import AppConfig
from src.contracts.events import MetricEvent
from src.runtime.lifecycle import ManagedProcess


class MetricsAggregatorProcess(ManagedProcess):
    """Consume metric events from bus and expose Prometheus gauges/counters."""

    def __init__(self, cfg: AppConfig, metrics_bus):
        super().__init__(name="Metrics")
        self.cfg = cfg
        self.metrics_bus = metrics_bus
        # Running totals for counter metrics: component -> metric_name -> total.
        self._counter_totals: dict[str, dict[str, float]] = defaultdict(dict)
        # Last observed values for gauge metrics: component -> metric_name -> value.
        self._gauge_values: dict[str, dict[str, float]] = defaultdict(dict)
        # Previous one-second snapshot for rate calculations.
        self._last_counter_snapshot: dict[str, dict[str, float]] = defaultdict(dict)
        self._known_components: set[str] = set()

    def _update_local_stats(self, ev: MetricEvent) -> None:
        """Update process-local per-stream metric aggregates."""
        component = ev.component or "unknown"
        self._known_components.add(component)
        if ev.metric_type.lower() == "counter":
            prev = self._counter_totals[component].get(ev.metric_name, 0.0)
            self._counter_totals[component][ev.metric_name] = prev + float(ev.value)
            return
        self._gauge_values[component][ev.metric_name] = float(ev.value)

    def _print_stream_stats(self, log: logging.Logger) -> None:
        """Print one compact table with all stream stats every second."""
        if not self._known_components:
            return

        rows: list[tuple[str, float, float, float, str]] = []
        for component in sorted(self._known_components):
            totals = self._counter_totals.get(component, {})
            prev = self._last_counter_snapshot.get(component, {})
            deltas: dict[str, float] = {}
            for metric_name, total in totals.items():
                deltas[metric_name] = total - prev.get(metric_name, 0.0)
            self._last_counter_snapshot[component] = dict(totals)

            drops_total = totals.get("zenoh_queue_drops", 0.0)
            drops_rate = deltas.get("zenoh_queue_drops", 0.0)
            gauges = self._gauge_values.get(component, {})
            rows.append(
                (
                    component,
                    float(gauges.get("fps_in", 0.0)),
                    float(gauges.get("fps_out", 0.0)),
                    float(gauges.get("processing_ms", 0.0)),
                    f"{drops_total:.0f} (+{drops_rate:.0f}/s)",
                )
            )

        stream_w = max(16, max(len(r[0]) for r in rows))
        divider = "+" + "-" * (stream_w + 2) + "+" + "-" * 10 + "+" + "-" * 10 + "+" + "-" * 15 + "+" + "-" * 15 + "+"
        header = (
            f"| {'stream name'.ljust(stream_w)} "
            f"| {'in fps'.rjust(8)} "
            f"| {'out fps'.rjust(8)} "
            f"| {'processing ms'.rjust(13)} "
            f"| {'drops'.rjust(13)} |"
        )
        log.info("Stream metrics:")
        log.info(divider)
        log.info(header)
        log.info(divider)
        for stream_name, in_fps, out_fps, proc_ms, drops in rows:
            line = (
                f"| {stream_name.ljust(stream_w)} "
                f"| {in_fps:8.2f} "
                f"| {out_fps:8.2f} "
                f"| {proc_ms:13.2f} "
                f"| {drops.rjust(13)} |"
            )
            log.info(line)
        log.info(divider)

    def run(self) -> None:
        """Run metrics exporter loop until process stop request."""
        log = logging.getLogger(self.name)
        if self.cfg.observability.metrics_enabled:
            start_http_server(self.cfg.observability.metrics_port, addr="127.0.0.1")
            log.info("Prometheus exporter on 127.0.0.1:%d", self.cfg.observability.metrics_port)

        value_g = Gauge("publisher_metric_value", "Last metric value", ["service", "component", "name", "type"])
        count_c = Counter("publisher_metric_events_total", "Metric events received", ["service", "component", "name", "type"])
        next_print_deadline = time.monotonic() + 1.0

        while not self.should_stop():
            try:
                ev = self.metrics_bus.get(timeout=0.2)
            except queue.Empty:
                ev = None

            if isinstance(ev, MetricEvent):
                labels = [ev.service, ev.component, ev.metric_name, ev.metric_type]
                value_g.labels(*labels).set(ev.value)
                count_c.labels(*labels).inc()
                self._update_local_stats(ev)

            now = time.monotonic()
            if now >= next_print_deadline:
                self._print_stream_stats(log)
                next_print_deadline = now + 1.0
