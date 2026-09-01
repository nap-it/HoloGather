"""
Subscriber Factory

Creates concrete subscriber instances based on SensorSpec configuration.
"""

from typing import Optional
from multiprocessing import Queue

from src.utils.config import AppConfig, SensorSpec
from src.handlers.base_subscriber import BaseSubscriberProcess
from src.handlers.rgb_camera_subscriber import RGBCameraSubscriber
from src.handlers.depth_camera_subscriber import DepthCameraSubscriber
from src.handlers.imu_subscriber import IMUFusedSubscriber, IMUSubscriber
from src.handlers.eet_subscriber import EETSubscriber
from src.handlers.spatial_input_subscriber import SpatialInputSubscriber
from src.handlers.vlc_subscriber import VLCSubscriber
from src.handlers.microphone_subscriber import MicrophoneSubscriber
from src.handlers.depth_correlated_subscriber import DepthCorrelatedSubscriber
from src.handlers.vam_location_subscriber import VamLocationSubscriber
from src.handlers.heading_subscriber import HeadingSubscriber
from src.handlers.unity_imu_subscriber import UnityImuSubscriber
from src.handlers.map_subscriber import MapSubscriber


class SubscriberFactory:
    """Creates concrete subscriber instances based on configuration."""

    @staticmethod
    def create_subscriber(spec: SensorSpec, cfg: AppConfig, audio_queue: Optional[Queue] = None) -> BaseSubscriberProcess:
        name = spec.name.lower().strip()

        if name in ("hololens_camera", "hololens_pv_sub", "camera_sub"):
            return RGBCameraSubscriber(config_file=cfg.sensor_config_file)
        
        elif name in ('hololens_depth', 'depth_camera', 'hl2_depth'):
            return DepthCameraSubscriber(config_file=cfg.sensor_config_file)
        
        elif name in ('hololens_imu', 'imu', 'hl2_imu'):
            if 'sensor' not in spec.params:
                raise ValueError(f"Sensor '{spec.name}' requires a 'sensor' parameter (e.g., sensor=accelerometer)")
            imu_type = spec.params.get("sensor").strip()
            if imu_type.lower() == "all":
                return IMUFusedSubscriber(config_file=cfg.sensor_config_file, hz=5.0)
            return IMUSubscriber(
                config_file=cfg.sensor_config_file,
                imu_type=imu_type,
            )
        
        elif name in ('hololens_eet', 'eye_tracking', 'hl2_eet'):
            return EETSubscriber(config_file=cfg.sensor_config_file)
        
        elif name in ('hololens_si', 'spatial_input', 'hl2_si'):
            return SpatialInputSubscriber(config_file=cfg.sensor_config_file)
        
        elif name in ('hololens_microphone', 'microphone', 'hl2_microphone'):
            return MicrophoneSubscriber(
                config_file=cfg.sensor_config_file,
                audio_queue=audio_queue
            )
        
        elif name in ('hololens_vlc', 'vlc', 'hl2_vlc'):
            if 'sensor' not in spec.params:
                raise ValueError(f"Sensor '{spec.name}' requires a 'sensor' parameter (e.g., sensor=RM_VLC_LEFT_LEFT)")
            vlc_type = spec.params.get("sensor").strip()
            return VLCSubscriber(
                config_file=cfg.sensor_config_file,
                vlc_type=vlc_type,
            )
        
        elif name in ('depth_correlator', 'depth_correlator_subscriber'):
            return DepthCorrelatedSubscriber(config_file=cfg.sensor_config_file)
            
        elif name in ("vam_location", "hololens_vam_location"):
            return VamLocationSubscriber(config_file=cfg.sensor_config_file, section="VAM_LOCATION")
        elif name in ("phone_location", "hololens_phone_location"):
            return VamLocationSubscriber(config_file=cfg.sensor_config_file, section="PHONE_LOCATION")
            
        elif name in ('unity_heading', 'heading', 'hololens_heading'):
            return HeadingSubscriber(config_file=cfg.sensor_config_file)
        
        elif name in ('unity_imu', 'orientation', 'hololens_unity_imu'):
            return UnityImuSubscriber(config_file=cfg.sensor_config_file)

        elif name in ('map', 'gps_map', 'map_view'):
            return MapSubscriber(config_file=cfg.sensor_config_file)

        raise ValueError(f"Unknown subscriber type '{spec.name}'")
