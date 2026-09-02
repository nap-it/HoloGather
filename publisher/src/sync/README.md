# src/sync — replay pacing & cross-stream synchronization

Drives **simulation mode**: replaying recorded `.hlp2` streams ([`../storage`](../storage))
back onto Zenoh at real-time speed, with every stream on one shared timeline.

## Files
- **`replay_scheduler.py`** — `ReplayScheduler`: paces events by their monotonic
  deltas (`target = playback_start + (event.ts_mono − first_event)`), sleeping
  until each event's real-time instant.
- **`replay_anchor.py`** — makes replay synchronized **across processes**: a
  session-wide anchor (earliest sample over *all* streams) and a shared playback
  epoch, so per-stream offsets (e.g. camera starting seconds after GPS) are
  preserved instead of each stream being zeroed to its own start. The epoch is
  guarded to never land in the past (which would burst frames).
- **`session_clock.py`** — the session start reference (`session_start_mono_ns`)
  shared via config to all processes.

## Why it matters
Each stream replays in its own process; without a shared anchor + epoch they
drift apart. This folder keeps a replayed dataset as tightly aligned as the live
capture was.
