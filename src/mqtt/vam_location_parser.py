"""VAM location payload parser for MQTT messages."""

from __future__ import annotations

import json


def parse_vam_location(payload: bytes) -> dict | None:
    """Parse latitude/longitude from ETSI VAM-like JSON payload."""
    try:
        doc = json.loads(payload.decode(errors="ignore"))
        vam = doc.get("vamParameters", {})
        ref = vam.get("basicContainer", {}).get("referencePosition", {})
        lat = ref.get("latitude")
        lon = ref.get("longitude")
        if lat is None or lon is None:
            return None
        out = {"latitude": float(lat), "longitude": float(lon)}
        alt = ref.get("altitude")
        if isinstance(alt, dict):
            alt = alt.get("altitudeValue")
        if alt is not None:
            out["altitude"] = float(alt)
        speed = ref.get("speed")
        if isinstance(speed, dict):
            speed = speed.get("speedValue")
        if speed is not None:
            out["speed_mps"] = float(speed)
        # Preserve the ETSI VAM generation time as dataset provenance (the
        # measurement instant, distinct from the Jetson receipt time). NOTE: the
        # receipt time is itself real-time; the growing GPS↔RGB lag once blamed on
        # it was later traced to the RGB video render, not this pipeline.
        # `generationDeltaTime` is ETSI TimestampIts mod 65536 ms. The optional
        # `referenceTime` branch below is defensive — current payloads omit it.
        gdt = doc.get("generationDeltaTime")
        if gdt is None:
            gdt = vam.get("generationDeltaTime")
        if gdt is not None:
            try:
                out["generation_delta_time"] = int(gdt)
            except (TypeError, ValueError):
                pass
        ref_time = doc.get("referenceTime") or doc.get("timestamp")
        if ref_time is not None:
            try:
                # referenceTime is ITS ms since 2004-01-01; store as ns for source_ts
                out["source_ts_ns"] = int(float(ref_time) * 1e6)
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return None
