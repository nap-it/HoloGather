# src/storage — HLP2 recording & playback

Reads and writes the dataset's local recording files. Each stream is a separate
append-only **`.hlp2`** file of `SensorEnvelope` records, framed by
[`../serialization`](../serialization) (`record_codec`).

Each file record starts with a 4-byte big-endian record length, followed by an
inner HLP2 record. The inner record may optionally be compressed as one LZ4
frame; see the serialization documentation for the byte-level layout.

## Files
- **`recorder.py`** — `StreamRecorder`: append envelopes to a `.hlp2` file
  (record mode).
- **`reader.py`** — `StreamReader`: iterate envelopes back from a `.hlp2` file
  (simulation replay, and the offline validation tooling).
- **`manifest.py`** — per-session manifest (session id, `session_start_unix_ns`,
  `session_start_mono_ns`) describing a recording run.

## Layout on disk
```
hololens_recording_<YYYYMMDD_HHMMSS>/
├── HololensCamera_1.hlp2      # PV / RGB
├── HololensDepth_1.hlp2
├── HololensMicrophone_1.hlp2
├── vam_location_1.hlp2  ·  phone_location_1.hlp2
└── unity_heading_1.hlp2  ·  unity_imu_1.hlp2
```
These files are the raw input to the dataset validation dashboard.
