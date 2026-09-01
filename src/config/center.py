"""Unified configuration center.

This module centralizes all startup configuration in one place and applies a
deterministic precedence chain:
1. file config
2. environment variables
3. CLI overrides
"""

from __future__ import annotations

import argparse
import configparser
import os
import json
import time
from datetime import datetime
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Optional


class PrettyConfigRepr:
    """Shared pretty repr for config dataclasses.

    The repr is JSON-formatted and recursively masks sensitive fields so logs
    remain readable and safe by default.
    """

    _SENSITIVE_TOKENS = ("password", "secret", "token", "key")

    @classmethod
    def _mask_sensitive(cls, value):
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                key_lower = str(k).lower()
                if any(token in key_lower for token in cls._SENSITIVE_TOKENS):
                    out[k] = "***"
                else:
                    out[k] = cls._mask_sensitive(v)
            return out
        if isinstance(value, list):
            return [cls._mask_sensitive(v) for v in value]
        if isinstance(value, tuple):
            return [cls._mask_sensitive(v) for v in value]
        return value

    def __repr__(self) -> str:
        if is_dataclass(self):
            payload = asdict(self)
        else:
            payload = self.__dict__
        payload = self._mask_sensitive(payload)
        return json.dumps(payload, indent=2, sort_keys=True, default=str)


@dataclass(frozen=True, repr=False)
class SettingsConfig(PrettyConfigRepr):
    """Global runtime settings shared across all processes."""

    log_level: str = "INFO"
    mode: str = "live"  # live|record|simulation
    data_dir: str = "./recordings"


@dataclass(frozen=True, repr=False)
class SessionConfig(PrettyConfigRepr):
    """Session identity and timeline anchors."""

    session_id: str
    session_start_unix_ns: int
    session_start_mono_ns: int


@dataclass(frozen=True, repr=False)
class CameraConfig(PrettyConfigRepr):
    """Personal video stream configuration."""

    enabled: bool = True
    stream_port_name: str = "PERSONAL_VIDEO"
    width: int = 1280
    height: int = 720
    framerate: int = 15
    divisor: int = 1
    profile: str = "H265_MAIN"
    gop_size: int = 5
    publish_topic: str = "Hololens/RGBCamera"


@dataclass(frozen=True, repr=False)
class DepthConfig(PrettyConfigRepr):
    """Depth stream configuration."""

    enabled: bool = True
    stream_port_name: str = "RM_DEPTH_LONGTHROW"
    depth_sensor: str = "RM_DEPTH_LONGTHROW"
    publish_topic: str = "Hololens/DepthCamera"


@dataclass(frozen=True, repr=False)
class MicrophoneConfig(PrettyConfigRepr):
    """Microphone stream configuration."""

    enabled: bool = True
    stream_port_name: str = "MICROPHONE"
    publish_topic: str = "Hololens/Microphone"
    profile: str = "AAC_24000"
    chunk: str = "MICROPHONE"
    level: str = "L2"
    decoded: bool = False


@dataclass(frozen=True, repr=False)
class EETConfig(PrettyConfigRepr):
    """Extended eye-tracking stream configuration."""

    enabled: bool = True
    stream_port_name: str = "EXTENDED_EYE_TRACKER"
    publish_topic: str = "Hololens/EET"
    fps: int = 30
    decoded: bool = False


@dataclass(frozen=True, repr=False)
class SpatialInputConfig(PrettyConfigRepr):
    """Spatial input stream configuration."""

    enabled: bool = True
    stream_port_name: str = "SPATIAL_INPUT"
    publish_topic: str = "Hololens/SpatialInput"
    decoded: bool = False


@dataclass(frozen=True, repr=False)
class IMUSensorConfig(PrettyConfigRepr):
    """Configuration for one IMU stream."""

    stream_port_name: str
    publish_topic: str
    mode: str = "MODE_1"


