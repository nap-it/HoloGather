# HoloGather

HoloGather is an end-to-end toolkit for gathering, recording, replaying, and consuming multimodal sensor data from a Microsoft HoloLens 2. It combines the HoloLens publisher and its subscriber reference implementations in a single repository while keeping both applications independently deployable.

## What is included

| Component | Purpose | Documentation |
|---|---|---|
| `publisher/` | Captures HoloLens and MQTT inputs, records `.hlp2` streams, publishes to Zenoh, and replays recorded sessions | [Publisher README](publisher/README.md) |
| `subscriber-examples/` | Decodes Zenoh streams and exposes video, audio, positioning, orientation, and metrics outputs | [Subscriber README](subscriber-examples/README.md) |
| `publisher/libs/hololens_sensor_streaming/` | App-local `hl2ss` capture dependency | Managed by the root `.gitmodules` |
| `subscriber-examples/libs/hololens_sensor_streaming/` | App-local `hl2ss` decoding dependency | Managed by the root `.gitmodules` |

The two `hl2ss` paths intentionally point to the same pinned upstream revision. Keeping one checkout inside each application preserves its standalone Docker build context and avoids coupling either image to files outside its directory.

## Supported data

- HoloLens personal video (RGB), long-throw or AHAT depth, and microphone.
- Research Mode VLC cameras, accelerometer, gyroscope, and magnetometer.
- Extended eye tracking and spatial input.
- MQTT-delivered VAM location, phone location, Unity heading, and Unity
  orientation.
- Local recording and synchronized real-time replay.
- RTSP, WebRTC, HLS, WebSocket, web-map, health, and Prometheus-style outputs.

The checked-in configuration enables RGB, long-throw depth, microphone, VAM location, phone location, Unity heading, and Unity orientation. Other sensors can be enabled in the application configuration files.

## Prerequisites

- Git 2.x with submodule support.
- Docker Engine with the Docker Compose plugin.
- A Linux host is recommended. The supplied Compose projects use host networking and the `IPC_LOCK` capability.
- For live capture: a HoloLens 2 running a compatible `hl2ss` server.
- For enabled external streams: an MQTT broker and the corresponding data producers.

## Get started

### 1. Clone the repository

```bash
git clone --recurse-submodules <repo_url>
cd hologather
```

If the repository was cloned without submodules, initialize them from the repository root:

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

Confirm the checkout with `git submodule status --recursive`.

### 2. Configure the data sources

Review these files before starting a live deployment:

| File | Configure |
|---|---|
| [`publisher/configs/app_config.ini`](publisher/configs/app_config.ini) | Enabled publisher sensors, HoloLens address, operating defaults |
| [`publisher/configs/sensors_config.ini`](publisher/configs/sensors_config.ini) | Sensor profiles, Zenoh topics, MQTT broker and source topics |
| [`subscriber-examples/configs/app_config.ini`](subscriber-examples/configs/app_config.ini) | Enabled subscribers, matching topics, queues, and output ports |
| [`subscriber-examples/configs/mediamtx.yml`](subscriber-examples/configs/mediamtx.yml) | MediaMTX streaming endpoints |

Publisher and subscriber topic names must match. The committed files contain loopback placeholders and no credentials; supply deployment-specific values locally and do not commit secrets or device addresses.

### 3. Start the publisher

The interactive launcher asks whether to run in live, record, or simulation mode and whether to publish over Zenoh:

```bash
cd publisher
./run-publisher.sh
```

It can also be started non-interactively:

```bash
# Capture and publish without writing a recording
SETTINGS_MODE=live ZENOH_ENABLED=true ./run-publisher.sh

# Capture, publish, and write a recording under ./recordings
SETTINGS_MODE=record ZENOH_ENABLED=true HOST_DIR=./recordings ./run-publisher.sh

# Replay an existing recording over the live Zenoh topics
SETTINGS_MODE=simulation ZENOH_ENABLED=true HOST_DIR=./recordings ./run-publisher.sh
```

### 4. Start the subscriber examples

From a second terminal:

```bash
cd subscriber-examples
./run-subscriber.sh
```

The first run builds the application image and downloads the pinned MediaMTX image. Start-up order is not strict, but starting the publisher first makes it easier to confirm that data is arriving immediately.

To stop either stack, run `docker compose down` from its application directory.

## Default subscriber outputs

| Output | Default endpoint |
|---|---|
| RGB video | `rtsp://localhost:8554/pv_camera` |
| RGB video over WebRTC | `http://localhost:8889/pv_camera/` |
| Depth video | `rtsp://localhost:8554/depth_camera` |
| VLC video | `rtsp://localhost:8554/vlc_camera_*` |
| GPS and heading map | `http://localhost:8797/` |
| Microphone WebSocket | `ws://localhost:4000/audio` |
| Subscriber metrics | `http://localhost:8686/` |

Only outputs for enabled subscribers are started. See the [subscriber configuration guide](subscriber-examples/docs/configurations.md)
and [topic/packet contract](subscriber-examples/docs/topic-packet-contract.md) for the complete mapping.

