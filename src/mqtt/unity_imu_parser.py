"""Unity IMU/orientation parser."""

from __future__ import annotations

import json


def parse_unity_imu(payload: bytes) -> dict | None:
    """Parse JSON orientation payload with yaw/pitch/roll floats."""
    try:
        obj = json.loads(payload.decode(errors="ignore").strip())
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if "yaw" not in obj or "pitch" not in obj or "roll" not in obj:
        return None
    try:
        return {
            "yaw": float(obj["yaw"]),
            "pitch": float(obj["pitch"]),
            "roll": float(obj["roll"]),
        }
    except Exception:
        return None
