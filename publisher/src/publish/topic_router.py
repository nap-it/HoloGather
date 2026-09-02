"""Topic routing helpers for canonical envelopes."""

from __future__ import annotations

from src.contracts.envelope import SensorEnvelope


def route_topic(env: SensorEnvelope) -> str:
    """Build default topic path from canonical envelope fields."""
    return f"hololens/{env.sensor_type.value}"
