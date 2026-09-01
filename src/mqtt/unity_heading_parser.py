"""Unity heading parser."""

from __future__ import annotations

def parse_heading(payload: bytes) -> dict | None:
    """Parse heading payload where body is a numeric string."""
    try:
        return {"heading": float(payload.decode(errors="ignore").strip())}
    except Exception:
        return None
