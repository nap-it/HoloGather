from __future__ import annotations

import argparse
import configparser
import os
import re
import sys
from dataclasses import dataclass, field, fields
from typing import Dict, List, Optional


def _split_specs(s: Optional[str]) -> List[str]:
    """Split semicolon/pipe spec strings while ignoring commented lines."""
    if not s:
        return []
    out: List[str] = []
    for line in s.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(";") or stripped.startswith("#"):
            continue
        for part in stripped.replace("|", ";").split(";"):
            p = part.strip()
            if not p:
                continue
            if p.startswith(";") or p.startswith("#"):
                continue
            out.append(p)
    return out


def _parse_params(s: str) -> Dict[str, str]:
    d: Dict[str, str] = {}
    if not s:
        return d
    for pair in s.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
            d[k.strip()] = v.strip()
        else:
            d[pair] = "true"
    return d


def _parse_sensor_spec(spec: str) -> "SensorSpec":
    if ":" in spec:
        name, rest = spec.split(":", 1)
        return SensorSpec(name=name.strip(), params=_parse_params(rest))
    return SensorSpec(name=spec.strip(), params={})


def _to_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_first(*keys: str) -> Optional[str]:
    for key in keys:
        val = os.getenv(key)
        if val is not None:
            return val
    return None


@dataclass
class SensorSpec:
    name: str
    params: Dict[str, str] = field(default_factory=dict)


@dataclass
class AppConfig:
    sensors_enable: List[str] = field(default_factory=list)
    sensors_list: Optional[str] = None
    sensors_specs: List[str] = field(default_factory=list)

    log_level: str = "DEBUG"
    sensor_config_file: str = "configs/app_config.ini"
    hololens_user_id: str = "-1"
    record_mode: bool = False
    simulation_mode: bool = False
    publish_mode: bool = False
    data_dir: str = "."
    metrics_port: int = 8000

    config_path: Optional[str] = None

    def sensors_all(self) -> List[SensorSpec]:
        specs: List[SensorSpec] = []
        for n in self.sensors_enable:
            n = n.strip()
            if n:
                specs.append(SensorSpec(name=n))
        for s in _split_specs(self.sensors_list):
            specs.append(_parse_sensor_spec(s))
        for s in self.sensors_specs:
            specs.append(_parse_sensor_spec(s))
        return specs

    def to_summary_line(self) -> str:
        items = []
        for f in fields(self):
            items.append((f.name, str(getattr(self, f.name))))
        return ", ".join([f'({k}, "{v}")' for k, v in items])

    def to_config_parser(self) -> configparser.ConfigParser:
        cp = configparser.ConfigParser()
        cp.add_section("settings")
        cp.set("settings", "log_level", self.log_level)
        cp.set("settings", "sensor_config_file", self.sensor_config_file)
        cp.set("settings", "hololens_user_id", self.hololens_user_id)
        cp.set("settings", "record_mode", str(self.record_mode))
        cp.set("settings", "simulation_mode", str(self.simulation_mode))
        cp.set("settings", "publish_mode", str(self.publish_mode))
        cp.set("settings", "data_dir", self.data_dir)
        cp.set("settings", "metrics_port", str(self.metrics_port))

        cp.add_section("sensors")
        if self.sensors_enable:
            cp.set("sensors", "enable", ", ".join(self.sensors_enable))
        if self.sensors_list:
            cp.set("sensors", "list", self.sensors_list)
        for i, spec in enumerate(self.sensors_specs):
            cp.set("sensors", f"sensor{i}", spec)
        return cp


