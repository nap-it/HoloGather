# WPMC 2026 paper release

Version: `wpmc-2026-v1.0.0`

This is the reviewed subscriber snapshot accompanying the paper **“A
Multimodal Gathering Tool for Wearable Urban Perception Data for the Microsoft
HoloLens 2.”**

## Included

- Zenoh subscribers and `SensorEnvelope` decoding examples.
- RGB, depth, VLC, audio, location, heading, IMU, eye-tracking, and
  spatial-input handlers.
- Local RTSP/WebRTC video, WebSocket audio, map, health, and metrics outputs.
- Sanitized example configuration and loopback-only service defaults.
- Public `hl2ss` submodule pinned to
  `fcc4e84108c79a1f7eb15f607a438b4086423e79`.
- MediaMTX pinned to version `1.20.1` with unused network protocols disabled.

## Validation

- 5 unit tests pass on the host and in the release container.
- Python compilation, shell syntax, Docker build, Compose validation, and
  MediaMTX configuration startup pass.
- The released tree contains no deployment credentials, private network
  addresses, recordings, packet captures, databases, private keys, or
  certificates detected by the release audit.

## Important limitations

- Initialize dependencies with `git submodule update --init --recursive`.
- The public `hl2ss` revision builds and passes automated tests, but real
  HoloLens streams should be exercised end-to-end with the publisher before
  experimental use.
- No project license is asserted by this snapshot. The project owner must add
  an approved root license before public redistribution. The `hl2ss`
  dependency has its own license and Commons Clause restriction.
- Camera, microphone, location, pose, calibration data, and runtime logs can be
  sensitive. Review them separately before publication.

