# src/handlers — subscriber implementations

One handler per stream. Each subscribes to a Zenoh topic via
[`../zenoh_utils`](../zenoh_utils), decodes packets with
[`../serialization`](../serialization), and turns them into something useful
(a video stream, a live view, logged values). Handlers are selected by name in
the config `[sensors]` list and instantiated by `src/factory.py`.

## Base
- **`base_subscriber.py`** — `BaseSubscriberProcess` (an `mp.Process`): connection
  lifecycle, the consume loop, rolling metrics, and clean shutdown. Subclasses
  implement `_subscriber_loop()` / `_subscriber_cleanup()`.

## Video / sensor handlers
- **`rgb_camera_subscriber.py`**, **`depth_camera_subscriber.py`**,
  **`vlc_subscriber.py`** — decode the HoloLens video streams (`hl2ss.decode_*`)
  and push frames to RTSP via [`../utils`](../utils) `VideoStreaming`.
- **`microphone_subscriber.py`** — AAC audio (served over WebSocket).
- **`imu_subscriber.py`**, **`eet_subscriber.py`**, **`spatial_input_subscriber.py`**,
  **`depth_correlated_subscriber.py`** — IMU, eye tracking, spatial input, and
  RGB-D correlation.

## Location / orientation (MQTT-origin) handlers
- **`vam_location_subscriber.py`** — VAM **and** phone GPS (same class, different
  config section).
- **`heading_subscriber.py`**, **`unity_imu_subscriber.py`** — device heading and
  Unity IMU.
- **`map_subscriber.py`** — live map view of GPS + heading served over HTTP
  (`web_port`, default 8797); optional raw-`gpsd` ground-truth overlay. The
  location analogue of the RGB video subscriber.

## Adding a handler
Create the class here, register its name in `src/factory.py` **and** in the
validator whitelist in `src/utils/config.py`, then list it in `[sensors]`.
