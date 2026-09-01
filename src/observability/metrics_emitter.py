"""Helpers for emitting metric events to the shared metrics bus."""

from __future__ import annotations

import time
from multiprocessing import Queue

from src.contracts.events import MetricEvent


def emit_metric(
    queue: Queue,
    service: str,
    component: str,
    metric_name: str,
    metric_type: str,
    value: float,
    labels: dict[str, str] | None = None,
) -> None:
    """Emit one metric event to the shared metrics bus.

    This function intentionally stays tiny so worker processes can call it
    from hot paths without pulling in collector-specific dependencies.
    """
    queue.put(
        MetricEvent(
            service=service,
            component=component,
            metric_name=metric_name,
            metric_type=metric_type,
            value=value,
            labels=labels or {},
            ts_unix_ns=time.time_ns(),
        )
    )
