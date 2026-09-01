from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from src.utils.config import build_argparser, from_everywhere


class SubscriberConfigValidationTests(unittest.TestCase):
    def test_comment_lines_in_sensors_list_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        log_level = DEBUG
                        sensor_config_file = {app_conf}

                        [sensors]
                        list =
                            hololens_camera;
                            ; hololens_depth;
                            ; vam_location;
                        """.format(app_conf=app_conf)
                    )
                )

            parser = build_argparser()
            ns = parser.parse_args(["--config", app_conf])
            cfg = from_everywhere(ns)
            names = [s.name for s in cfg.sensors_all()]
            self.assertEqual(names, ["hololens_camera"])

    def test_env_overrides_file_and_cli_overrides_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        log_level = INFO
                        publish_mode = false
                        sensor_config_file = {app_conf}

                        [sensors]
                        list = hololens_camera;
                        """.format(app_conf=app_conf)
                    )
                )

            env = {"PUBLISH_MODE": "true"}
            parser = build_argparser()
            ns = parser.parse_args(["--config", app_conf, "--publish_mode", "false"])
            with patch.dict(os.environ, env, clear=False):
                cfg = from_everywhere(ns)
            self.assertFalse(cfg.publish_mode)

    def test_unknown_sensor_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        sensor_config_file = {app_conf}

                        [sensors]
                        list = mystery_sensor;
                        """.format(app_conf=app_conf)
                    )
                )
            parser = build_argparser()
            ns = parser.parse_args(["--config", app_conf])
            with self.assertRaises(ValueError):
                from_everywhere(ns)

    def test_missing_imu_sensor_param_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        sensor_config_file = {app_conf}

                        [sensors]
                        list = hololens_imu;
                        """.format(app_conf=app_conf)
                    )
                )
            parser = build_argparser()
            ns = parser.parse_args(["--config", app_conf])
            with self.assertRaises(ValueError):
                from_everywhere(ns)

    def test_vam_location_sensor_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_conf = f"{td}/app.ini"
            with open(app_conf, "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        [settings]
                        sensor_config_file = {app_conf}

                        [sensors]
                        list = vam_location;
                        """.format(app_conf=app_conf)
                    )
                )
            parser = build_argparser()
            ns = parser.parse_args(["--config", app_conf])
            cfg = from_everywhere(ns)
            self.assertEqual([s.name for s in cfg.sensors_all()], ["vam_location"])


if __name__ == "__main__":
    unittest.main()
