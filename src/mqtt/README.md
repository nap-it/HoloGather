# src/mqtt — MQTT sensor ingestion

Ingests the non-HoloLens sensors that arrive over MQTT (GPS and orientation)
and parses their vendor-specific payloads into plain dicts. The parsed dicts are
turned into `SensorEnvelope`s by the MQTT sensor processes in
[`../processes`](../processes).

## Files
- **`client_service.py`** — `MqttClientService`: thin wrapper over `paho-mqtt`
  (connect / subscribe / background network loop).
- **`vam_location_parser.py`** — ETSI **VAM** GPS from `cabasicservice`; decodes
  lat/lon/speed and preserves the measurement time (`generationDeltaTime`).
- **`phone_location_parser.py`** — **OwnTracks** phone GPS; decodes lat/lon and
  preserves the fix time (`tst` → `source_ts_ns`).
- **`unity_heading_parser.py`** — device **heading** (degrees) from the Unity app.
- **`unity_imu_parser.py`** — Unity **IMU** (orientation) payloads.

## Note on timestamps
The parsers keep the source measurement time alongside the value as dataset
provenance; the receipt time (`ts_unix_ns`) is stamped later in the envelope.
Each parser returns `None` on malformed input (the caller skips it).
