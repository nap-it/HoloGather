"""Session timeline helper."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionClock:
    """Captures session origin in both unix and monotonic time domains."""

    session_start_unix_ns: int
    session_start_mono_ns: int

    @classmethod
    def now(cls) -> "SessionClock":
        """Create a new session clock anchored at current time."""
        return cls(time.time_ns(), time.monotonic_ns())

    def unix_ns(self) -> int:
        """Current unix timestamp in nanoseconds."""
        return time.time_ns()

    def mono_ns(self) -> int:
        """Current monotonic timestamp in nanoseconds."""
        return time.monotonic_ns()

    def mono_delta_ns(self, ts_mono_ns: int) -> int:
        """Delta from session monotonic origin."""
        return ts_mono_ns - self.session_start_mono_ns
