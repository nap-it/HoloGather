import multiprocessing as mp
import logging
import signal
import time
from collections import deque
from statistics import mean

class BaseSubscriberProcess(mp.Process):
    """
    Base class for subscriber processes.

    Subclasses must implement:
        - _subscriber_loop()
        - _subscriber_cleanup()

    Subclasses may implement:
        - _request_stop()  (parent side)
    """

    def __init__(self, subscriber_name: str):
        super().__init__()
        self.subscriber_name = subscriber_name
        self.name = subscriber_name
        self._stop_event = mp.Event()
        self.logger = logging.getLogger(self.subscriber_name)
        self.metrics_bus = None
        
        self._airtime_window = deque(maxlen=60)
        self._processing_window = deque(maxlen=60)
        self._last_metric_emit = time.monotonic()

    def set_metrics_bus(self, metrics_queue: mp.Queue):
        """Inject metrics bus into the process and its delegates."""
        self.metrics_bus = metrics_queue
        # Auto-inject into SensorZenohReader if it exists as `self._sensor_subscriber`
        if hasattr(self, '_sensor_subscriber') and hasattr(self._sensor_subscriber, 'set_metrics_bus'):
            self._sensor_subscriber.set_metrics_bus(metrics_queue)
        # Some subscribers use `_sensor_reader` naming instead.
        if hasattr(self, "_sensor_reader") and hasattr(self._sensor_reader, "set_metrics_bus"):
            self._sensor_reader.set_metrics_bus(metrics_queue)

    def _emit_metric(self, metric_name: str, metric_type: str, value: float) -> None:
        """Emit one subscriber-local metric if metrics bus is configured."""
        if self.metrics_bus is None:
            return
        try:
            from src.observability.metrics_emitter import emit_metric

            emit_metric(
                self.metrics_bus,
                "subscriber",
                getattr(self, "topic", self.subscriber_name),
                metric_name,
                metric_type,
                value,
            )
        except Exception:
            # Metrics must never break the hot path.
            return

    def _emit_packet_airtime_ms(self, packet) -> float:
        """Emit queue airtime in milliseconds for one consumed SensorPacket."""
        arrival_ts = getattr(packet, "arrival_timestamp", None)
        if arrival_ts is None:
            return 0.0
        airtime_ms = max((time.time() - float(arrival_ts)) * 1000.0, 0.0)
        self._airtime_window.append(airtime_ms)
        return airtime_ms

    def _emit_processing_ms(self, proc_ms: float) -> None:
        """Add processing ms to the rolling window."""
        self._processing_window.append(proc_ms)

    def _flush_rolling_metrics(self) -> None:
        """Emit rolling averages to the metrics bus once per second."""
        now = time.monotonic()
        if now - self._last_metric_emit >= 1.0:
            if self._airtime_window:
                self._emit_metric("airtime_ms", "gauge", float(mean(self._airtime_window)))
            if self._processing_window:
                self._emit_metric("processing_ms", "gauge", float(mean(self._processing_window)))
            self._last_metric_emit = now

    # ----------------------------------------------------------------------
    def run(self):
        # Ignore SIGINT in child so parent owns shutdown signalling.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.logger.info(f"[{self.subscriber_name}] Subscriber started (PID {self.pid})")
        try:
            self._subscriber_loop()
        except KeyboardInterrupt:
            self.logger.info(f"[{self.subscriber_name}] Subscriber interrupted, exiting cleanly.")
        except Exception as e:
            if self._stop_event.is_set():
                self.logger.info(f"[{self.subscriber_name}] Stopping gracefully.")
            else:
                self.logger.error(f"Subscriber crashed: {e}", exc_info=True)
        finally:
            try:
                self._subscriber_cleanup()
            except KeyboardInterrupt:
                self.logger.info(f"[{self.subscriber_name}] Cleanup interrupted; exiting.")
            self.logger.info(f"[{self.subscriber_name}] Subscriber exited.")

    # ----------------------------------------------------------------------
    def stop(self):
        """Parent-side stop request."""
        self.logger.debug(f"[{self.subscriber_name}] stop() called.")
        try:
            self._request_stop()
        except Exception as e:
            self.logger.warning(f"Error in _request_stop(): {e}")
        self._stop_event.set()

    # ----------------------------------------------------------------------
    def _request_stop(self):
        """Optional hook for subclasses to unblock readers or sockets."""
        pass

    # ----------------------------------------------------------------------
    def _subscriber_loop(self):
        raise NotImplementedError()

    # ----------------------------------------------------------------------
    def _subscriber_cleanup(self):
        raise NotImplementedError()
