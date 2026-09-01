"""Shared inter-process bus declarations."""

from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass


@dataclass
class RuntimeBuses:
    """Container holding all multiprocessing queues used across processes."""

    control_bus: mp.Queue
    metrics_bus: mp.Queue
    health_bus: mp.Queue


def create_buses() -> RuntimeBuses:
    """Create all runtime queues.

    Queues are unbounded by default and intended for control-plane traffic.
    High-rate frame payloads stay in-process and should not be sent on these
    buses.
    """
    return RuntimeBuses(
        control_bus=mp.Queue(),
        metrics_bus=mp.Queue(),
        health_bus=mp.Queue(),
    )
