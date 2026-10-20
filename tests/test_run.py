from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from quality_pilot.config import Config
from quality_pilot.run import execute_run


class FakeCompose:
    def __init__(self, compose_file: Path, project_name: str) -> None:
        self.attempt_number = 0

    def config_check(self, output_path: Path) -> int:
        return 0

    def start(self, services: tuple[str, ...], output_path: Path, timeout: int) -> int:
        self.attempt_number += 1
        output_path.write_text("services ready\n", encoding="utf-8")
        return 0

    def test(
        self,
        service: str,
        command: tuple[str, ...],
        artifacts_dir: Path,
        output_path: Path,
        timeout: int,
    ) -> int:
        if self.attempt_number == 1:
            outcome = '<failure message="first attempt failed" />'
            exit_code = 1
        else:
            outcome = ""
            exit_code = 0
        (artifacts_dir / "junit.xml").write_text(
            '<testsuite><testcase classname="checkout" name="purchase">'
            f"{outcome}</testcase></testsuite>",
            encoding="utf-8",
        )
        output_path.write_text("test output\n", encoding="utf-8")
        return exit_code

    def logs(self, output_path: Path) -> int:
        output_path.write_text("application logs\n", encoding="utf-8")
        return 0

    def stop(self, output_path: Path) -> int:
        output_path.write_text("resources cleaned\n", encoding="utf-8")
        return 0


class RunTests(unittest.TestCase):
    def test_retries_in_fresh_attempts_and_reports_flaky_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            compose_file = root / "compose.yaml"
            compose_file.write_text("services: {}\n", encoding="utf-8")
            config = Config(
                compose_file=compose_file,
                app_services=("app",),
                test_service="e2e",
                test_command=("pytest", "--junitxml={artifacts}/junit.xml"),
                retries=1,
                timeout_seconds=60,
                artifacts_dir=root / "runs",
                junit_report="junit.xml",
            )
            fake = FakeCompose(compose_file, "qp-test")
            with patch("quality_pilot.run.DockerCompose", return_value=fake) as factory:
                run_dir, result = execute_run(config)

            self.assertEqual(factory.call_count, 1)
            self.assertEqual(result["outcome"], "flaky")
            self.assertEqual(result["test_cases"][0]["outcome"], "flaky")
            self.assertEqual(len(result["attempts"]), 2)
            self.assertTrue((run_dir / "run.json").is_file())
            self.assertTrue((run_dir / "report.md").is_file())
            self.assertTrue((run_dir / "attempts/01/services.log").is_file())
            self.assertTrue((run_dir / "attempts/02/services.log").is_file())


if __name__ == "__main__":
    unittest.main()
