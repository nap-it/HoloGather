# src/serialization — SensorEnvelope codecs

Canonical serialization for the `SensorEnvelope` (defined in
[`../contracts`](../contracts)) across both sinks: local recording files and the
Zenoh wire. One envelope shape, two encodings.

## Files
- **`payload_codec.py`** — encodes/decodes the sensor payload dict (msgpack).
- **`record_codec.py`** — encodes the inner HLP2 record:
  `[magic][header len][payload len][msgpack header][payload]`.
- **`zenoh_codec.py`** — Zenoh wire framing:
  `[4-byte header len][msgpack header][payload bytes]`, consumed by subscribers'
  `packet_codec`.

## HLP2 file framing

[`../storage/recorder.py`](../storage/recorder.py) wraps every encoded HLP2
record with a 4-byte, big-endian record length. The complete on-disk layout is:

```text
[record length][HLP2][header length][payload length][msgpack header][payload]
      4 B       4 B       4 B             4 B
```

The record length excludes its own 4 bytes. When `recording_compression=lz4`,
the bytes after the record-length field are an LZ4 frame containing the entire
inner HLP2 record; with `recording_compression=none`, they are the inner record
directly. Readers must know the session's compression setting (the runtime also
tries an uncompressed fallback during replay).

## Why two codecs
Recording keeps a self-describing, seekable append log; Zenoh keeps a compact
header+payload frame. Both wrap the same envelope, so a recorded stream and a
live stream carry identical fields.
