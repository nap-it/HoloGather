# src/zenoh_utils — Zenoh transport

The subscriber-side transport layer: receive raw packets off Zenoh and hand them
to a handler.

## Files
- **`sensor_zenoh_reader.py`** — `SensorZenohReader`: opens a Zenoh session,
  declares a subscriber on a topic, and pushes each received sample as a
  `SensorPacket(arrival_timestamp, message)` into an overwriting FIFO
  ([`../utils`](../utils) `OverWritableMPFIFO`). The handler drains that queue and
  decodes with [`../serialization`](../serialization) `packet_codec`.

## Role
Isolates all Zenoh specifics in one place so that handlers deal only with
`SensorPacket`s, never with the Zenoh API. Uses the default (peer) Zenoh config
unless one is supplied.