def load_file(path: Optional[str]) -> AppConfig:
    cfg = AppConfig()
    if not path:
        return cfg
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"Config file is not readable: {path}")

    cp = configparser.ConfigParser()
    read_ok = cp.read(path)
    if not read_ok:
        raise FileNotFoundError(f"Config file not found or unreadable: {path}")

    cfg.config_path = path
    g = lambda sec, key, fallback=None: cp.get(sec, key, fallback=fallback) if cp.has_section(sec) else fallback

    enable_raw = g("sensors", "enable", "")
    cfg.sensors_enable = [x.strip() for x in re.split(r"[,\s]+", enable_raw) if x.strip() and not x.strip().startswith(("#", ";"))]
    cfg.sensors_list = g("sensors", "list")

    if cp.has_section("sensors"):
        indexed: List[tuple[int, str]] = []
        pat = re.compile(r"sensor(\d+)$")
        for k, v in cp.items("sensors"):
            m = pat.match(k)
            if m and v.strip():
                indexed.append((int(m.group(1)), v.strip()))
        cfg.sensors_specs = [v for _, v in sorted(indexed, key=lambda x: x[0])]

    cfg.log_level = g("settings", "log_level", cfg.log_level)
    cfg.sensor_config_file = g("settings", "sensor_config_file", cfg.sensor_config_file)
    cfg.hololens_user_id = g("settings", "hololens_user_id", cfg.hololens_user_id)
    cfg.record_mode = _to_bool(g("settings", "record_mode"), cfg.record_mode)
    cfg.simulation_mode = _to_bool(g("settings", "simulation_mode"), cfg.simulation_mode)
    cfg.publish_mode = _to_bool(g("settings", "publish_mode"), cfg.publish_mode)
    cfg.data_dir = g("settings", "data_dir", cfg.data_dir)
    cfg.metrics_port = int(g("settings", "metrics_port", cfg.metrics_port))
    return cfg


def apply_env(cfg: AppConfig) -> None:
    env_enable = _env_first("sensors_enable", "SENSORS_ENABLE")
    if env_enable is not None:
        cfg.sensors_enable = [x.strip() for x in re.split(r"[,\s]+", env_enable) if x.strip()]

    sensors_list = _env_first("sensors_list", "SENSORS_LIST")
    if sensors_list is not None:
        cfg.sensors_list = sensors_list

    env_specs: List[tuple[int, str]] = []
    for k, v in os.environ.items():
        m = re.fullmatch(r"(?:sensors_sensor|SENSORS_SENSOR)(\d+)", k)
        if m and v.strip():
            env_specs.append((int(m.group(1)), v.strip()))
    if env_specs:
        cfg.sensors_specs = [v for _, v in sorted(env_specs, key=lambda x: x[0])]

    log_level = _env_first("settings_log_level", "SETTINGS_LOG_LEVEL")
    if log_level is not None:
        cfg.log_level = log_level

    sensor_cfg = _env_first("sensor_config_file", "SENSOR_CONFIG_FILE")
    if sensor_cfg is not None:
        cfg.sensor_config_file = sensor_cfg

    user_id = _env_first("hololens_user_id", "HOLOLENS_USER_ID")
    if user_id is not None:
        cfg.hololens_user_id = user_id

    record_mode = _env_first("record_mode", "RECORD_MODE")
    if record_mode is not None:
        cfg.record_mode = _to_bool(record_mode, cfg.record_mode)

    simulation_mode = _env_first("simulation_mode", "SIMULATION_MODE")
    if simulation_mode is not None:
        cfg.simulation_mode = _to_bool(simulation_mode, cfg.simulation_mode)

    publish_mode = _env_first("publish_mode", "PUBLISH_MODE")
    if publish_mode is not None:
        cfg.publish_mode = _to_bool(publish_mode, cfg.publish_mode)

    data_dir = _env_first("data_dir", "DATA_DIR")
    if data_dir is not None:
        cfg.data_dir = data_dir
    metrics_port = _env_first("metrics_port", "METRICS_PORT")
    if metrics_port is not None:
        cfg.metrics_port = int(metrics_port)


