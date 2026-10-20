from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from quality_pilot.compose import DockerCompose


class ComposeTests(unittest.TestCase):
    def test_cleanup_is_scoped_and_does_not_use_compose_down_volumes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            compose = DockerCompose(root / "compose.yaml", "qp-unique")
            calls: list[list[str]] = []

            def fake_run(args: list[str], output_path: Path, timeout: int | None = None) -> int:
                calls.append(args)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    "qp-unique_db-data\n" if "ls" in args else "",
                    encoding="utf-8",
                )
                return 0

            with patch("quality_pilot.compose.DockerCompose.run", side_effect=fake_run):
                result = compose.stop(root / "cleanup.log")

            self.assertEqual(result, 0)
            self.assertIn("down", calls[0])
            self.assertNotIn("--volumes", calls[0])
            self.assertEqual(calls[1][-1], "label=com.docker.compose.project=qp-unique")
            self.assertEqual(calls[2], ["docker", "volume", "rm", "qp-unique_db-data"])


if __name__ == "__main__":
    unittest.main()