@dataclass(frozen=True, repr=False)
class IMUConfig(PrettyConfigRepr):
    """Grouped IMU stream configuration."""

    enabled: bool = True
    decoded: bool = False
    accelerometer: IMUSensorConfig = field(
        default_factory=lambda: IMUSensorConfig(
            stream_port_name="RM_IMU_ACCELEROMETER",
            publish_topic="Hololens/IMU/Accelerometer",
            mode="MODE_1",
        )
    )
    gyroscope: IMUSensorConfig = field(
        default_factory=lambda: IMUSensorConfig(
            stream_port_name="RM_IMU_GYROSCOPE",
            publish_topic="Hololens/IMU/Gyroscope",
            mode="MODE_1",
        )
    )
    magnetometer: IMUSensorConfig = field(
        default_factory=lambda: IMUSensorConfig(
            stream_port_name="RM_IMU_MAGNETOMETER",
            publish_topic="Hololens/IMU/Magnetometer",
            mode="MODE_1",
        )
    )


@dataclass(frozen=True, repr=False)
class VLCCameraConfig(PrettyConfigRepr):
    """Configuration for one VLC camera stream."""

    stream_port_name: str
    publish_topic: str


@dataclass(frozen=True, repr=False)
class VLCConfig(PrettyConfigRepr):
    """Grouped VLC camera stream configuration."""

    enabled: bool = True
    profile: str = "H265_MAIN"
    divisor: int = 1
    gop_size: int = 5
    decoded: bool = False
    leftfront: VLCCameraConfig = field(
        default_factory=lambda: VLCCameraConfig(
            stream_port_name="RM_VLC_LEFTFRONT",
            publish_topic="Hololens/VLC/leftfront",
        )
    )
    leftleft: VLCCameraConfig = field(
        default_factory=lambda: VLCCameraConfig(
            stream_port_name="RM_VLC_LEFTLEFT",
            publish_topic="Hololens/VLC/leftleft",
        )
    )
    rightfront: VLCCameraConfig = field(
        default_factory=lambda: VLCCameraConfig(
            stream_port_name="RM_VLC_RIGHTFRONT",
            publish_topic="Hololens/VLC/rightfront",
        )
    )
    rightright: VLCCameraConfig = field(
        default_factory=lambda: VLCCameraConfig(
            stream_port_name="RM_VLC_RIGHTRIGHT",
            publish_topic="Hololens/VLC/rightright",
        )
    )


@dataclass(frozen=True, repr=False)
class HololensConfig(PrettyConfigRepr):
    """HoloLens source and enabled stream list configuration."""

    enabled: bool = True
    address: str = "127.0.0.1"
    user_id: str = "1"
    sink_buffer: int = 150
    sensors: tuple[str, ...] = ("hololens_camera", "hololens_depth")
    camera: CameraConfig = field(default_factory=CameraConfig)
    depth: DepthConfig = field(default_factory=DepthConfig)
    microphone: MicrophoneConfig = field(default_factory=MicrophoneConfig)
    eet: EETConfig = field(default_factory=EETConfig)
    spatial_input: SpatialInputConfig = field(default_factory=SpatialInputConfig)
    imu: IMUConfig = field(default_factory=IMUConfig)
    vlc: VLCConfig = field(default_factory=VLCConfig)


@dataclass(frozen=True, repr=False)
class MqttConfig(PrettyConfigRepr):
    """MQTT broker and topic settings."""

    enabled: bool = True
    host: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    vam_location_topic: str = "vanetza/in/vam"
    phone_location_topic_owntrack: str = "owntracks/user/phone"
    heading_topic: str = "camera_heading"
    orientation_topic: str = "hololens/orientation"
    vam_location_enabled: bool = True
    phone_location_enabled: bool = False
    heading_enabled: bool = True
    orientation_enabled: bool = True


@dataclass(frozen=True, repr=False)
class ZenohConfig(PrettyConfigRepr):
    """Zenoh publication configuration, including optional SHM tuning."""

    enabled: bool = True
    config_file: Optional[str] = None
    use_shm: bool = False
    shm_arena_size: int = 16 * 1024 * 1024


@dataclass(frozen=True, repr=False)
class RecordingConfig(PrettyConfigRepr):
    """Local recording controls."""

    enabled: bool = True
    compression: str = "lz4"  # lz4|none


