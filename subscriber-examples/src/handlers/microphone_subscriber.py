from __future__ import annotations

import os
import sys
import logging
import configparser
import queue
import time
import signal

from src.hl2ss_imports import hl2ss

from multiprocessing import Queue

from src.handlers.base_subscriber import BaseSubscriberProcess
from src.zenoh_utils.sensor_zenoh_reader import SensorZenohReader, SensorPacket
from src.utils.overwritable_mp_fifo import OverWritableMPFIFO
from src.serialization.packet_codec import decode
from src.serialization.hl2ss_packet import unwrap_sensor_payload


class MicrophoneSubscriber(BaseSubscriberProcess):
    """
    Subscriber for microphone packets encoded with the new wire format.
    Decodes raw AAC payload using hl2ss.decode_microphone and forwards the
    resulting float32 audio array to the shared audio_queue for streaming.
    """

    def __init__(self, config_file: str, mic_id: str = "1", audio_queue: Queue = None):
        super().__init__(subscriber_name=f"MicrophoneSubscriber_{mic_id}")

        self.config_file = config_file
        self.mic_id = mic_id
        self.audio_queue = audio_queue

        config = configparser.ConfigParser()
        config.read(self.config_file)

        section = "MICROPHONE"
        self.topic = config.get(section, "topic", fallback="Hololens/Microphone")
        self.max_size = config.getint(section, "sensor_queue_size", fallback=10)
        
        prof_str = config.get(section, "profile", fallback="AAC_24000")
        self.profile = getattr(hl2ss.AudioProfile, prof_str, hl2ss.AudioProfile.AAC_24000)

        self.buffer = OverWritableMPFIFO[SensorPacket](max_size=self.max_size)

        self._sensor_reader = SensorZenohReader(
            topic_name=self.topic,
            sensor_queue=self.buffer,
            config_file_path=None,
        )

        # Lazy-initialised on first packet (needs profile from metadata).
        self._mic_decoder = None

    # ------------------------------------------------------------------
    def _process_packet(self, metadata: dict, payload: bytes, packet_count: int) -> None:
        if self._mic_decoder is None:
            try:
                self._mic_decoder = hl2ss.decode_microphone(
                    self.profile, hl2ss.AACLevel.L2
                )
            except Exception as e:
                self.logger.error(f"Could not create microphone decoder: {e}")
                return

        try:
            audio_array = self._mic_decoder.decode(payload)
        except Exception as e:
            self.logger.warning(f"Microphone decode error: {e}")
            return

        if self.audio_queue is not None:
            try:
                self.audio_queue.put_nowait(audio_array.tobytes())
            except Exception:
                pass  # queue full — drop frame

        if packet_count % 100 == 0:
            self.logger.info(
                f"[Mic {self.mic_id}] Packet {packet_count} | "
                f"ts={metadata.get('ts_unix_ns')} | ch={metadata.get('metadata', {}).get('ch', '?')} | "
                f"sr={metadata.get('metadata', {}).get('sr', '?')} | shape={audio_array.shape}"
            )

    # ------------------------------------------------------------------
    def _subscriber_loop(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        self._sensor_reader.run()
        self.logger.info(f"Microphone subscriber running. Topic: {self.topic}")

        packet_count = 0

        while not self._stop_event.is_set():
            self._flush_rolling_metrics()
            try:
                packet = self.buffer.get()
            except queue.Empty:
                time.sleep(0.001)
                continue

            if packet is None:
                continue
            self._emit_packet_airtime_ms(packet)

            t0 = time.perf_counter()
            try:
                metadata, payload = decode(packet.message)
            except Exception as e:
                self.logger.warning(f"Failed to decode packet: {e}")
                continue
            payload, _pkt = unwrap_sensor_payload(metadata, payload)
            if not payload:
                continue

            self._process_packet(metadata, payload, packet_count)
            self._emit_processing_ms((time.perf_counter() - t0) * 1000.0)
            packet_count += 1

    # ------------------------------------------------------------------
    def _request_stop(self):
        self.logger.info("Requesting Zenoh reader stop...")
        self._stop_event.set()

    # ------------------------------------------------------------------
    def _subscriber_cleanup(self):
        self.logger.info("Cleaning up microphone subscriber...")
        try:
            self._sensor_reader.stop()
        except Exception as e:
            self.logger.debug(f"Error stopping sensor reader: {e}")
        self.logger.info("Cleanup complete.")
