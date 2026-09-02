from __future__ import annotations

import logging
import time
import configparser
import signal
import math

from src.hl2ss_imports import hl2ss

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.zenoh_utils.sensor_zenoh_reader import SensorZenohReader, SensorPacket
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.serialization.packet_codec import decode
from src.serialization.hl2ss_packet import unwrap_sensor_payload


class IMUSubscriber(BaseSubscriberProcess):
    """
    Subscriber for IMU packets encoded with the new wire format.
    Decodes raw IMU struct array using hl2ss.decode_rm_imu.
    Computes orientation terms from IMU samples when possible:
    - accelerometer: pitch/roll
    - magnetometer: heading/yaw
    - gyroscope: integrated yaw/pitch/roll

    Preferred source is HL2SS packet pose (Mode 1), which yields significantly
    better heading/yaw tracking than magnetometer-only heading.
    """

    def __init__(self, config_file: str = None, imu_type: str = "ACCELEROMETER"):
        super().__init__(subscriber_name=f"imu_{imu_type.lower()}")

        self.config_file = config_file
        self.imu_type = imu_type.upper()

        config = configparser.ConfigParser()
        config.read(self.config_file)
        section = "IMU"

        self.topic = config.get(section, "topic", fallback=f"Hololens/{self.imu_type}")
        self.topic += "/" + self.imu_type.capitalize().strip()

        self.max_buffer = config.getint(section, "sensor_queue_size", fallback=25)
        self.logger = logging.getLogger(f"IMUSubscriber[{self.imu_type}]")

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=self.max_buffer)

        self._sensor_subscriber = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )

        # Stateless decoder — create once.
        self._imu_decoder = hl2ss.decode_rm_imu()
        self._gyro_yaw_deg = 0.0
        self._gyro_pitch_deg = 0.0
        self._gyro_roll_deg = 0.0
        self._last_gyro_soc_tick: int | None = None
        self._last_hdg: float = 0.0
        self._last_yaw: float = 0.0
        self._last_pit: float = 0.0
        self._last_rol: float = 0.0

    @staticmethod
    def _wrap_360(angle_deg: float) -> float:
        return (angle_deg + 360.0) % 360.0

    @staticmethod
    def _wrap_180(angle_deg: float) -> float:
        return ((angle_deg + 180.0) % 360.0) - 180.0

    @staticmethod
    def _ang_diff_deg(a: float, b: float) -> float:
        return ((a - b + 180.0) % 360.0) - 180.0

    def _pose_yaw_candidate(self, pose) -> float | None:
        """Extract a robust yaw candidate from pose by trying common conventions."""
        try:
            # Candidate forward vectors for common transform conventions.
            cols = [
                (float(pose[0, 2]), float(pose[1, 2]), float(pose[2, 2])),
                (-float(pose[0, 2]), -float(pose[1, 2]), -float(pose[2, 2])),
                (float(pose[0, 0]), float(pose[1, 0]), float(pose[2, 0])),
                (-float(pose[0, 0]), -float(pose[1, 0]), -float(pose[2, 0])),
            ]
            rows = [
                (float(pose[2, 0]), float(pose[2, 1]), float(pose[2, 2])),
                (-float(pose[2, 0]), -float(pose[2, 1]), -float(pose[2, 2])),
                (float(pose[0, 0]), float(pose[0, 1]), float(pose[0, 2])),
                (-float(pose[0, 0]), -float(pose[0, 1]), -float(pose[0, 2])),
            ]
            vecs = cols + rows
            candidates: list[float] = []
            for vx, _vy, vz in vecs:
                if abs(vx) + abs(vz) < 1e-8:
                    continue
                candidates.append(self._wrap_360(math.degrees(math.atan2(vx, vz))))
            if not candidates:
                return None
            # Choose candidate that best matches current yaw continuity.
            return min(candidates, key=lambda c: abs(self._ang_diff_deg(c, self._yaw_deg)))
        except Exception:
            return None

    def _compute_orientation_from_pose(self, packet_info: dict) -> dict[str, float | None]:
        out: dict[str, float | None] = {
            "heading": None,
            "yaw": None,
            "pitch": None,
            "roll": None,
        }
        pose = packet_info.get("packet_pose")
        if pose is None:
            return out
        try:
            if not hl2ss.is_valid_pose(pose):
                return out
            r00 = float(pose[0, 0]); r10 = float(pose[1, 0]); r20 = float(pose[2, 0])
            r21 = float(pose[2, 1]); r22 = float(pose[2, 2])

            if abs(r20) < 0.9999:
                pitch = math.asin(-r20)
                roll = math.atan2(r21, r22)
                yaw = math.atan2(r10, r00)
            else:
                # Gimbal lock fallback.
                pitch = math.pi / 2.0 if r20 <= -0.9999 else -math.pi / 2.0
                roll = 0.0
                yaw = math.atan2(-float(pose[0, 1]), float(pose[1, 1]))

            yaw_deg = self._wrap_360(math.degrees(yaw))
            out["yaw"] = yaw_deg
            out["heading"] = yaw_deg
            out["pitch"] = self._wrap_180(math.degrees(pitch))
            out["roll"] = self._wrap_180(math.degrees(roll))
            return out
        except Exception:
            return out

    def _resolve_imu_kind(self, metadata: dict) -> str:
        kind = self.imu_type.upper()
        if kind and kind != "ALL":
            return kind
        port_name = str(metadata.get("metadata", {}).get("port_name", "")).upper()
        if "ACCELEROMETER" in port_name:
            return "ACCELEROMETER"
        if "MAGNETOMETER" in port_name:
            return "MAGNETOMETER"
        if "GYROSCOPE" in port_name:
            return "GYROSCOPE"
        topic = str(getattr(self, "topic", "")).upper()
        if "ACCELEROMETER" in topic:
            return "ACCELEROMETER"
        if "MAGNETOMETER" in topic:
            return "MAGNETOMETER"
        if "GYROSCOPE" in topic:
            return "GYROSCOPE"
        return kind

    def _compute_orientation(self, imu, imu_kind: str) -> dict[str, float | None]:
        out: dict[str, float | None] = {
            "heading": None,
            "yaw": None,
            "pitch": None,
            "roll": None,
        }
        if imu.count <= 0:
            return out

        # Use the latest sample in packet for accel/mag derived values.
        x = float(imu.x[-1])
        y = float(imu.y[-1])
        z = float(imu.z[-1])

        if "ACCEL" in imu_kind:
            # Standard tilt estimate from gravity vector.
            roll = math.degrees(math.atan2(y, z))
            pitch = math.degrees(math.atan2(-x, math.sqrt((y * y) + (z * z))))
            out["pitch"] = self._wrap_180(pitch)
            out["roll"] = self._wrap_180(roll)
            return out

        if "MAG" in imu_kind:
            # Magnetic heading in the horizontal plane (no tilt compensation here).
            heading = math.degrees(math.atan2(y, x))
            heading = self._wrap_360(heading)
            out["heading"] = heading
            out["yaw"] = heading
            return out

        if "GYRO" in imu_kind:
            # Integrate angular velocity samples. HL2SS gyro values are rad/s.
            if self._last_gyro_soc_tick is None:
                self._last_gyro_soc_tick = int(imu.soc_ticks[0])
            for i in range(imu.count):
                tick = int(imu.soc_ticks[i])
                dt = max((tick - self._last_gyro_soc_tick) * 1e-7, 0.0)
                self._last_gyro_soc_tick = tick
                if dt <= 0.0:
                    continue
                gx = float(imu.x[i])  # roll rate
                gy = float(imu.y[i])  # pitch rate
                gz = float(imu.z[i])  # yaw rate
                self._gyro_roll_deg += math.degrees(gx) * dt
                self._gyro_pitch_deg += math.degrees(gy) * dt
                self._gyro_yaw_deg += math.degrees(gz) * dt

            out["roll"] = self._wrap_180(self._gyro_roll_deg)
            out["pitch"] = self._wrap_180(self._gyro_pitch_deg)
            out["yaw"] = self._wrap_360(self._gyro_yaw_deg)
            out["heading"] = out["yaw"]
            return out

        return out

    # ------------------------------------------------------------------
    def _publish_orientation_metrics(self, orientation: dict[str, float | None]) -> None:
        hdg = orientation["heading"]
        yaw = orientation["yaw"]
        pit = orientation["pitch"]
        rol = orientation["roll"]

        if hdg is not None:
            self._last_hdg = float(hdg)
        if yaw is not None:
            self._last_yaw = float(yaw)
        if pit is not None:
            self._last_pit = float(pit)
        if rol is not None:
            self._last_rol = float(rol)

        # Short names requested.
        self._emit_metric("hdg", "gauge", self._last_hdg)
        self._emit_metric("yaw", "gauge", self._last_yaw)
        self._emit_metric("pit", "gauge", self._last_pit)
        self._emit_metric("rol", "gauge", self._last_rol)

        # Keep explicit names for compatibility.
        self._emit_metric("imu_heading_deg", "gauge", self._last_hdg)
        self._emit_metric("imu_yaw_deg", "gauge", self._last_yaw)
        self._emit_metric("imu_pitch_deg", "gauge", self._last_pit)
        self._emit_metric("imu_roll_deg", "gauge", self._last_rol)

    # ------------------------------------------------------------------
    def _log_imu_frame(self, metadata: dict, imu, packet_info: dict) -> None:
        ts = metadata.get("ts_unix_ns", 0)
        imu_kind = self._resolve_imu_kind(metadata)
        o = self._compute_orientation_from_pose(packet_info)
        if o["heading"] is None and o["yaw"] is None and o["pitch"] is None and o["roll"] is None:
            o = self._compute_orientation(imu, imu_kind)
        hdg = o["heading"]
        yaw = o["yaw"]
        pit = o["pitch"]
        rol = o["roll"]

        if imu.count == 0:
            self.logger.debug(f"[{self.imu_type}] Empty IMU packet | ts={ts}")
            return

        self._publish_orientation_metrics(o)
        # Keep terminal output quiet; orientation is exported to Prometheus gauges.
        if True: #(int(ts) % 100) == 0:
            self.logger.debug(
                "[%s] heading=%s yaw=%s pit=%s rol=%s",
                imu_kind,
                f"{hdg:.1f}" if hdg is not None else "n/a",
                f"{yaw:.1f}" if yaw is not None else "n/a",
                f"{pit:.1f}" if pit is not None else "n/a",
                f"{rol:.1f}" if rol is not None else "n/a",
            )

    # ------------------------------------------------------------------
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self.logger.info(f"IMU subscriber for '{self.imu_type}' listening on: {self.topic}")
        self._sensor_subscriber.run()

        while not self._stop_event.is_set():
            self._flush_rolling_metrics()
            if self.buffer.is_empty():
                time.sleep(0.001)
                continue

            packet = self.buffer.get()
            if packet is None:
                continue
            self._emit_packet_airtime_ms(packet)
            
            t0 = time.perf_counter()
            try:
                metadata, payload = decode(packet.message)
            except Exception as e:
                self.logger.warning(f"Failed to decode packet: {e}")
                continue
            payload, packet_info = unwrap_sensor_payload(metadata, payload)
            if not payload:
                continue

            try:
                imu = self._imu_decoder.decode(payload)
            except Exception as e:
                self.logger.error(f"Failed decoding IMU payload: {e}")
                continue

            self._log_imu_frame(metadata, imu, packet_info)
            self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)

    # ------------------------------------------------------------------
    def _subscriber_cleanup(self):
        self.logger.info(f"Cleaning up IMU subscriber {self.imu_type}...")
        self._stop_event.set()
        self.buffer.put(None)

    # ------------------------------------------------------------------
    def _request_stop(self):
        self._stop_event.set()
        self._sensor_subscriber.stop()


