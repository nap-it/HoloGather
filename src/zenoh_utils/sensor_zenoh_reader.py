import time
import logging
from dataclasses import dataclass
from typing import Optional

import zenoh  # type: ignore

from src.utils.overwritable_mp_fifo import OverWritableMPFIFO


@dataclass
class SensorPacket:
    """Raw packet as received from Zenoh, ready for packet_codec.decode()."""
    arrival_timestamp: float
    message: bytes


class SensorZenohReader:
    """
    Callback-based Zenoh subscriber that buffers incoming raw packets.

    Each received sample is stored as a SensorPacket(arrival_timestamp, message)
    where message is the raw bytes produced by packet_codec.encode().
    Callers consume from sensor_queue and call stop() when done.
    """

    def __init__(
        self,
        topic_name: str,
        sensor_queue: OverWritableMPFIFO,
        config_file_path: Optional[str] = None,
    ):
        self.key_expr     = topic_name
        self.sensor_queue = sensor_queue
        self.logger       = logging.getLogger("SensorZenohReader")
        self.metrics_bus  = None

        self.zenoh_config = zenoh.Config()
        if config_file_path is not None:
            self.zenoh_config = zenoh.Config.from_file(config_file_path)

    def set_metrics_bus(self, bus) -> None:
        self.metrics_bus = bus

    def _emit_metric(self, name: str, typ: str, value: float) -> None:
        if self.metrics_bus is not None:
            from src.observability.metrics_emitter import emit_metric
            emit_metric(self.metrics_bus, "subscriber", self.key_expr, name, typ, value)

    def run(self) -> None:
        self.session      = zenoh.open(self.zenoh_config)
        self.alive        = True
        self.subscription = self.session.declare_subscriber(
            self.key_expr, self._on_data
        )

    def _on_data(self, sample: zenoh.Sample) -> None:
        if not self.alive:
            return
        try:
            raw: bytes = sample.payload.to_bytes()
            self._emit_metric("frames_received", "counter", 1.0)
            self._emit_metric("bytes_received", "counter", float(len(raw)))
            
            self.sensor_queue.put(
                SensorPacket(arrival_timestamp=time.time(), message=raw)
            )
        except Exception as e:
            self.logger.error("SensorZenohReader callback error: %s", e)

    def stop(self) -> None:
        self.alive = False
        try:
            self.subscription.undeclare()
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass
