"""Depth correlator placeholder.

Correlation is intentionally out of the hot path in this refactor. This file is
kept as a dedicated extension point for future multi-stream correlation logic.
"""

from __future__ import annotations


class DepthCorrelatorHandler:
    """Future extension point for depth-to-RGB correlation handlers."""

    def poll(self) -> bytes | None:
        """Return correlated payload bytes when available."""
        return None
