"""In-memory health state snapshot model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from src.contracts.types import HealthState


@dataclass
class HealthSnapshot:
    """In-memory snapshot used by the health endpoint process."""

    services: Dict[str, HealthState] = field(default_factory=dict)

    def update(self, service: str, state: HealthState) -> None:
        """Set latest known health state for one service."""
        self.services[service] = state

    def is_ready(self) -> bool:
        """Readiness = all known services are READY and at least one exists."""
        return bool(self.services) and all(v == HealthState.READY for v in self.services.values())
