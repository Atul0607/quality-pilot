from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from quality_pilot.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_loads_valid_config(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            config_path = root / "quality-pilot.toml"
            config_path.write_text(
                'version = 1\ncompose_file = "compose.yaml"\n'
                'app_services = ["app"]\ntest_service = "e2e"\n'
                'test_command = ["pytest", "--junitxml={artifacts}/junit.xml"]\n',
                encoding="utf-8",
            )
            config = load_config(config_path)
            self.assertEqual(config.app_services, ("app",))
            self.assertEqual(config.retries, 2)
            self.assertEqual(config.junit_report, "junit.xml")

    def test_rejects_unknown_keys(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            config_path = root / "quality-pilot.toml"
            config_path.write_text(
                'version = 1\ncompose_file = "compose.yaml"\n'
                'app_services = ["app"]\ntest_service = "e2e"\n'
                'test_command = ["pytest"]\nretrys = 2\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "Unknown configuration key"):
                load_config(config_path)

    def test_rejects_report_path_traversal(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
            config_path = root / "quality-pilot.toml"
            config_path.write_text(
                'version = 1\ncompose_file = "compose.yaml"\n'
                'app_services = ["app"]\ntest_service = "e2e"\n'
                'test_command = ["pytest"]\njunit_report = "../outside.xml"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "relative path"):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
