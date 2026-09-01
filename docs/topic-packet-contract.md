# Subscriber Packet Contract

Zenoh samples decode to `(envelope_header, envelope_payload)` via `packet_codec.decode`.

For HoloLens streams, `envelope_header["content_type"]` is now:

- `application/x-hl2ss.packet`

In that case:

1. Call `hl2ss.unpack_packet(envelope_payload)` (or `unwrap_sensor_payload(...)` helper).
2. Decode the inner `packet.payload` with the sensor decoder (`decode_pv`, `decode_rm_depth_*`, `decode_rm_vlc`, `decode_rm_imu`, `decode_microphone`, `decode_si`, `decode_eet`).
3. Read per-packet metadata from `envelope_header["metadata"]`.
4. Read stream calibration from `envelope_header["calibration"]` when present.

## By sensor/topic

- RGB camera topic: full hl2ss packet; inner payload is PV encoded frame + PV trailer.
- Depth topic: full hl2ss packet; inner payload is RM depth encoded frame + depth trailer.
- VLC topics: full hl2ss packet; inner payload is VLC encoded frame + VLC trailer.
- IMU topics: full hl2ss packet; inner payload is packed IMU sample records.
- Microphone topic: full hl2ss packet; inner payload is AAC/RAW microphone bytes.
- Spatial Input topic: full hl2ss packet; inner payload is SI structured bytes.
- EET topic: full hl2ss packet; inner payload is EET structured bytes.

Non-HoloLens MQTT-derived topics (`Heading`, `UnityIMU`, `Location`) remain msgpack payloads.
