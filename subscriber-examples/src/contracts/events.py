"""Event models used across process boundaries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricEvent:
    """A single metric reading to be aggregated via the metrics bus."""
    service: str
    component: str
    metric_name: str
    metric_type: str  # e.g., 'counter', 'gauge'
    value: float
    labels: dict[str, str]
    ts_unix_ns: int
