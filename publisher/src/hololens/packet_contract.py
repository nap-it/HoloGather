"""Utilities for exporting rich hl2ss packet contracts."""

from __future__ import annotations

import struct
from typing import Any

import numpy as np

from src.hololens.hl2ss_imports import hl2ss, hl2ss_lnm


HL2SS_PACKET_CONTENT_TYPE = "application/x-hl2ss.packet"


def _to_builtin(value: Any) -> Any:
    """Convert numpy/object-rich values into msgpack-safe Python primitives."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return {
            "__ndarray__": True,
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "data": value.tobytes(),
        }
    if isinstance(value, dict):
        return {str(k): _to_builtin(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_builtin(v) for v in value]
    if hasattr(value, "__dict__"):
        out = {"__class__": value.__class__.__name__}
        out.update({k: _to_builtin(v) for k, v in vars(value).items() if not k.startswith("_")})
        return out
    return str(value)


def pack_frame(frame: Any) -> bytes:
    """Pack full hl2ss packet when possible; fallback to raw frame payload bytes."""
    payload = getattr(frame, "payload", None)
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        return b""
    try:
        return bytes(hl2ss.pack_packet(frame))
    except Exception:
        return bytes(payload)


def base_packet_metadata(frame: Any, *, port_name: str) -> dict[str, Any]:
    """Build packet-level metadata common to all hl2ss streams."""
    payload = getattr(frame, "payload", b"")
    pose = getattr(frame, "pose", None)
    pose_list = None
    if pose is not None:
        try:
            pose_list = np.asarray(pose, dtype=np.float32).reshape((4, 4)).flatten().tolist()
        except Exception:
            pose_list = None
    return {
        "port_name": port_name,
        "packet_timestamp": int(getattr(frame, "timestamp", 0)),
        "payload_size": len(payload) if isinstance(payload, (bytes, bytearray, memoryview)) else 0,
        "has_pose": bool(pose is not None),
        "pose": pose_list,
    }


def parse_pv_metadata(payload: bytes) -> dict[str, Any]:
    if len(payload) < 80:
        return {}
    m = payload[-80:]
    return {
        "pv_focal_length": np.frombuffer(m, dtype=np.float32, offset=0, count=2).tolist(),
        "pv_principal_point": np.frombuffer(m, dtype=np.float32, offset=8, count=2).tolist(),
        "pv_exposure_time": int(np.frombuffer(m, dtype=np.uint64, offset=16, count=1)[0]),
        "pv_exposure_compensation": np.frombuffer(m, dtype=np.uint64, offset=24, count=2).tolist(),
        "pv_lens_position": int(np.frombuffer(m, dtype=np.uint32, offset=40, count=1)[0]),
        "pv_focus_state": int(np.frombuffer(m, dtype=np.uint32, offset=44, count=1)[0]),
        "pv_iso_speed": int(np.frombuffer(m, dtype=np.uint32, offset=48, count=1)[0]),
        "pv_white_balance": int(np.frombuffer(m, dtype=np.uint32, offset=52, count=1)[0]),
        "pv_iso_gains": np.frombuffer(m, dtype=np.float32, offset=56, count=2).tolist(),
        "pv_white_balance_gains": np.frombuffer(m, dtype=np.float32, offset=64, count=3).tolist(),
        "pv_resolution": np.frombuffer(m, dtype=np.uint16, offset=76, count=2).tolist(),
    }


def parse_vlc_metadata(payload: bytes) -> dict[str, Any]:
    if len(payload) < 24:
        return {}
    m = payload[-24:]
    return {
        "vlc_sensor_ticks": int(struct.unpack_from("<Q", m, 0)[0]),
        "vlc_exposure": int(struct.unpack_from("<Q", m, 8)[0]),
        "vlc_gain": int(struct.unpack_from("<I", m, 16)[0]),
    }


def parse_depth_metadata(payload: bytes) -> dict[str, Any]:
    if len(payload) < 8:
        return {}
    return {"depth_sensor_ticks": int(struct.unpack_from("<Q", payload, len(payload) - 8)[0])}


def parse_imu_metadata(payload: bytes) -> dict[str, Any]:
    return {"imu_sample_count": int(len(payload) // 32)}


def parse_si_metadata(payload: bytes) -> dict[str, Any]:
    if len(payload) < 4:
        return {}
    flags = int(struct.unpack_from("<I", payload, 0)[0])
    return {
        "si_valid_flags": flags,
        "si_head_pose_valid": bool(flags & 0x01),
        "si_eye_ray_valid": bool(flags & 0x02),
        "si_hand_left_valid": bool(flags & 0x04),
        "si_hand_right_valid": bool(flags & 0x08),
    }


def parse_eet_metadata(payload: bytes) -> dict[str, Any]:
    if len(payload) < 8:
        return {}
    flags = int(struct.unpack_from("<I", payload, len(payload) - 4)[0])
    return {
        "eet_valid_flags": flags,
        "eet_calibration_valid": bool(flags & 0x01),
        "eet_combined_ray_valid": bool(flags & 0x02),
        "eet_left_ray_valid": bool(flags & 0x04),
        "eet_right_ray_valid": bool(flags & 0x08),
        "eet_left_openness_valid": bool(flags & 0x10),
        "eet_right_openness_valid": bool(flags & 0x20),
        "eet_vergence_distance_valid": bool(flags & 0x40),
    }


def fetch_calibration(
    host: str,
    *,
    port_name: str,
    pv_width: int | None = None,
    pv_height: int | None = None,
    pv_framerate: int | None = None,
) -> dict[str, Any]:
    """Download mode-2 calibration for streams that expose it."""
    sockopt = hl2ss_lnm.create_sockopt(settimeout=2.0)
    try:
        port = int(getattr(hl2ss.StreamPort, port_name))
    except Exception:
        return {}

    try:
        if port in (
            int(hl2ss.StreamPort.RM_VLC_LEFTFRONT),
            int(hl2ss.StreamPort.RM_VLC_LEFTLEFT),
            int(hl2ss.StreamPort.RM_VLC_RIGHTFRONT),
            int(hl2ss.StreamPort.RM_VLC_RIGHTRIGHT),
        ):
            return {"rm_vlc": _to_builtin(hl2ss_lnm.download_calibration_rm_vlc(host, port, sockopt=sockopt))}
        if port == int(hl2ss.StreamPort.RM_DEPTH_AHAT):
            return {
                "rm_depth_ahat": _to_builtin(
                    hl2ss_lnm.download_calibration_rm_depth_ahat(host, port, sockopt=sockopt)
                )
            }
        if port == int(hl2ss.StreamPort.RM_DEPTH_LONGTHROW):
            return {
                "rm_depth_longthrow": _to_builtin(
                    hl2ss_lnm.download_calibration_rm_depth_longthrow(host, port, sockopt=sockopt)
                )
            }
        if port in (
            int(hl2ss.StreamPort.RM_IMU_ACCELEROMETER),
            int(hl2ss.StreamPort.RM_IMU_GYROSCOPE),
            int(hl2ss.StreamPort.RM_IMU_MAGNETOMETER),
        ):
            return {"rm_imu": _to_builtin(hl2ss_lnm.download_calibration_rm_imu(host, port, sockopt=sockopt))}
        if port == int(hl2ss.StreamPort.PERSONAL_VIDEO):
            return {
                "pv": _to_builtin(
                    hl2ss_lnm.download_calibration_pv(
                        host,
                        port,
                        sockopt=sockopt,
                        width=int(pv_width or 1920),
                        height=int(pv_height or 1080),
                        framerate=int(pv_framerate or 30),
                    )
                )
            }
    except Exception as exc:
        return {"error": str(exc)}
    return {}
