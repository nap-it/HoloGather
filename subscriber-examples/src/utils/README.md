# src/utils — shared subscriber infrastructure

Buffers, video output, web serving, and config parsing used across the handlers
in [`../handlers`](../handlers).

## Buffers (keep-latest)
- **`base_queue.py`** — abstract queue base.
- **`over_writable_fifo.py`** — `OverWritableFIFO`: bounded, thread-safe FIFO that
  drops the oldest item when full (single process; `deque` + `Lock`).
- **`overwritable_mp_fifo.py`** — `OverWritableMPFIFO`: process-safe variant
  backed by `multiprocessing.Queue`. Used between a `SensorZenohReader` callback
  and the handler loop; the overwriting semantics keep latency bounded under
  bursts.

## Video output
- **`video_streaming.py`** — `VideoStreaming`: encodes frames with **PyAV** and
  pushes them to **MediaMTX over RTSP** (`queue_frame()` → RTSP → WebRTC/HLS via
  MediaMTX). Used by the RGB / depth / VLC subscribers.

## Web / config
- **`fastapi_app.py`**, **`fastapi_server.py`** — FastAPI app + runner for
  WebSocket serving (e.g. the microphone audio stream).
- **`config.py`** — `AppConfig` / `SensorSpec`: parses the `[sensors]` list and
  per-sensor sections from the `.ini`, with env overrides and validation.

## Usage
```python
from src.utils.over_writable_fifo import OverWritableFIFO      # same process
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO   # across mp.Process
buf = OverWritableMPFIFO(max_size=2)
```
