"""Phone location payload parser for OwnTracks MQTT messages."""

from __future__ import annotations

import json


def parse_phone_location(payload: bytes) -> dict | None:
    """Parse OwnTracks payload keys: lat, lon, alt, vel."""
    try:
        location = json.loads(payload.decode(errors="ignore"))
    except json.JSONDecodeError:
        return None
    except Exception:
        return None

    if "lat" not in location or "lon" not in location:
        return None

    out: dict[str, float] = {
        "latitude": float(location["lat"]),
        "longitude": float(location["lon"]),
    }
    if "alt" in location:
        out["altitude"] = float(location["alt"])
    if "vel" in location:
        out["speed_mps"] = float(location["vel"])
    # Preserve the OwnTracks measurement timestamp (`tst`, Unix epoch seconds) as
    # nanoseconds — the time of the actual GPS fix, kept as dataset provenance
    # alongside the Jetson receipt time (`ts_unix_ns`). NOTE: the receipt time is
    # itself real-time; the growing GPS↔RGB lag once blamed on it was later traced
    # to the RGB video render, not this pipeline. `tst` is 1-second resolution.
    tst = location.get("tst")
    if tst is not None:
        try:
            out["source_ts_ns"] = int(float(tst) * 1e9)
        except (TypeError, ValueError):
            pass
    return out
