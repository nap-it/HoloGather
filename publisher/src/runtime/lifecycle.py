"""Process lifecycle primitives."""

from __future__ import annotations

import multiprocessing as mp


class ManagedProcess(mp.Process):
    """Base process with cooperative stop event.

    Child processes should call `should_stop()` in their loop and exit cleanly
    when it turns true.
    """

    def __init__(self, name: str):
        super().__init__(name=name)
        self._stop_event = mp.Event()

    def stop(self) -> None:
        """Request cooperative process termination."""
        self._stop_event.set()

    def should_stop(self) -> bool:
        """Check whether cooperative stop was requested."""
        return self._stop_event.is_set()
