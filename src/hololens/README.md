# src/hololens — HoloLens capture adapter

The boundary between the HoloLens streaming library (`hl2ss` / `hl2ss_mp`) and the
rest of the publisher. Everything upstream of this folder is HoloLens-specific;
everything downstream works on canonical `SensorEnvelope`s.

## Files
- **`hl2ss_imports.py`** — single, strict import point for the vendored `hl2ss`
  modules (prepends the bundled `libs/.../viewer` path so the library's top-level
  sibling imports resolve). Import `hl2ss` from here, never directly.
- **`sink_manager.py`** — `HololensSinkManager`: owns the shared `hl2ss_mp`
  producer/consumer pair and the sink attach/detach lifecycle for the active
  streams (PV, depth, microphone, …). Generic — no per-sensor receiver logic.
- **`packet_contract.py`** — exports the rich per-packet contract (timestamp,
  pose, frame metadata) extracted from an `hl2ss` packet for downstream use.

## Role in the pipeline
`sink_manager` pulls frames from the HoloLens → the streamer process
([`../processes/hololens_streamer_process.py`](../processes)) wraps each into a
`SensorEnvelope` for recording and Zenoh publishing.
