#!/usr/bin/env python3
"""
Extract GPS, heading, and frame-timestamp data from the HLP2 recordings and
write one JSON per recording (keyed by its id) plus an index.json catalogue
into data/. The dashboard pages build themselves from these files.

Usage:
    python3 scripts/extract_dashboard_data.py [--recordings <dir>]

Outputs:
    data/<recording_id>.json   (one per recording)
    data/index.json            (catalogue, newest first)
"""

import argparse
import json
import math
import struct
from datetime import datetime
from pathlib import Path

import msgpack

# ── HLP2 constants (mirrors validate_recordings.py) ──────────────────────────
_MAGIC        = b"HLP2"
_PRELUDE_FMT  = ">4sII"
_PRELUDE_SIZE = struct.calcsize(_PRELUDE_FMT)

ROOT        = Path(__file__).resolve().parent.parent
DASHBOARD   = ROOT / "data"


def _recordings_path() -> Path:
    """Recordings folder from config.json's `recordings_path` (relative paths are
    resolved against the repo root). This is where the .hlp2 streams and the
    generated validation_*.mp4 videos live — kept outside the repo."""
    cfg = ROOT / "config.json"
    raw = "../publisher/recordings"
    if cfg.exists():
        try:
            raw = json.loads(cfg.read_text()).get("recordings_path", raw)
        except Exception:
            pass
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p).resolve()


RECORDINGS  = _recordings_path()


# ── HLP2 reader ───────────────────────────────────────────────────────────────

def iter_hlp2(path: Path):
    """Yield (ts_unix_ns, payload_bytes) for every record."""
    with open(path, "rb") as fh:
        while True:
            size_b = fh.read(4)
            if len(size_b) < 4:
                break
            size = int.from_bytes(size_b, "big")
            blob = fh.read(size)
            if len(blob) < size:
                break
            magic, header_len, payload_len = struct.unpack(_PRELUDE_FMT, blob[:_PRELUDE_SIZE])
            if magic != _MAGIC:
                break
            header  = msgpack.unpackb(
                blob[_PRELUDE_SIZE:_PRELUDE_SIZE + header_len], raw=False
            )
            payload = blob[_PRELUDE_SIZE + header_len:_PRELUDE_SIZE + header_len + payload_len]
            yield int(header["ts_unix_ns"]), payload


