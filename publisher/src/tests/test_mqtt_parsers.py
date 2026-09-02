from __future__ import annotations

import unittest

from src.mqtt.phone_location_parser import parse_phone_location
from src.mqtt.unity_heading_parser import parse_heading
from src.mqtt.unity_imu_parser import parse_unity_imu
from src.mqtt.vam_location_parser import parse_vam_location


class ParserTests(unittest.TestCase):
    def test_parse_vam_location(self) -> None:
        payload = b'{"vamParameters":{"basicContainer":{"referencePosition":{"latitude":40.0,"longitude":-8.0}}}}'
        out = parse_vam_location(payload)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["latitude"], 40.0)

    def test_parse_phone_location(self) -> None:
        payload = b'{"lat":40.1,"lon":-8.2,"alt":12.5,"vel":3.2}'
        out = parse_phone_location(payload)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["latitude"], 40.1)
        self.assertEqual(out["longitude"], -8.2)
        self.assertEqual(out["altitude"], 12.5)
        self.assertEqual(out["speed_mps"], 3.2)

    def test_parse_heading(self) -> None:
        out = parse_heading(b"123.4")
        self.assertEqual(out, {"heading": 123.4})

    def test_parse_unity_imu_json(self) -> None:
        out = parse_unity_imu(b'{"yaw":260.1883,"pitch":14.5152,"roll":356.6423}')
        self.assertIsNotNone(out)
        assert out is not None
        self.assertAlmostEqual(out["yaw"], 260.1883, places=4)
        self.assertAlmostEqual(out["pitch"], 14.5152, places=4)
        self.assertAlmostEqual(out["roll"], 356.6423, places=4)


if __name__ == "__main__":
    unittest.main()
