"""Session manifest model and writer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SessionManifest:
    """Metadata index describing one recording session."""

    session_id: str
    schema_version: int
    session_start_unix_ns: int
    session_start_mono_ns: int
    streams: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        """Write manifest JSON to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