def iter_ts_only(path: Path):
    """Yield only ts_unix_ns values (fast, skips payload bytes)."""
    with open(path, "rb") as fh:
        while True:
            size_b = fh.read(4)
            if len(size_b) < 4:
                break
            _ = int.from_bytes(size_b, "big")  # advance past size prefix
            prelude = fh.read(_PRELUDE_SIZE)
            if len(prelude) < _PRELUDE_SIZE:
                break
            magic, header_len, payload_len = struct.unpack(_PRELUDE_FMT, prelude)
            if magic != _MAGIC:
                break
            header = msgpack.unpackb(fh.read(header_len), raw=False)
            fh.seek(payload_len, 1)
            yield int(header["ts_unix_ns"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def decode_msgpack_payload(payload: bytes) -> dict | None:
    """Decode a msgpack-encoded payload dict (MQTT streams)."""
    try:
        return msgpack.unpackb(payload, raw=False)
    except Exception:
        return None


def fix_etsi_coords(lat: float, lon: float) -> tuple[float, float]:
    """
    ETSI ITS uses 1/10 microdegrees (10^-7 degrees). If the raw value is
    outside [-90, 90] / [-180, 180], divide by 10^7 to convert to degrees.
    """
    if abs(lat) > 90:
        lat /= 1e7
    if abs(lon) > 180:
        lon /= 1e7
    return lat, lon


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distance in metres between two WGS-84 coordinates."""
    R = 6_371_000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_vam_gaps(vam_points: list, total_duration_s: float, gap_thresh_s: float = 30.0) -> list:
    """
    Return [[t_start, t_end], ...] for segments with no VAM data.
    Covers the pre-start gap (GPS fix delay) and the post-end gap (shutdown).
    """
    gaps = []
    if not vam_points:
        return [[0, total_duration_s]]

    first_t = vam_points[0][2]
    if first_t > gap_thresh_s:
        gaps.append([0.0, round(first_t, 2)])

    for i in range(len(vam_points) - 1):
        dt = vam_points[i + 1][2] - vam_points[i][2]
        if dt > gap_thresh_s:
            gaps.append([round(vam_points[i][2], 2), round(vam_points[i + 1][2], 2)])

    last_t = vam_points[-1][2]
    if total_duration_s - last_t > gap_thresh_s:
        gaps.append([round(last_t, 2), round(total_duration_s, 2)])

    return gaps


def downsample(lst: list, every_n: int) -> list:
    """Keep every n-th element plus the last."""
    result = lst[::every_n]
    if lst and result[-1] != lst[-1]:
        result.append(lst[-1])
    return result


# ── Per-stream extractors ─────────────────────────────────────────────────────

# ETSI ITS epoch: 2004-01-01 00:00:00 UTC = 1072915200 s Unix. TimestampIts (and
# thus VAM generationDeltaTime = TimestampIts mod 65536 ms) counts ms from here.
_ITS_EPOCH_MS = 1072915200000
_ITS_WRAP     = 65536


def _unwrap_vam_ts(receipt_ns: int, gen_delta_ms: int) -> int:
    """
    Recover the absolute VAM generation time (ns) from the 16-bit
    `generationDeltaTime` using the receipt time as a coarse reference.
    Validated on real data: residual latency ~30 ms, so this reconstructs the
    true generation instant to millisecond precision.
    """
    recv_ms    = receipt_ns / 1e6
    its_recv   = recv_ms - _ITS_EPOCH_MS
    latency_ms = (its_recv - gen_delta_ms) % _ITS_WRAP
    return int(round((recv_ms - latency_ms) * 1e6))


def _event_ts(d: dict, receipt_ts: int) -> int:
    """
    Prefer the true source time over the Jetson receipt time:
      1. `source_ts_ns` — OwnTracks `tst` (phone GPS fix time), preserved by the
         parser. Removes the phone pipeline's variable 0.09–42 s latency.
      2. `generation_delta_time` — VAM generation time, unwrapped to absolute.
      3. receipt time — fallback for older recordings lacking both.
    """
    src = d.get("source_ts_ns")
    try:
        if src:
            return int(src)
    except (TypeError, ValueError):
        pass
    gdt = d.get("generation_delta_time")
    try:
        if gdt is not None:
            return _unwrap_vam_ts(receipt_ts, int(gdt))
    except (TypeError, ValueError):
        pass
    return receipt_ts


def extract_vam(path: Path, start_ts: int) -> list:
    """→ [[lat, lon, t_s], ...] — ETSI unavailable values (lat=90, lon=180) filtered out."""
    points = []
    for ts, payload in iter_hlp2(path):
        d = decode_msgpack_payload(payload)
        if d is None:
            continue
        lat = d.get("latitude")
        lon = d.get("longitude")
        if lat is None or lon is None:
            continue
        lat, lon = fix_etsi_coords(float(lat), float(lon))
        # Skip ETSI "unavailable" sentinel (lat=90, lon=180) and any implausible fix
        if abs(lat) >= 89.9 or abs(lon) >= 179.9:
            continue
        t = (_event_ts(d, ts) - start_ts) / 1e9
        points.append([round(lat, 7), round(lon, 7), round(t, 3)])
    return points


def extract_phone(path: Path, start_ts: int) -> list:
    """→ [[lat, lon, t_s], ...]"""
    points = []
    for ts, payload in iter_hlp2(path):
        d = decode_msgpack_payload(payload)
        if d is None:
            continue
        lat = d.get("latitude")
        lon = d.get("longitude")
        if lat is None or lon is None:
            continue
        t = (_event_ts(d, ts) - start_ts) / 1e9
        points.append([round(float(lat), 7), round(float(lon), 7), round(t, 3)])
    return points


def extract_heading(path: Path, start_ts: int, every_n: int = 10) -> list:
    """→ [[t_s, degrees], ...] downsampled."""
    raw = []
    for ts, payload in iter_hlp2(path):
        d = decode_msgpack_payload(payload)
        if d is None:
            continue
        h = d.get("heading")
        if h is None:
            continue
        t = (ts - start_ts) / 1e9
        raw.append([round(t, 3), round(float(h), 2)])
    return downsample(raw, every_n)


def _wrap180(a: float) -> float:
    """Wrap degrees to (-180, 180]."""
    return ((a + 180.0) % 360.0) - 180.0


def extract_imu(path: Path, start_ts: int, every_n: int = 5) -> list:
    """→ [[t_s, pitch, roll], ...] downsampled, angles wrapped to (-180, 180].
    From unity_imu (pitch = look up/down, roll = head tilt)."""
    raw = []
    for ts, payload in iter_hlp2(path):
        d = decode_msgpack_payload(payload)
        if d is None or "pitch" not in d or "roll" not in d:
            continue
        t = (ts - start_ts) / 1e9
        raw.append([round(t, 3), round(_wrap180(float(d["pitch"])), 2),
                    round(_wrap180(float(d["roll"])), 2)])
    return downsample(raw, every_n)


def extract_frame_ts(path: Path, start_ts: int, every_n: int = 30) -> tuple[list, list]:
    """
    Return (full_ts, downsampled_ts) where full_ts has every frame timestamp
    (used for accurate drop-rate calculation) and downsampled_ts keeps every
    every_n-th entry (smaller JSON payload for the dashboard).
    """
    raw = []
    for ts in iter_ts_only(path):
        raw.append(round((ts - start_ts) / 1e9, 4))
    return raw, downsample(raw, every_n)


# ── Drop rate per trajectory segment ─────────────────────────────────────────

def compute_drop_rate(vam_points: list, full_frame_ts: list,
                      nominal_fps: float = 30.0, window_s: float = 10.0) -> list:
    """
    For each VAM GPS point, compute the RGB frame drop rate in a ±window_s/2
    window. Uses the full (non-downsampled) frame timestamp list for accuracy.
    Returns [[lat, lon, t_s, drop_rate], ...] with drop_rate in [0, 1].
    """
    if not full_frame_ts or not vam_points:
        return [[p[0], p[1], p[2], 0.0] for p in vam_points]

    result = []
    for lat, lon, t in vam_points:
        t0 = t - window_s / 2
        t1 = t + window_s / 2
        actual   = sum(1 for ft in full_frame_ts if t0 <= ft <= t1)
        expected = nominal_fps * (t1 - t0)
        rate     = max(0.0, 1.0 - actual / expected) if expected > 0 else 0.0
        result.append([lat, lon, round(t, 3), round(rate, 3)])
    return result


# ── Helpers for extract_run ───────────────────────────────────────────────────

def _session_bounds(files: dict) -> tuple[int, int, dict]:
    """
    Return (start_ts, last_ts, first_ts_per_stream).
    start_ts = earliest first timestamp across all files.
    last_ts  = latest last timestamp across all files.
    """
    first_ts: dict = {}
    last_ts_vals: list = []

    for name, p in files.items():
        if not p.exists():
            continue
        all_ts = list(iter_ts_only(p))
        if all_ts:
            first_ts[name] = all_ts[0]
            last_ts_vals.append(all_ts[-1])

    if not first_ts:
        raise RuntimeError("No readable HLP2 files found")

    return min(first_ts.values()), max(last_ts_vals), first_ts


def _gps_bearing(la1: float, lo1: float, la2: float, lo2: float) -> float:
    """Forward azimuth (degrees, 0–360) from point 1 to point 2."""
    import math
    dlon = math.radians(lo2 - lo1)
    la1r, la2r = math.radians(la1), math.radians(la2)
    x = math.sin(dlon) * math.cos(la2r)
    y = math.cos(la1r) * math.sin(la2r) - math.sin(la1r) * math.cos(la2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _interp_heading(hdg_pts: list, t: float) -> float:
    """Linear heading interpolation with shortest-path angular blending."""
    if not hdg_pts or t <= hdg_pts[0][0]:
        return hdg_pts[0][1] if hdg_pts else 0.0
    if t >= hdg_pts[-1][0]:
        return hdg_pts[-1][1]
    for i in range(len(hdg_pts) - 1):
        ta, ha = hdg_pts[i]; tb, hb = hdg_pts[i + 1]
        if ta <= t <= tb:
            return ha + (((hb - ha + 540) % 360) - 180) * (t - ta) / (tb - ta)
    return 0.0


def _heading_offset(vam_pts: list, phone_pts: list, hdg_pts: list) -> float:
    """
    Estimate the constant calibration offset (degrees) to add to the recorded
    heading so it matches the GPS direction of travel. Uses the denser GPS
    track and averages (GPS bearing − recorded heading) over up to 200 steps.
    """
    import math
    track = phone_pts if len(phone_pts) > len(vam_pts) else vam_pts
    diffs = []
    for i in range(1, min(len(track), 200)):
        la1, lo1, t1 = track[i - 1]; la2, lo2, t2 = track[i]
        dist = 6_371_000 * math.sqrt(
            math.radians(la2 - la1) ** 2
            + (math.radians(lo2 - lo1) * math.cos(math.radians(la1))) ** 2
        )
        if dist < 1.0:
            continue
        move_b = _gps_bearing(la1, lo1, la2, lo2)
        rec_h  = _interp_heading(hdg_pts, (t1 + t2) / 2)
        diffs.append(((move_b - rec_h + 540) % 360) - 180)
    return round(sum(diffs) / len(diffs), 1) if diffs else 0.0


def _video_paths(run_dir: Path) -> tuple[str, str]:
    """Return the URL under which the server exposes each validation video
    (/recordings/<dir>/validation_*.mp4 — serve_dashboard.py maps /recordings/ to
    the configured recordings folder), or "" when a video is not present yet."""
    def url(name: str) -> str:
        return f"/recordings/{run_dir.name}/{name}" if (run_dir / name).exists() else ""

    return url("validation_rgb.mp4"), url("validation_depth.mp4")


# ── Main extraction per run ───────────────────────────────────────────────────

def extract_run(run_dir: Path) -> dict:
    """Extract all dashboard data for one recording, keyed by its recording id."""
    print(f"\n  {run_dir.name}")

    files = {
        "vam":    run_dir / "vam_location_1.hlp2",
        "phone":  run_dir / "phone_location_1.hlp2",
        "hdg":    run_dir / "unity_heading_1.hlp2",
        "imu":    run_dir / "unity_imu_1.hlp2",
        "camera": run_dir / "HololensCamera_1.hlp2",
    }
    for name, p in files.items():
        if not p.exists():
            print(f"    WARNING: {p.name} not found")

    start_ts, last_ts, first_ts_per = _session_bounds(files)
    duration_s     = (last_ts - start_ts) / 1e9
    video_offset_s = (first_ts_per.get("camera", start_ts) - start_ts) / 1e9
    print(f"    duration: {duration_s:.1f}s  video_offset: {video_offset_s:.2f}s")

    vam_pts   = extract_vam(files["vam"],   start_ts) if files["vam"].exists()   else []
    phone_pts = extract_phone(files["phone"], start_ts) if files["phone"].exists() else []
    hdg_pts   = extract_heading(files["hdg"], start_ts) if files["hdg"].exists()  else []
    imu_pts   = extract_imu(files["imu"],   start_ts) if files["imu"].exists()   else []

    # Optional offset-corrected heading stream (unity_heading_1_offset.hlp2), when
    # present, so the dashboard can switch between the original and corrected data.
    hdg_corr_file = run_dir / "unity_heading_1_offset.hlp2"
    hdg_corr_pts  = extract_heading(hdg_corr_file, start_ts) if hdg_corr_file.exists() else []
    if hdg_corr_pts:
        print(f"    heading (corrected) stream: {len(hdg_corr_pts)} pts")

    full_frame_ts, ds_frame_ts = (
        extract_frame_ts(files["camera"], start_ts)
        if files["camera"].exists() else ([], [])
    )
    print(f"    vam={len(vam_pts)} phone={len(phone_pts)} "
          f"heading={len(hdg_pts)} frames={len(full_frame_ts)}(→{len(ds_frame_ts)})")

    hdg_off = _heading_offset(vam_pts, phone_pts, hdg_pts)
    print(f"    heading_offset: {hdg_off:+.1f}°")

    ts_str = run_dir.name.replace("hololens_recording_", "")
    date   = f"{ts_str[:4]}-{ts_str[4:6]}-{ts_str[6:8]}"
    clock  = f"{ts_str[9:11]}:{ts_str[11:13]}" if len(ts_str) >= 13 else ""
    rgb_rel, depth_rel = _video_paths(run_dir)

    return {
        "id":             ts_str,
        "label":          f"{date} {clock}".strip(),
        "date":           date,
        "dir":            run_dir.name,
        "duration":       round(duration_s, 2),
        "start_ts_ns":    start_ts,
        "video_offset_s": round(video_offset_s, 3),
        "rgb_video":      rgb_rel,
        "depth_video":    depth_rel,
        "vam":            vam_pts,
        "phone":          phone_pts,
        "hdg":            hdg_pts,
        "hdg_corr":       hdg_corr_pts,
        "imu":            imu_pts,
        "vam_gaps":       find_vam_gaps(vam_pts, duration_s),
        "vam_with_drops": compute_drop_rate(vam_pts, full_frame_ts),
        "frame_ts":       ds_frame_ts,
        "heading_offset": hdg_off,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract HLP2 data for the dashboard")
    parser.add_argument(
        "--recordings", type=Path, default=RECORDINGS,
        help="Path to the recordings directory (default: %(default)s)",
    )
    args = parser.parse_args()

    recordings_dir: Path = args.recordings
    if not recordings_dir.is_dir():
        print(f"Error: recordings directory not found: {recordings_dir}")
        raise SystemExit(1)

    # Find and sort recording folders
    run_dirs = sorted(
        [d for d in recordings_dir.iterdir()
         if d.is_dir() and d.name.startswith("hololens_recording_")]
    )
    if not run_dirs:
        print(f"No hololens_recording_* directories found in {recordings_dir}")
        raise SystemExit(1)

    print(f"Found {len(run_dirs)} recording(s) in {recordings_dir}")

    DASHBOARD.mkdir(parents=True, exist_ok=True)

    index: list[dict] = []
    for run_dir in run_dirs:
        try:
            data = extract_run(run_dir)
            out  = DASHBOARD / f"{data['id']}.json"
            out.write_text(json.dumps(data, separators=(",", ":")))
            size_kb = out.stat().st_size // 1024
            print(f"    → {out.relative_to(ROOT)}  ({size_kb} KB)")
            # One compact entry per recording; the dashboard builds itself from this.
            index.append({
                "id":        data["id"],
                "label":     data["label"],
                "date":      data["date"],
                "dir":       data["dir"],
                "duration":  data["duration"],
                "has_rgb":   bool(data["rgb_video"]),
                "has_depth": bool(data["depth_video"]),
                "has_hdg_corr": bool(data["hdg_corr"]),
                "counts":    {"vam": len(data["vam"]), "phone": len(data["phone"]),
                              "hdg": len(data["hdg"])},
            })
        except Exception as exc:
            print(f"    ERROR: {exc}")

    # Newest first — the index page and the page's picker both read this.
    index.sort(key=lambda r: r["id"], reverse=True)
    idx_path = DASHBOARD / "index.json"
    idx_path.write_text(json.dumps(
        {"generated": datetime.now().isoformat(timespec="seconds"), "runs": index},
        separators=(",", ":")))
    print(f"\n  → {idx_path.relative_to(ROOT)}  ({len(index)} recording(s))")

    # Drop stale files from the old run{n}.json scheme / deleted recordings.
    keep = {f"{r['id']}.json" for r in index} | {"index.json"}
    for old in DASHBOARD.glob("*.json"):
        if old.name not in keep:
            old.unlink()
            print(f"  removed stale {old.name}")

    print("\nDone. Open the dashboard with:\n  python3 scripts/serve_dashboard.py\n")


if __name__ == "__main__":
    main()
