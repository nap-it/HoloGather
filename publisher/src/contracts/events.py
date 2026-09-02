"""Control-plane event contracts exchanged through shared buses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from src.contracts.types import ControlAction, HealthState


@dataclass(frozen=True)
class ControlEvent:
    """Supervisor-to-worker control message."""

    target: str
    action: ControlAction
    reason: str = ""


@dataclass(frozen=True)
class MetricEvent:
    """Worker-emitted metric observation sent to metrics process."""

    service: str
    component: str
    metric_name: str
    metric_type: str
    value: float
    labels: Mapping[str, str] = field(default_factory=dict)
    ts_unix_ns: int = 0


@dataclass(frozen=True)
class HealthEvent:
    """Worker-emitted health status heartbeat/event."""

    service: str
    state: HealthState
    detail: str = ""
    heartbeat_unix_ns: int = 0
