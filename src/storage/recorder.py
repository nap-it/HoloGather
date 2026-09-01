"""Stream recording writer."""

from __future__ import annotations

from pathlib import Path

import lz4.frame  # type: ignore

from src.contracts.envelope import SensorEnvelope
from src.serialization.record_codec import encode_record


class StreamRecorder:
    """Append-only writer for a single logical stream file."""

    def __init__(self, file_path: str, compression: str = "lz4"):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("ab")
        self.compression = compression

    def write(self, env: SensorEnvelope) -> None:
        """Write one framed record; optionally compress each record blob."""
        blob = encode_record(env)
        if self.compression == "lz4":
            blob = lz4.frame.compress(blob)
        self.fh.write(len(blob).to_bytes(4, "big") + blob)

    def close(self) -> None:
        """Close underlying file handle."""
        self.fh.close()