class IMUFusedSubscriber(BaseSubscriberProcess):
    """Single-process IMU fusion subscriber for accel+gyro+mag at fixed rate."""

    def __init__(self, config_file: str = None, hz: float = 5.0):
        super().__init__(subscriber_name="imu_fused")
        self.config_file = config_file
        self.hz = max(float(hz), 1.0)
        self.topic = "Hololens/IMU/Fused"

        config = configparser.ConfigParser()
        config.read(self.config_file)
        section = "IMU"
        base_topic = config.get(section, "topic", fallback="Hololens/IMU").rstrip("/")
        self.max_buffer = config.getint(section, "sensor_queue_size", fallback=25)

        self._buf_acc = OverWritableMPFIFO[SensorPacket](max_size=self.max_buffer)
        self._buf_gyr = OverWritableMPFIFO[SensorPacket](max_size=self.max_buffer)
        self._buf_mag = OverWritableMPFIFO[SensorPacket](max_size=self.max_buffer)

        self._sub_acc = SensorZenohReader(f"{base_topic}/Accelerometer", self._buf_acc, config_file_path=None)
        self._sub_gyr = SensorZenohReader(f"{base_topic}/Gyroscope", self._buf_gyr, config_file_path=None)
        self._sub_mag = SensorZenohReader(f"{base_topic}/Magnetometer", self._buf_mag, config_file_path=None)

        self._imu_decoder = hl2ss.decode_rm_imu()

        # Latest sensor samples (device axes).
        self._acc: tuple[float, float, float] | None = None
        self._gyr: tuple[float, float, float] | None = None  # rad/s
        self._mag: tuple[float, float, float] | None = None

        # Fused orientation state (deg).
        self._yaw_deg = 0.0
        self._pit_deg = 0.0
        self._rol_deg = 0.0
        self._pose = None

    def set_metrics_bus(self, metrics_queue):
        super().set_metrics_bus(metrics_queue)
        self._sub_acc.set_metrics_bus(metrics_queue)
        self._sub_gyr.set_metrics_bus(metrics_queue)
        self._sub_mag.set_metrics_bus(metrics_queue)

    @staticmethod
    def _wrap_360(angle_deg: float) -> float:
        return (angle_deg + 360.0) % 360.0

    @staticmethod
    def _wrap_180(angle_deg: float) -> float:
        return ((angle_deg + 180.0) % 360.0) - 180.0

    @staticmethod
    def _ang_diff_deg(a: float, b: float) -> float:
        return ((a - b + 180.0) % 360.0) - 180.0

    def _pose_yaw_candidate(self, pose) -> float | None:
        """Extract a robust yaw candidate from pose by trying common conventions."""
        try:
            cols = [
                (float(pose[0, 2]), float(pose[1, 2]), float(pose[2, 2])),
                (-float(pose[0, 2]), -float(pose[1, 2]), -float(pose[2, 2])),
                (float(pose[0, 0]), float(pose[1, 0]), float(pose[2, 0])),
                (-float(pose[0, 0]), -float(pose[1, 0]), -float(pose[2, 0])),
            ]
            rows = [
                (float(pose[2, 0]), float(pose[2, 1]), float(pose[2, 2])),
                (-float(pose[2, 0]), -float(pose[2, 1]), -float(pose[2, 2])),
                (float(pose[0, 0]), float(pose[0, 1]), float(pose[0, 2])),
                (-float(pose[0, 0]), -float(pose[0, 1]), -float(pose[0, 2])),
            ]
            vecs = cols + rows
            candidates: list[float] = []
            for vx, _vy, vz in vecs:
                if abs(vx) + abs(vz) < 1e-8:
                    continue
                candidates.append(self._wrap_360(math.degrees(math.atan2(vx, vz))))
            if not candidates:
                return None
            return min(candidates, key=lambda c: abs(self._ang_diff_deg(c, self._yaw_deg)))
        except Exception:
            return None

    def _drain_sensor(self, sensor_name: str, buf: OverWritableMPFIFO[SensorPacket]) -> None:
        while not buf.is_empty():
            packet = buf.get()
            if packet is None:
                return
            self._emit_packet_airtime_ms(packet)
            try:
                metadata, payload = decode(packet.message)
                payload, packet_info = unwrap_sensor_payload(metadata, payload)
                if not payload:
                    continue
                pose = packet_info.get("packet_pose")
                if pose is not None:
                    try:
                        if hl2ss.is_valid_pose(pose):
                            self._pose = pose
                    except Exception:
                        pass
                imu = self._imu_decoder.decode(payload)
            except Exception:
                continue
            if imu.count <= 0:
                continue
            x = float(imu.x[-1]); y = float(imu.y[-1]); z = float(imu.z[-1])
            if sensor_name == "acc":
                self._acc = (x, y, z)
            elif sensor_name == "gyr":
                self._gyr = (x, y, z)
            elif sensor_name == "mag":
                self._mag = (x, y, z)

    def _fuse_once(self, dt_s: float) -> tuple[float, float, float, float]:
        # 1) Gyro integration prediction.
        if self._gyr is not None:
            gx, gy, gz = self._gyr
            self._rol_deg = self._wrap_180(self._rol_deg + math.degrees(gx) * dt_s)
            self._pit_deg = self._wrap_180(self._pit_deg + math.degrees(gy) * dt_s)
            self._yaw_deg = self._wrap_360(self._yaw_deg + math.degrees(gz) * dt_s)

        alpha_pr = 0.98

        # 2) Accelerometer correction for pitch/roll.
        if self._acc is not None:
            ax, ay, az = self._acc
            rol_acc = math.degrees(math.atan2(ay, az))
            pit_acc = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
            self._rol_deg = self._wrap_180(alpha_pr * self._rol_deg + (1.0 - alpha_pr) * rol_acc)
            self._pit_deg = self._wrap_180(alpha_pr * self._pit_deg + (1.0 - alpha_pr) * pit_acc)

        # 3) Yaw correction from pose when available and coherent with gyro.
        pose_used = False
        if self._pose is not None:
            yaw_pose = self._pose_yaw_candidate(self._pose)
            if yaw_pose is not None:
                err = self._ang_diff_deg(yaw_pose, self._yaw_deg)
                # Reject pose if it strongly disagrees with integrated yaw.
                if abs(err) <= 90.0:
                    self._yaw_deg = self._wrap_360(self._yaw_deg + 0.15 * err)
                    pose_used = True

        # 4) Magnetometer correction fallback (tilt compensated).
        if (not pose_used) and (self._mag is not None):
            mx, my, mz = self._mag
            pit = math.radians(self._pit_deg)
            rol = math.radians(self._rol_deg)
            mx2 = mx * math.cos(pit) + mz * math.sin(pit)
            my2 = (
                mx * math.sin(rol) * math.sin(pit)
                + my * math.cos(rol)
                - mz * math.sin(rol) * math.cos(pit)
            )
            yaw_mag = math.degrees(math.atan2(my2, mx2))
            yaw_mag = self._wrap_360(yaw_mag)
            dy = self._ang_diff_deg(yaw_mag, self._yaw_deg)
            self._yaw_deg = self._wrap_360(self._yaw_deg + 0.05 * dy)

        hdg = self._yaw_deg
        return hdg, self._yaw_deg, self._pit_deg, self._rol_deg

    def _publish_orientation_metrics(self, hdg: float, yaw: float, pit: float, rol: float) -> None:
        self._emit_metric("hdg", "gauge", float(hdg))
        self._emit_metric("yaw", "gauge", float(yaw))
        self._emit_metric("pit", "gauge", float(pit))
        self._emit_metric("rol", "gauge", float(rol))
        self._emit_metric("imu_heading_deg", "gauge", float(hdg))
        self._emit_metric("imu_yaw_deg", "gauge", float(yaw))
        self._emit_metric("imu_pitch_deg", "gauge", float(pit))
        self._emit_metric("imu_roll_deg", "gauge", float(rol))

    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self._sub_acc.run()
        self._sub_gyr.run()
        self._sub_mag.run()
        self.logger.info("IMU fused subscriber listening at 5Hz on accel+gyro+mag topics")

        period_s = 1.0 / self.hz
        last_t = time.perf_counter()
        next_t = last_t + period_s

        while not self._stop_event.is_set():
            self._drain_sensor("acc", self._buf_acc)
            self._drain_sensor("gyr", self._buf_gyr)
            self._drain_sensor("mag", self._buf_mag)
            self._flush_rolling_metrics()

            now = time.perf_counter()
            if now < next_t:
                time.sleep(min(0.005, next_t - now))
                continue

            dt_s = max(now - last_t, 1e-3)
            last_t = now
            next_t = now + period_s

            t0 = time.perf_counter()
            hdg, yaw, pit, rol = self._fuse_once(dt_s)
            self._publish_orientation_metrics(hdg, yaw, pit, rol)
            self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)
            self.logger.info("hdg=%.1f° yaw=%.1f° pit=%.1f° rol=%.1f°", hdg, yaw, pit, rol)

    def _request_stop(self):
        self._stop_event.set()

    def _subscriber_cleanup(self):
        try:
            self._sub_acc.stop()
            self._sub_gyr.stop()
            self._sub_mag.stop()
        except Exception:
            pass
