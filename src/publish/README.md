# src/publish — Zenoh publishing

Publishes canonical `SensorEnvelope`s to Zenoh so subscribers (e.g. the
[hololens-subscribers-examples](../../../hololens-subscribers-examples)) can
consume the live streams.

## Files
- **`zenoh_publisher.py`** — `ZenohPublisherService`: owns one shared Zenoh
  session and lazily-declared per-topic publishers, fed from a queue by a single
  dispatcher thread. Optionally shares a Zenoh SHM provider across topics.
- **`topic_router.py`** — builds the default topic key for an envelope from its
  canonical fields (sensor type / stream id), keeping topic naming in one place.

## Role
The processes in [`../processes`](../processes) enqueue `(topic, envelope)`; this
folder serializes each via [`../serialization`](../serialization) (`zenoh_codec`)
and puts it on the wire. Enabled/disabled by config (`ZENOH_ENABLED`).
