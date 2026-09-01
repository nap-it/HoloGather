# Configurations

This document lists configuration options for `hololens-subscribers-examples`.

Precedence:
1. File (`--config`)
2. Environment variables
3. CLI flags

Default config file path:
- `configs/app_config.ini`

## File Configuration

### `[settings]`
- `log_level` default: `DEBUG`
- `sensor_config_file` default: `configs/app_config.ini`
- `hololens_user_id` default: `-1`
- `record_mode` default: `false`
- `simulation_mode` default: `false`
- `publish_mode` default: `false`
- `data_dir` default: `.`
- `metrics_port` default: `8000`

### `[sensors]`
Supported forms:
- `enable = sensorA,sensorB`
- `list = sensorA; sensorB:param=x; ...`
- `sensor0 = sensorA`
- `sensor1 = sensorB:param=x`

Comments in `list` can use lines starting with `;` or `#`.

### Sensor names (accepted)
- Camera: `hololens_camera`, `hololens_pv_sub`, `camera_sub`
- Depth: `hololens_depth`, `depth_camera`, `hl2_depth`
- IMU: `hololens_imu`, `imu`, `hl2_imu` (requires `sensor=accelerometer|gyroscope|magnetometer|all`; `all` runs one fused 5Hz process)
- EET: `hololens_eet`, `eye_tracking`, `hl2_eet`
- Spatial input: `hololens_si`, `spatial_input`, `hl2_si`
- Microphone: `hololens_microphone`, `microphone`, `hl2_microphone`
- VLC: `hololens_vlc`, `vlc`, `hl2_vlc` (requires `sensor=leftleft|leftfront|rightfront|rightright`)
- Other: `depth_correlator`, `depth_correlator_subscriber`, `vam_location`, `hololens_vam_location`, `phone_location`, `hololens_phone_location`, `unity_heading`, `heading`, `hololens_heading`, `unity_imu`, `orientation`, `hololens_unity_imu`

## Environment Variables

Lowercase and uppercase forms are supported for key settings:
- `settings_log_level` / `SETTINGS_LOG_LEVEL`
- `sensor_config_file` / `SENSOR_CONFIG_FILE`
- `hololens_user_id` / `HOLOLENS_USER_ID`
- `record_mode` / `RECORD_MODE`
- `simulation_mode` / `SIMULATION_MODE`
- `publish_mode` / `PUBLISH_MODE`
- `data_dir` / `DATA_DIR`
- `metrics_port` / `METRICS_PORT`
- `sensors_enable` / `SENSORS_ENABLE`
- `sensors_list` / `SENSORS_LIST`
- `sensors_sensor0` / `SENSORS_SENSOR0` (and numbered variants)

## CLI Flags
- `--config` (default: `configs/app_config.ini`)
- `--sensors_enable`
- `--sensors_list`
- `--sensors_sensor` (repeatable)
- `--sensors_sensor0=...` / `--sensors_sensor1=...` (exact index form)
- `--log_level`
- `--sensor_config_file`
- `--hololens_user_id`
- `--record_mode`
- `--simulation_mode`
- `--publish_mode`
- `--data_dir`
- `--metrics_port`

## Validation Rules
- `log_level` must be one of: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`
- `record_mode` and `simulation_mode` cannot both be true
- `sensor_config_file` must exist
- At least one sensor must be configured
- Unknown sensor names are rejected
- IMU and VLC sensors must include required `sensor=...` parameter

## Unity MQTT-Derived Streams
- `unity_heading` consumes publisher topic `Hololens/Heading` (stream id in publisher: `unity_heading_<id>`).
- `unity_imu` consumes publisher topic `Hololens/UnityIMU` (stream id in publisher: `unity_imu_<id>`).
