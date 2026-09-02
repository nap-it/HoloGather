"""Stream recording reader."""

from __future__ import annotations

from pathlib import Path

import lz4.frame  # type: ignore

from src.contracts.envelope import SensorEnvelope
from src.serialization.record_codec import decode_record


class StreamReader:
    """Sequential reader for one stream recording file."""

    def __init__(self, file_path: str, compression: str = "lz4"):
        self.path = Path(file_path)
        self.fh = self.path.open("rb")
        self.compression = compression

    def read(self) -> SensorEnvelope | None:
        """Read next record from file and decode into envelope."""
        size_b = self.fh.read(4)
        if not size_b or len(size_b) < 4:
            return None
        size = int.from_bytes(size_b, "big")
        blob = self.fh.read(size)
        if self.compression == "lz4":
            blob = lz4.frame.decompress(blob)
        return decode_record(blob)

    def close(self) -> None:
        """Close underlying file handle."""
        self.fh.close()
