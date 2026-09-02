"""Shared session anchor + epoch for synchronized multi-stream replay.

The hl2ss streamer (camera/depth/mic) and each MQTT sensor (VAM, phone, heading,
IMU) replay in *separate* processes. For all streams to land on ONE timeline,
every process must map recording time -> replay time with the SAME affine
function ``replay_time(t) = epoch + (t - anchor)``. That requires two values to
be identical across every process:

* ``anchor`` = the earliest ``ts_mono_ns`` across ALL recorded streams. Each
  process derives it deterministically from the same files (no IPC, no races),
  so inter-stream offsets (e.g. the camera starting seconds after the GPS) are
  preserved instead of each stream being zeroed to its own first sample.
* ``epoch``  = one shared monotonic start. We use the run's
  ``session_start_mono_ns`` (identical across child processes, same
  ``CLOCK_MONOTONIC`` on one host) plus a warm-up so every process is inside its
  replay loop before playback begins.

Only the affine *inputs* change; the pacing math in ``ReplayScheduler`` is
unchanged. ``anchor`` is always used as ``env.ts_mono_ns - anchor`` (a delta in
the recording clock), so mixing it with a replay-clock ``epoch`` is correct.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from src.storage.reader import StreamReader

_log = logging.getLogger(__name__)


def _warmup_ns() -> int:
    """Warm-up before playback starts. Generous on purpose: dead time is
    harmless, a process starting *behind* the epoch is not. Tunable via env."""
    try:
        return int(float(os.getenv("HOLO_REPLAY_WARMUP_S", "8")) * 1_000_000_000)
    except (TypeError, ValueError):
        return 8_000_000_000


def _first_env_mono_ns(path: Path, compression: str) -> int | None:
    """Read only the first record's ``ts_mono_ns`` (cheap), with compression
    fallback matching the readers used elsewhere."""
    for comp in (compression, "none"):
        reader = None
        try:
            reader = StreamReader(str(path), compression=comp)
            env = reader.read()
            if env is not None:
                return int(env.ts_mono_ns)
        except Exception:
            continue
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
    return None


def session_replay_anchor_ns(data_dir: Path, compression: str) -> int | None:
    """Earliest ``ts_mono_ns`` across every ``*.hlp2`` stream in ``data_dir``.

    Deterministic across processes (same files -> same value). Returns ``None``
    if nothing is readable, so callers can fall back to their own first event.
    """
    anchors: list[int] = []
    for path in sorted(Path(data_dir).glob("*.hlp2")):
        mono = _first_env_mono_ns(path, compression)
        if mono is not None:
            anchors.append(mono)
    if not anchors:
        _log.warning("No readable .hlp2 streams for replay anchor in %s", data_dir)
        return None
    return min(anchors)


def shared_playback_epoch_ns(session_start_mono_ns: int | None) -> int:
    """Single shared replay epoch in the current run's monotonic clock.

    ``session_start_mono_ns`` is identical across child processes (built once and
    shared via config) and on the same host uses the same ``CLOCK_MONOTONIC`` as
    ``time.monotonic_ns()``.

    CRITICAL: the epoch must never land in the *past*. If it does, the scheduler
    never sleeps and dumps a burst of frames at max speed, overrunning subscriber
    queues (dropped packets, no keyframe, no video). When startup already exceeded
    the warm-up (e.g. slow container start / large-file anchor scan), fall back to
    a small margin from *now* — this costs a little cross-process alignment but
    keeps playback real-time paced, which matters far more.
    """
    base = int(session_start_mono_ns) if session_start_mono_ns else time.monotonic_ns()
    candidate = base + _warmup_ns()
    floor = time.monotonic_ns() + 500_000_000  # never in the past → never bursts
    return max(candidate, floor)