def _validate_config(cfg: AppConfig) -> None:
    valid_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    if str(cfg.log_level).upper() not in valid_levels:
        raise ValueError(f"Invalid log_level '{cfg.log_level}'. Expected one of: {sorted(valid_levels)}")

    if cfg.record_mode and cfg.simulation_mode:
        raise ValueError("record_mode and simulation_mode cannot both be true")
    if int(cfg.metrics_port) <= 0:
        raise ValueError("metrics_port must be > 0")

    if cfg.config_path and not os.path.isfile(cfg.config_path):
        raise FileNotFoundError(f"Loaded config path does not exist: {cfg.config_path}")
    if not os.path.isfile(cfg.sensor_config_file):
        raise FileNotFoundError(f"sensor_config_file not found: {cfg.sensor_config_file}")

    specs = cfg.sensors_all()
    if not specs:
        raise ValueError("No sensors configured. Add at least one sensor in [sensors].")

    valid_sensor_names = {
        "hololens_camera", "hololens_pv_sub", "camera_sub",
        "hololens_depth", "depth_camera", "hl2_depth",
        "hololens_imu", "imu", "hl2_imu",
        "hololens_eet", "eye_tracking", "hl2_eet",
        "hololens_si", "spatial_input", "hl2_si",
        "hololens_microphone", "microphone", "hl2_microphone",
        "hololens_vlc", "vlc", "hl2_vlc",
        "depth_correlator", "depth_correlator_subscriber",
        "vam_location", "hololens_vam_location",
        "phone_location", "hololens_phone_location",
        "unity_heading", "heading", "hololens_heading",
        "unity_imu", "orientation", "hololens_unity_imu",
        "map", "gps_map", "map_view",
    }
    imu_names = {"hololens_imu", "imu", "hl2_imu"}
    vlc_names = {"hololens_vlc", "vlc", "hl2_vlc"}

    for spec in specs:
        name = spec.name.strip().lower()
        if name not in valid_sensor_names:
            raise ValueError(f"Unknown sensor '{spec.name}'")
        if name in imu_names and "sensor" not in spec.params:
            raise ValueError(f"Sensor '{spec.name}' requires parameter sensor=accelerometer|gyroscope|magnetometer")
        if name in vlc_names and "sensor" not in spec.params:
            raise ValueError(f"Sensor '{spec.name}' requires parameter sensor=leftleft|leftfront|rightfront|rightright")


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="Sensor Hub",
        description="Parses [sensors] in outputs-style and exposes SensorSpec list.",
    )
    p.add_argument("--config", default="configs/app_config.ini")

    p.add_argument("--sensors_enable", help="Comma/space list of sensor names")
    p.add_argument("--sensors_list", help="Semicolon/pipe separated sensor specs")
    p.add_argument("--sensors_sensor", action="append", help="One-per-line style: name[:k=v,k=v]")

    p.add_argument("--log_level")
    p.add_argument("--sensor_config_file")
    p.add_argument("--hololens_user_id")
    p.add_argument("--record_mode", choices=["true", "false", "1", "0", "yes", "no", "on", "off"])
    p.add_argument("--simulation_mode", choices=["true", "false", "1", "0", "yes", "no", "on", "off"])
    p.add_argument("--publish_mode", choices=["true", "false", "1", "0", "yes", "no", "on", "off"])
    p.add_argument("--data_dir")
    p.add_argument("--metrics_port")
    return p


def from_everywhere(ns: argparse.Namespace) -> AppConfig:
    cfg = load_file(ns.config)
    apply_env(cfg)

    for name, value in vars(ns).items():
        if name == "config" or value in (None, [], ""):
            continue
        if name == "sensors_sensor":
            cfg.sensors_specs.extend(value)
            continue
        if name in {"record_mode", "simulation_mode", "publish_mode"}:
            setattr(cfg, name, _to_bool(str(value)))
            continue
        if name in {"metrics_port"}:
            setattr(cfg, name, int(value))
            continue
        if hasattr(cfg, name):
            setattr(cfg, name, str(value))

    # exact-index CLI support: --sensors_sensor0=..., --sensors_sensor1=...
    exacts: Dict[int, str] = {}
    pat_eq = re.compile(r"--sensors_sensor(\d+)=(.+)")
    pat_kw = re.compile(r"--sensors_sensor(\d+)$")
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        m = pat_eq.match(a)
        if m:
            exacts[int(m.group(1))] = m.group(2)
            i += 1
            continue
        m = pat_kw.match(a)
        if m and i + 1 < len(argv):
            exacts[int(m.group(1))] = argv[i + 1]
            i += 2
            continue
        i += 1
    if exacts:
        cfg.sensors_specs = [v for _, v in sorted(exacts.items(), key=lambda x: x[0])]

    _validate_config(cfg)
    return cfg
