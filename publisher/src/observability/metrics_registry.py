"""In-memory metrics snapshot helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class MetricsSnapshot:
    """Latest metric value per `(service, component, name, type)` tuple."""

    values: Dict[Tuple[str, str, str, str], float] = field(default_factory=dict)

    def set_value(self, service: str, component: str, name: str, typ: str, value: float) -> None:
        """Upsert latest value for one labeled metric key."""
        self.values[(service, component, name, typ)] = value