@dataclass(frozen=True, repr=False)
class ObservabilityConfig(PrettyConfigRepr):
    """Metrics and health endpoint configuration."""

    metrics_enabled: bool = True
    metrics_port: int = 9101
    health_enabled: bool = True
    health_port: int = 9201


@dataclass(frozen=True, repr=False)
class RuntimeConfig(PrettyConfigRepr):
    """Supervisor lifecycle and restart policy parameters."""

    restart_max_attempts: int = 3
    restart_backoff_s: float = 1.0
    supervisor_tick_s: float = 1.0


@dataclass(frozen=True, repr=False)
class AppConfig(PrettyConfigRepr):
    """Immutable application config tree distributed to all processes."""

    settings: SettingsConfig
    session: SessionConfig
    hololens: HololensConfig
    mqtt: MqttConfig
    zenoh: ZenohConfig
    recording: RecordingConfig
    observability: ObservabilityConfig
    runtime: RuntimeConfig


@dataclass
class MutableAppConfig:
    """Mutable merge target used while applying file/env/cli overrides."""

    settings_log_level: str = "INFO"
    settings_mode: str = "live"
    settings_data_dir: str = "./recordings"

    hololens_enabled: bool = True
    hololens_address: str = "127.0.0.1"
    hololens_user_id: str = "1"
    hololens_sink_buffer: int = 150
    hololens_sensors: str = "hololens_camera;hololens_depth"

    camera_enabled: bool = True
    camera_stream_port_name: str = "PERSONAL_VIDEO"
    camera_width: int = 1280
    camera_height: int = 720
    camera_framerate: int = 15
    camera_divisor: int = 1
    camera_profile: str = "H265_MAIN"
    camera_gop_size: int = 5
    camera_publish_topic: str = "Hololens/RGBCamera"

    depth_enabled: bool = True
    depth_stream_port_name: str = "RM_DEPTH_LONGTHROW"
    depth_sensor: str = "RM_DEPTH_LONGTHROW"
    depth_publish_topic: str = "Hololens/DepthCamera"

    microphone_enabled: bool = True
    microphone_stream_port_name: str = "MICROPHONE"
    microphone_publish_topic: str = "Hololens/Microphone"
    microphone_profile: str = "AAC_24000"
    microphone_chunk: str = "MICROPHONE"
    microphone_level: str = "L2"
    microphone_decoded: bool = False

    eet_enabled: bool = True
    eet_stream_port_name: str = "EXTENDED_EYE_TRACKER"
    eet_publish_topic: str = "Hololens/EET"
    eet_fps: int = 30
    eet_decoded: bool = False

    spatial_input_enabled: bool = True
    spatial_input_stream_port_name: str = "SPATIAL_INPUT"
    spatial_input_publish_topic: str = "Hololens/SpatialInput"
    spatial_input_decoded: bool = False

    imu_enabled: bool = True
    imu_decoded: bool = False
    imu_accelerometer_stream_port_name: str = "RM_IMU_ACCELEROMETER"
    imu_accelerometer_topic: str = "Hololens/IMU/Accelerometer"
    imu_accelerometer_mode: str = "MODE_1"
    imu_gyroscope_stream_port_name: str = "RM_IMU_GYROSCOPE"
    imu_gyroscope_topic: str = "Hololens/IMU/Gyroscope"
    imu_gyroscope_mode: str = "MODE_1"
    imu_magnetometer_stream_port_name: str = "RM_IMU_MAGNETOMETER"
    imu_magnetometer_topic: str = "Hololens/IMU/Magnetometer"
    imu_magnetometer_mode: str = "MODE_1"

    vlc_enabled: bool = True
    vlc_profile: str = "H265_MAIN"
    vlc_divisor: int = 1
    vlc_gop_size: int = 5
    vlc_decoded: bool = False
    vlc_leftfront_stream_port_name: str = "RM_VLC_LEFTFRONT"
    vlc_leftfront_topic: str = "Hololens/VLC/leftfront"
    vlc_leftleft_stream_port_name: str = "RM_VLC_LEFTLEFT"
    vlc_leftleft_topic: str = "Hololens/VLC/leftleft"
    vlc_rightfront_stream_port_name: str = "RM_VLC_RIGHTFRONT"
    vlc_rightfront_topic: str = "Hololens/VLC/rightfront"
    vlc_rightright_stream_port_name: str = "RM_VLC_RIGHTRIGHT"
    vlc_rightright_topic: str = "Hololens/VLC/rightright"

    mqtt_enabled: bool = True
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_vam_location_topic: str = "vanetza/in/vam"
    mqtt_phone_location_topic_owntrack: str = "owntracks/user/phone"
    mqtt_heading_topic: str = "camera_heading"
    mqtt_orientation_topic: str = "hololens/orientation"

    zenoh_enabled: bool = True
    zenoh_config_file: Optional[str] = None
    zenoh_use_shm: bool = False
    zenoh_shm_arena_size: int = 16 * 1024 * 1024

    recording_enabled: bool = True
    recording_compression: str = "lz4"

    observability_metrics_enabled: bool = True
    observability_metrics_port: int = 9101
    observability_health_enabled: bool = True
    observability_health_port: int = 9201

    runtime_restart_max_attempts: int = 3
    runtime_restart_backoff_s: float = 1.0
    runtime_supervisor_tick_s: float = 1.0


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser exposing all mutable config fields as overrides."""

    p = argparse.ArgumentParser(description="Hololens Publisher")
    p.add_argument("--config", default="configs/app_config.ini")
    p.add_argument("--sensor-config-file", default="configs/sensors_config.ini")
    for f in fields(MutableAppConfig):
        p.add_argument("--" + f.name.replace("_", "-"))
    return p


def _to_bool(v: str) -> bool:
    """Parse common truthy/falsey text into boolean."""

    return v.strip().lower() in {"1", "true", "yes", "on"}


def _set(cfg: MutableAppConfig, name: str, raw: str) -> None:
    """Type-aware assignment helper for mutable config fields."""

    cur = getattr(cfg, name)
    if isinstance(cur, bool):
        setattr(cfg, name, _to_bool(raw))
    elif isinstance(cur, int):
        setattr(cfg, name, int(raw))
    elif isinstance(cur, float):
        setattr(cfg, name, float(raw))
    else:
        setattr(cfg, name, raw)


def _from_file(cfg: MutableAppConfig, config_path: str, sensor_config_path: str) -> None:
    """Populate mutable config from INI files (lowest precedence layer)."""

    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if not os.path.isfile(sensor_config_path):
        raise FileNotFoundError(f"Sensor config file not found: {sensor_config_path}")

    cp = configparser.ConfigParser()
    cp.read([config_path, sensor_config_path])

    cfg.hololens_sensors = cp.get("sensors", "list", fallback=cfg.hololens_sensors)
    cfg.settings_log_level = cp.get("settings", "log_level", fallback=cfg.settings_log_level)
    record = cp.getboolean("settings", "record_mode", fallback=False)
    simulation = cp.getboolean("settings", "simulation_mode", fallback=False)
    cfg.settings_mode = "simulation" if simulation else ("record" if record else "live")
    cfg.settings_data_dir = cp.get("settings", "data_dir", fallback=cfg.settings_data_dir)
    cfg.recording_compression = cp.get("settings", "recording_compression", fallback=cfg.recording_compression)

    cfg.hololens_address = cp.get("settings", "hololens_address", fallback=cfg.hololens_address)
    cfg.hololens_user_id = cp.get("settings", "hololens_user_id", fallback=cfg.hololens_user_id)
    cfg.zenoh_enabled = cp.getboolean("settings", "publish_mode", fallback=cfg.zenoh_enabled)

    cfg.hololens_sink_buffer = cp.getint("SINK_MANAGER", "buffer_size", fallback=cfg.hololens_sink_buffer)

    cfg.camera_stream_port_name = cp.get("CAMERA", "port", fallback=cfg.camera_stream_port_name)
    cfg.camera_width = cp.getint("CAMERA", "width", fallback=cfg.camera_width)
    cfg.camera_height = cp.getint("CAMERA", "height", fallback=cfg.camera_height)
    cfg.camera_framerate = cp.getint("CAMERA", "framerate", fallback=cfg.camera_framerate)
    cfg.camera_divisor = cp.getint("CAMERA", "divisor", fallback=cfg.camera_divisor)
    cfg.camera_profile = cp.get("CAMERA", "profile", fallback=cfg.camera_profile)
    cfg.camera_gop_size = cp.getint("CAMERA", "gop_size", fallback=cfg.camera_gop_size)
    cfg.camera_publish_topic = cp.get("CAMERA", "publish_topic", fallback=cfg.camera_publish_topic)

    cfg.depth_stream_port_name = cp.get("DEPTH_CAMERA", "port", fallback=cfg.depth_stream_port_name)
    cfg.depth_sensor = cp.get("DEPTH_CAMERA", "depth_sensor", fallback=cfg.depth_sensor)
    cfg.depth_publish_topic = cp.get("DEPTH_CAMERA", "topic", fallback=cfg.depth_publish_topic)

    cfg.microphone_stream_port_name = cp.get("MICROPHONE", "port", fallback=cfg.microphone_stream_port_name)
    cfg.microphone_publish_topic = cp.get("MICROPHONE", "publish_topic", fallback=cfg.microphone_publish_topic)
    cfg.microphone_profile = cp.get("MICROPHONE", "profile", fallback=cfg.microphone_profile)
    cfg.microphone_chunk = cp.get("MICROPHONE", "chunk", fallback=cfg.microphone_chunk)
    cfg.microphone_level = cp.get("MICROPHONE", "level", fallback=cfg.microphone_level)
    cfg.microphone_decoded = cp.getboolean("MICROPHONE", "decoded", fallback=cfg.microphone_decoded)

    cfg.eet_stream_port_name = cp.get("EET", "port", fallback=cfg.eet_stream_port_name)
    cfg.eet_publish_topic = cp.get("EET", "topic", fallback=cfg.eet_publish_topic)
    cfg.eet_fps = cp.getint("EET", "framerate", fallback=cfg.eet_fps)
    cfg.eet_decoded = cp.getboolean("EET", "decoded", fallback=cfg.eet_decoded)

    cfg.spatial_input_stream_port_name = cp.get("SPATIAL_INPUT", "port", fallback=cfg.spatial_input_stream_port_name)
    cfg.spatial_input_publish_topic = cp.get("SPATIAL_INPUT", "topic", fallback=cfg.spatial_input_publish_topic)
    cfg.spatial_input_decoded = cp.getboolean("SPATIAL_INPUT", "decoded", fallback=cfg.spatial_input_decoded)

    cfg.imu_accelerometer_stream_port_name = cp.get("ACCELEROMETER", "port", fallback=cfg.imu_accelerometer_stream_port_name)
    cfg.imu_accelerometer_topic = cp.get("ACCELEROMETER", "topic", fallback=cfg.imu_accelerometer_topic)
    cfg.imu_accelerometer_mode = cp.get("ACCELEROMETER", "mode", fallback=cfg.imu_accelerometer_mode)
    cfg.imu_gyroscope_stream_port_name = cp.get("GYROSCOPE", "port", fallback=cfg.imu_gyroscope_stream_port_name)
    cfg.imu_gyroscope_topic = cp.get("GYROSCOPE", "topic", fallback=cfg.imu_gyroscope_topic)
    cfg.imu_gyroscope_mode = cp.get("GYROSCOPE", "mode", fallback=cfg.imu_gyroscope_mode)
    cfg.imu_magnetometer_stream_port_name = cp.get("MAGNETOMETER", "port", fallback=cfg.imu_magnetometer_stream_port_name)
    cfg.imu_magnetometer_topic = cp.get("MAGNETOMETER", "topic", fallback=cfg.imu_magnetometer_topic)
    cfg.imu_magnetometer_mode = cp.get("MAGNETOMETER", "mode", fallback=cfg.imu_magnetometer_mode)
    cfg.imu_decoded = cp.getboolean("IMU", "decoded", fallback=cfg.imu_decoded)

    cfg.vlc_profile = cp.get("VLC", "profile", fallback=cfg.vlc_profile)
    cfg.vlc_divisor = cp.getint("VLC", "divisor", fallback=cfg.vlc_divisor)
    cfg.vlc_gop_size = cp.getint("VLC", "gop_size", fallback=cfg.vlc_gop_size)
    cfg.vlc_decoded = cp.getboolean("VLC", "decoded", fallback=cfg.vlc_decoded)
    cfg.vlc_leftfront_topic = cp.get("VLC", "leftfront_topic", fallback=cfg.vlc_leftfront_topic)
    cfg.vlc_leftleft_topic = cp.get("VLC", "leftleft_topic", fallback=cfg.vlc_leftleft_topic)
    cfg.vlc_rightfront_topic = cp.get("VLC", "rightfront_topic", fallback=cfg.vlc_rightfront_topic)
    cfg.vlc_rightright_topic = cp.get("VLC", "rightright_topic", fallback=cfg.vlc_rightright_topic)

    cfg.mqtt_host = cp.get("locator", "mqtt_host", fallback=cfg.mqtt_host)
    cfg.mqtt_port = cp.getint("locator", "mqtt_port", fallback=cfg.mqtt_port)
    cfg.mqtt_username = cp.get("locator", "mqtt_username", fallback=cfg.mqtt_username)
    cfg.mqtt_password = cp.get("locator", "mqtt_password", fallback=cfg.mqtt_password)
    cfg.mqtt_vam_location_topic = cp.get(
        "locator",
        "vam_location_topic",
        fallback=cp.get("locator", "mqtt_topic", fallback=cfg.mqtt_vam_location_topic),
    )
    cfg.mqtt_phone_location_topic_owntrack = cp.get(
        "locator",
        "phone_location_topic_owntrack",
        fallback=cfg.mqtt_phone_location_topic_owntrack,
    )
    cfg.mqtt_heading_topic = cp.get("UNITY", "heading_topic", fallback=cfg.mqtt_heading_topic)
    cfg.mqtt_orientation_topic = cp.get("UNITY", "orientation_topic", fallback=cfg.mqtt_orientation_topic)

    cfg.zenoh_config_file = cp.get("ZENOH", "config_file", fallback=cfg.zenoh_config_file)
    cfg.zenoh_use_shm = cp.getboolean("ZENOH", "use_shm", fallback=cfg.zenoh_use_shm)
    cfg.zenoh_shm_arena_size = cp.getint("ZENOH", "shm_arena_size", fallback=cfg.zenoh_shm_arena_size)


def _apply_env(cfg: MutableAppConfig) -> None:
    """Apply environment variable overrides over file values."""

    for f in fields(cfg):
        env_key = f.name.upper()
        val = os.getenv(env_key)
        if val is not None:
            _set(cfg, f.name, val)


def _apply_cli(cfg: MutableAppConfig, ns: argparse.Namespace) -> None:
    """Apply explicit CLI overrides (highest precedence layer)."""

    for f in fields(cfg):
        raw = getattr(ns, f.name, None)
        if raw is not None:
            _set(cfg, f.name, raw)


def _validate(cfg: MutableAppConfig) -> None:
    """Validate merged mutable config before freezing."""

    if cfg.settings_mode not in {"live", "record", "simulation"}:
        raise ValueError("settings_mode must be one of: live, record, simulation")
    if cfg.observability_metrics_port <= 0:
        raise ValueError("observability_metrics_port must be > 0")
    if cfg.observability_health_port <= 0:
        raise ValueError("observability_health_port must be > 0")


def _split_sensors(raw: str) -> tuple[str, ...]:
    """Parse sensor list string into normalized tuple of sensor tokens.

    Expected format is typically one token per line ending with `;`.
    Lines beginning with `;` or `#` are treated as comments and ignored.
    """

    out: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(";") or stripped.startswith("#"):
            continue
        for token in stripped.split(";"):
            t = token.strip()
            if not t:
                continue
            if t.startswith(";") or t.startswith("#"):
                continue
            out.append(t.lower())
    return tuple(out)


def _has_sensor(sensors: tuple[str, ...], sensor_name: str) -> bool:
    """Check if a sensor token exists (supports suffix options after `:`)."""

    return any(token == sensor_name or token.startswith(f"{sensor_name}:") for token in sensors)


def _build_immutable(cfg: MutableAppConfig) -> AppConfig:
    """Freeze mutable config into immutable typed `AppConfig` tree."""

    sensors = _split_sensors(cfg.hololens_sensors)
    camera_enabled = cfg.camera_enabled and _has_sensor(sensors, "hololens_camera")
    depth_enabled = cfg.depth_enabled and _has_sensor(sensors, "hololens_depth")
    microphone_enabled = cfg.microphone_enabled and _has_sensor(sensors, "hololens_microphone")
    eet_enabled = cfg.eet_enabled and _has_sensor(sensors, "hololens_eet")
    spatial_input_enabled = cfg.spatial_input_enabled and _has_sensor(sensors, "hololens_si")
    imu_enabled = cfg.imu_enabled and _has_sensor(sensors, "hololens_imu")
    vlc_enabled = cfg.vlc_enabled and _has_sensor(sensors, "hololens_vlc")
    vam_location_enabled = _has_sensor(sensors, "vam_location")
    phone_location_enabled = _has_sensor(sensors, "phone_location")
    heading_enabled = _has_sensor(sensors, "unity_heading") or _has_sensor(sensors, "heading")
    orientation_enabled = _has_sensor(sensors, "unity_imu") or _has_sensor(sensors, "orientation")

    hololens_enabled = cfg.hololens_enabled and any(
        [
            camera_enabled,
            depth_enabled,
            microphone_enabled,
            eet_enabled,
            spatial_input_enabled,
            imu_enabled,
            vlc_enabled,
        ]
    )
    mqtt_enabled = cfg.mqtt_enabled and (
        vam_location_enabled or phone_location_enabled or heading_enabled or orientation_enabled
    )
    recording_enabled = cfg.recording_enabled and (cfg.settings_mode == "record")
    session_start_unix_ns = time.time_ns()
    session_start_mono_ns = time.monotonic_ns()
    session_id = str(uuid.uuid4())

    resolved_data_dir = cfg.settings_data_dir
    if cfg.settings_mode == "record":
        record_ts = datetime.fromtimestamp(session_start_unix_ns / 1_000_000_000.0).strftime("%Y%m%d_%H%M%S")
        resolved_data_dir = os.path.join(cfg.settings_data_dir, f"hololens_recording_{record_ts}")

    return AppConfig(
        settings=SettingsConfig(
            log_level=cfg.settings_log_level,
            mode=cfg.settings_mode,
            data_dir=resolved_data_dir,
        ),
        session=SessionConfig(
            session_id=session_id,
            session_start_unix_ns=session_start_unix_ns,
            session_start_mono_ns=session_start_mono_ns,
        ),
        hololens=HololensConfig(
            enabled=hololens_enabled,
            address=cfg.hololens_address,
            user_id=cfg.hololens_user_id,
            sink_buffer=cfg.hololens_sink_buffer,
            sensors=sensors,
            camera=CameraConfig(
                enabled=camera_enabled,
                stream_port_name=cfg.camera_stream_port_name,
                width=cfg.camera_width,
                height=cfg.camera_height,
                framerate=cfg.camera_framerate,
                divisor=cfg.camera_divisor,
                profile=cfg.camera_profile,
                gop_size=cfg.camera_gop_size,
                publish_topic=cfg.camera_publish_topic,
            ),
            depth=DepthConfig(
                enabled=depth_enabled,
                stream_port_name=cfg.depth_stream_port_name,
                depth_sensor=cfg.depth_sensor,
                publish_topic=cfg.depth_publish_topic,
            ),
            microphone=MicrophoneConfig(
                enabled=microphone_enabled,
                stream_port_name=cfg.microphone_stream_port_name,
                publish_topic=cfg.microphone_publish_topic,
                profile=cfg.microphone_profile,
                chunk=cfg.microphone_chunk,
                level=cfg.microphone_level,
                decoded=cfg.microphone_decoded,
            ),
            eet=EETConfig(
                enabled=eet_enabled,
                stream_port_name=cfg.eet_stream_port_name,
                publish_topic=cfg.eet_publish_topic,
                fps=cfg.eet_fps,
                decoded=cfg.eet_decoded,
            ),
            spatial_input=SpatialInputConfig(
                enabled=spatial_input_enabled,
                stream_port_name=cfg.spatial_input_stream_port_name,
                publish_topic=cfg.spatial_input_publish_topic,
                decoded=cfg.spatial_input_decoded,
            ),
            imu=IMUConfig(
                enabled=imu_enabled,
                decoded=cfg.imu_decoded,
                accelerometer=IMUSensorConfig(
                    stream_port_name=cfg.imu_accelerometer_stream_port_name,
                    publish_topic=cfg.imu_accelerometer_topic,
                    mode=cfg.imu_accelerometer_mode,
                ),
                gyroscope=IMUSensorConfig(
                    stream_port_name=cfg.imu_gyroscope_stream_port_name,
                    publish_topic=cfg.imu_gyroscope_topic,
                    mode=cfg.imu_gyroscope_mode,
                ),
                magnetometer=IMUSensorConfig(
                    stream_port_name=cfg.imu_magnetometer_stream_port_name,
                    publish_topic=cfg.imu_magnetometer_topic,
                    mode=cfg.imu_magnetometer_mode,
                ),
            ),
            vlc=VLCConfig(
                enabled=vlc_enabled,
                profile=cfg.vlc_profile,
                divisor=cfg.vlc_divisor,
                gop_size=cfg.vlc_gop_size,
                decoded=cfg.vlc_decoded,
                leftfront=VLCCameraConfig(
                    stream_port_name=cfg.vlc_leftfront_stream_port_name,
                    publish_topic=cfg.vlc_leftfront_topic,
                ),
                leftleft=VLCCameraConfig(
                    stream_port_name=cfg.vlc_leftleft_stream_port_name,
                    publish_topic=cfg.vlc_leftleft_topic,
                ),
                rightfront=VLCCameraConfig(
                    stream_port_name=cfg.vlc_rightfront_stream_port_name,
                    publish_topic=cfg.vlc_rightfront_topic,
                ),
                rightright=VLCCameraConfig(
                    stream_port_name=cfg.vlc_rightright_stream_port_name,
                    publish_topic=cfg.vlc_rightright_topic,
                ),
            ),
        ),
        mqtt=MqttConfig(
            enabled=mqtt_enabled,
            host=cfg.mqtt_host,
            port=cfg.mqtt_port,
            username=cfg.mqtt_username,
            password=cfg.mqtt_password,
            vam_location_topic=cfg.mqtt_vam_location_topic,
            phone_location_topic_owntrack=cfg.mqtt_phone_location_topic_owntrack,
            heading_topic=cfg.mqtt_heading_topic,
            orientation_topic=cfg.mqtt_orientation_topic,
            vam_location_enabled=vam_location_enabled,
            phone_location_enabled=phone_location_enabled,
            heading_enabled=heading_enabled,
            orientation_enabled=orientation_enabled,
        ),
        zenoh=ZenohConfig(
            enabled=cfg.zenoh_enabled,
            config_file=cfg.zenoh_config_file,
            use_shm=cfg.zenoh_use_shm,
            shm_arena_size=cfg.zenoh_shm_arena_size,
        ),
        recording=RecordingConfig(
            enabled=recording_enabled,
            compression=cfg.recording_compression,
        ),
        observability=ObservabilityConfig(
            metrics_enabled=cfg.observability_metrics_enabled,
            metrics_port=cfg.observability_metrics_port,
            health_enabled=cfg.observability_health_enabled,
            health_port=cfg.observability_health_port,
        ),
        runtime=RuntimeConfig(
            restart_max_attempts=cfg.runtime_restart_max_attempts,
            restart_backoff_s=cfg.runtime_restart_backoff_s,
            supervisor_tick_s=cfg.runtime_supervisor_tick_s,
        ),
    )


def load_config() -> AppConfig:
    """Load and validate application config using file/env/CLI precedence."""

    parser = build_parser()
    ns = parser.parse_args()

    cfg = MutableAppConfig()
    _from_file(cfg, ns.config, ns.sensor_config_file)  # file
    _apply_env(cfg)  # env override
    _apply_cli(cfg, ns)  # CLI override (highest)
    _validate(cfg)
    return _build_immutable(cfg)
