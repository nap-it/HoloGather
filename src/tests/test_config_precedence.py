from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from src.config.center import load_config


class ConfigPrecedenceTests(unittest.TestCase):
    def test_file_env_cli_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            sensor_conf = f"{td}/sensors.ini"

            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        log_level = WARNING
                        hololens_address = 192.0.2.10
                        hololens_user_id = 5
                        record_mode = False
                        simulation_mode = False
                        publish_mode = True
                        data_dir = ./recordings

                        [sensors]
                        list = hololens_camera;
                        """
                    )
                )

            with open(sensor_conf, "w", encoding="utf-8") as f:
                f.write("[locator]\nmqtt_host = file-host\nmqtt_port = 1883\n")

            env = {
                "SETTINGS_LOG_LEVEL": "DEBUG",
                "MQTT_HOST": "env-host",
            }

            argv = [
                "prog",
                "--config",
                app_conf,
                "--sensor-config-file",
                sensor_conf,
                "--settings-log-level",
                "ERROR",
                "--mqtt-host",
                "cli-host",
            ]

            with patch.dict(os.environ, env, clear=False), patch("sys.argv", argv):
                cfg = load_config()

            self.assertEqual(cfg.settings.log_level, "ERROR")
            self.assertEqual(cfg.mqtt.host, "cli-host")

    def test_camera_only_sensor_list_disables_other_services(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            sensor_conf = f"{td}/sensors.ini"

            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [sensors]
                        list =
                            hololens_camera;
                            ; hololens_depth;
                            ; vam_location;
                            ; unity_heading;

                        [settings]
                        log_level = INFO
                        hololens_address = 192.0.2.10
                        hololens_user_id = 1
                        record_mode = False
                        simulation_mode = False
                        publish_mode = False
                        data_dir = /tmp/recordings
                        """
                    )
                )

            with open(sensor_conf, "w", encoding="utf-8") as f:
                f.write("[locator]\nmqtt_host = 127.0.0.1\nmqtt_port = 1883\n")

            argv = [
                "prog",
                "--config",
                app_conf,
                "--sensor-config-file",
                sensor_conf,
            ]

            with patch("sys.argv", argv):
                cfg = load_config()

            self.assertEqual(cfg.hololens.sensors, ("hololens_camera",))
            self.assertTrue(cfg.hololens.enabled)
            self.assertTrue(cfg.hololens.camera.enabled)
            self.assertFalse(cfg.hololens.depth.enabled)
            self.assertFalse(cfg.hololens.microphone.enabled)
            self.assertFalse(cfg.hololens.eet.enabled)
            self.assertFalse(cfg.hololens.spatial_input.enabled)
            self.assertFalse(cfg.hololens.imu.enabled)
            self.assertFalse(cfg.hololens.vlc.enabled)
            self.assertFalse(cfg.mqtt.vam_location_enabled)
            self.assertFalse(cfg.mqtt.heading_enabled)
            self.assertFalse(cfg.mqtt.enabled)
            self.assertFalse(cfg.zenoh.enabled)
            self.assertFalse(cfg.recording.enabled)

    def test_sensor_comment_lines_do_not_enable_depth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            sensor_conf = f"{td}/sensors.ini"

            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [sensors]
                        list =
                            ; hololens_depth;
                            hololens_camera;
                            ; hololens_imu:sensor=all;

                        [settings]
                        log_level = INFO
                        hololens_address = 192.0.2.10
                        hololens_user_id = 1
                        record_mode = False
                        simulation_mode = False
                        publish_mode = False
                        data_dir = /tmp/recordings
                        """
                    )
                )

            with open(sensor_conf, "w", encoding="utf-8") as f:
                f.write("[CAMERA]\nport=PERSONAL_VIDEO\n")

            argv = ["prog", "--config", app_conf, "--sensor-config-file", sensor_conf]
            with patch("sys.argv", argv):
                cfg = load_config()

            self.assertEqual(cfg.hololens.sensors, ("hololens_camera",))
            self.assertTrue(cfg.hololens.camera.enabled)
            self.assertFalse(cfg.hololens.depth.enabled)

    def test_boolean_override_precedence_for_zenoh_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            sensor_conf = f"{td}/sensors.ini"

            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        log_level = INFO
                        hololens_address = 192.0.2.10
                        hololens_user_id = 1
                        record_mode = False
                        simulation_mode = False
                        publish_mode = False
                        data_dir = /tmp/recordings

                        [sensors]
                        list = hololens_camera;
                        """
                    )
                )

            with open(sensor_conf, "w", encoding="utf-8") as f:
                f.write("[CAMERA]\nport=PERSONAL_VIDEO\n")

            argv = [
                "prog",
                "--config",
                app_conf,
                "--sensor-config-file",
                sensor_conf,
                "--zenoh-enabled",
                "false",
            ]
            env = {"ZENOH_ENABLED": "true"}

            with patch.dict(os.environ, env, clear=False), patch("sys.argv", argv):
                cfg = load_config()

            # File says false, env says true, CLI says false -> CLI wins.
            self.assertFalse(cfg.zenoh.enabled)

    def test_record_mode_resolves_session_subfolder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            sensor_conf = f"{td}/sensors.ini"

            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        log_level = INFO
                        record_mode = True
                        simulation_mode = False
                        publish_mode = False
                        data_dir = /tmp/recordings

                        [sensors]
                        list = hololens_camera;
                        """
                    )
                )

            with open(sensor_conf, "w", encoding="utf-8") as f:
                f.write("[CAMERA]\nport=PERSONAL_VIDEO\n")

            argv = ["prog", "--config", app_conf, "--sensor-config-file", sensor_conf]
            with patch("sys.argv", argv):
                cfg = load_config()

            self.assertTrue(cfg.settings.data_dir.startswith("/tmp/recordings/hololens_recording_"))


if __name__ == "__main__":
    unittest.main()
