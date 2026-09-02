"""Enum contracts shared across runtime modules."""

from __future__ import annotations

from enum import Enum


class SensorType(str, Enum):
    """Canonical sensor type labels used in `SensorEnvelope`."""

    PV = "pv"
    DEPTH = "depth"
    DEPTH_CORRELATED = "depth_correlated"
    VLC = "vlc"
    IMU = "imu"
    MICROPHONE = "microphone"
    SPATIAL_INPUT = "spatial_input"
    EET = "eet"
    VAM_LOCATION = "vam_location"
    PHONE_LOCATION = "phone_location"
    HEADING = "heading"


class ControlAction(str, Enum):
    """Control-plane actions sent over `control_bus`."""

    STOP = "stop"
    RELOAD = "reload"
    DRAIN = "drain"


class HealthState(str, Enum):
    """Service health states reported to `health_bus`."""

    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
