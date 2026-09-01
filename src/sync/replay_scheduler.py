"""Replay pacing scheduler based on monotonic deltas."""

from __future__ import annotations

import time

from src.contracts.envelope import SensorEnvelope


class ReplayScheduler:
    """Replays events preserving relative monotonic timing between frames."""

    def __init__(self, playback_start_mono_ns: int, first_event_mono_ns: int):
        self.playback_start_mono_ns = playback_start_mono_ns
        self.first_event_mono_ns = first_event_mono_ns

    def wait_until(self, env: SensorEnvelope) -> None:
        """Sleep until event's target replay time."""
        delta = env.ts_mono_ns - self.first_event_mono_ns
        target = self.playback_start_mono_ns + delta
        now = time.monotonic_ns()
        if target > now:
            time.sleep((target - now) / 1_000_000_000.0)
