# src/processes — worker processes

Each sensor stream runs as its own supervised process (see
[`../runtime`](../runtime)). A process captures/ingests one source, wraps samples
in `SensorEnvelope`s, and fans them out to recording ([`../storage`](../storage))
and Zenoh ([`../publish`](../publish)). The same processes also drive **simulation
replay** from recorded files, paced by [`../sync`](../sync).

## Files
- **`hololens_streamer_process.py`** — captures the HoloLens streams (PV, depth,
  microphone, …) via the [`../hololens`](../hololens) sink manager; records +
  publishes them. Handles multi-stream replay on a shared timeline.
- **`mqtt_sensor_base_process.py`** — base class for the MQTT sensors: a
  keep-latest capture loop in record/live mode and a scheduled replay loop in
  simulation. Subclasses only override payload parsing.
- **`vam_location_sensor_process.py`**, **`phone_location_sensor_process.py`**,
  **`unity_heading_sensor_process.py`**, **`unity_imu_sensor_process.py`** —
  concrete MQTT sensors (topic + parser from [`../mqtt`](../mqtt)).
- **`health_process.py`** — aggregates per-process heartbeats into health state.
- **`metrics_aggregator_process.py`** — collects and reports the per-stream
  throughput/latency metrics.

## Data flow
`capture/ingest → SensorEnvelope → { StreamRecorder (.hlp2), Zenoh publisher }`,
with health + metrics emitted on the side buses.
