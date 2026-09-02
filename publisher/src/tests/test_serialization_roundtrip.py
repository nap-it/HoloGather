from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.contracts.envelope import SensorEnvelope
from src.contracts.types import SensorType
from src.serialization.record_codec import decode_record, encode_record
from src.serialization.zenoh_codec import decode_zenoh, encode_zenoh
from src.storage.reader import StreamReader
from src.storage.recorder import StreamRecorder


class SerializationRoundtripTests(unittest.TestCase):
    def test_zenoh_roundtrip(self) -> None:
        env = SensorEnvelope(
            schema_version=1,
            sensor_type=SensorType.VAM_LOCATION,
            stream_id="vam_location_1",
            session_id="session",
            seq=10,
            ts_unix_ns=1,
            ts_mono_ns=2,
            metadata={"a": 1},
            calibration={"c": {"x": 2}},
            payload=b"abc",
        )
        encoded = encode_zenoh(env)
        decoded = decode_zenoh(encoded)
        self.assertEqual(decoded.stream_id, env.stream_id)
        self.assertEqual(decoded.payload, env.payload)
        self.assertEqual(decoded.metadata, env.metadata)
        self.assertEqual(decoded.calibration, env.calibration)

    def test_record_roundtrip(self) -> None:
        env = SensorEnvelope(
            schema_version=1,
            sensor_type=SensorType.HEADING,
            stream_id="unity_heading_1",
            session_id="session",
            seq=99,
            ts_unix_ns=100,
            ts_mono_ns=200,
            metadata={"b": 2},
            calibration={"k": [1, 2, 3]},
            payload=b"xyz",
        )
        encoded = encode_record(env)
        decoded = decode_record(encoded)
        self.assertEqual(decoded.seq, 99)
        self.assertEqual(decoded.payload, b"xyz")
        self.assertEqual(decoded.metadata, env.metadata)
        self.assertEqual(decoded.calibration, env.calibration)

    def test_stream_file_roundtrip_with_record_length(self) -> None:
        env = SensorEnvelope(
            schema_version=1,
            sensor_type=SensorType.PV,
            stream_id="pv_1",
            session_id="session",
            seq=1,
            ts_unix_ns=100,
            ts_mono_ns=200,
            payload=b"frame",
        )

        for compression in ("none", "lz4"):
            with self.subTest(compression=compression), TemporaryDirectory() as td:
                path = Path(td) / "stream.hlp2"
                writer = StreamRecorder(str(path), compression=compression)
                writer.write(env)
                writer.close()

                raw = path.read_bytes()
                self.assertEqual(int.from_bytes(raw[:4], "big"), len(raw) - 4)

                reader = StreamReader(str(path), compression=compression)
                decoded = reader.read()
                self.assertIsNotNone(decoded)
                self.assertEqual(decoded, env)
                self.assertIsNone(reader.read())
                reader.close()


if __name__ == "__main__":
    unittest.main()
