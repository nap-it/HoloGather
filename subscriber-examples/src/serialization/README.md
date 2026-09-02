# src/serialization — wire decoding

Decodes the bytes received off Zenoh into `(metadata, payload)` and unwraps the
HoloLens packet layer. This mirrors the publisher's `zenoh_codec`.

## Files
- **`packet_codec.py`** — the wire format:
  `[4-byte big-endian header len][msgpack header][payload bytes]`.
  `decode(bytes) → (metadata: dict, payload: bytes)`.
- **`hl2ss_packet.py`** — `unwrap_sensor_payload(metadata, payload)`: when the
  publisher sent `content_type=application/x-hl2ss.packet`, strips the
  `hl2ss.pack_packet` wrapper to yield the raw encoded frame (+ pose/timestamp
  context) the video decoders expect.
- **`sensor_types.py`** — `SensorType` constants (PV, DEPTH, VLC, …) shared with
  the header's `st` field.

## Flow
`SensorZenohReader` bytes → `packet_codec.decode` → (`hl2ss_packet.unwrap` for
video) → handler decode.
