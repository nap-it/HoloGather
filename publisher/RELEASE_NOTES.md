# WPMC 2026 paper release

Version: `wpmc-2026-v1.0.0`

This is the reviewed source snapshot accompanying the paper **“A Multimodal
Gathering Tool for Wearable Urban Perception Data for the Microsoft HoloLens
2.”**

## Included

- HoloLens RGB, depth, audio, IMU, eye-tracking, and spatial-input adapters.
- MQTT adapters for external positioning, heading, and orientation data.
- Versioned `SensorEnvelope` serialization for Zenoh and HLP2 files.
- Live publishing, recording, synchronized replay, supervision, health, and
  metrics components.
- Sanitized example configuration and loopback-only development defaults.
- Public `hl2ss` submodule pinned to
  `fcc4e84108c79a1f7eb15f607a438b4086423e79`.

## Validation

- 12 unit tests pass on the host and in the release container.
- Python compilation, shell syntax, Docker build, and Compose validation pass.
- HLP2 file framing is tested with both uncompressed and LZ4 records.
- The released tree contains no deployment credentials, private network
  addresses, recordings, packet captures, databases, private keys, or
  certificates detected by the release audit.

## Important limitations

- Initialize dependencies with `git submodule update --init --recursive`.
- The public `hl2ss` revision builds and passes automated tests, but the
  original deployment used a private fork. Validate video and audio capture on
  a real HoloLens 2 before experimental use.
- No project license is asserted by this snapshot. The project owner must add
  an approved root license before public redistribution. The `hl2ss`
  dependency has its own license and Commons Clause restriction.
- Camera, microphone, location, pose, calibration data, and runtime logs can be
  sensitive. Review them separately before publication.

