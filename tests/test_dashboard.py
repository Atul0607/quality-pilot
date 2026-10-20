from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from quality_pilot.dashboard import create_server, load_runs, render_detail, render_index


def _write_run(
    root: Path,
    run_id: str,
    outcome: str,
    *,
    test_cases: list[dict[str, object]] | None = None,
    evidence: list[str] | None = None,
) -> Path:
    directory = root / run_id
    directory.mkdir()
    data = {
        "schema_version": 1,
        "run_id": run_id,
        "outcome": outcome,
        "started_at": "2026-10-20T09:00:00+00:00",
        "finished_at": "2026-10-20T09:00:05+00:00",
        "attempts": [
            {"number": 1, "outcome": outcome, "test_exit_code": 0 if outcome == "passed" else 1}
        ],
        "test_cases": test_cases or [],
        "warnings": [],
        "evidence": evidence or [],
    }
    (directory / "run.json").write_text(json.dumps(data), encoding="utf-8")
    (directory / "report.md").write_text("# saved report\n", encoding="utf-8")
    return directory


class DashboardTests(unittest.TestCase):
    def test_index_shows_actual_run_outcomes_and_surfaces_bad_records(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_run(root, "run-passed", "passed")
            _write_run(root, "run-failed", "failed")
            _write_run(
                root,
                "run-flaky",
                "flaky",
                test_cases=[
                    {
                        "test_id": "checkout::purchase",
                        "outcome": "flaky",
                        "attempts": ["failed", "passed"],
                        "failure": "first attempt failed",
                    }
                ],
            )
            (root / "run-incomplete").mkdir()
            (root / "run-invalid").mkdir()
            (root / "run-invalid" / "run.json").write_text("{", encoding="utf-8")
            (root / "run-future-schema").mkdir()
            (root / "run-future-schema" / "run.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "run_id": "run-future-schema",
                        "started_at": "2026-10-20T09:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            records, warnings = load_runs(root)
            page = render_index(records, warnings)

            self.assertEqual(len(records), 3)
            self.assertIn("Passed runs", page)
            self.assertIn("Failed runs", page)
            self.assertIn("Flaky runs", page)
            self.assertIn("run-flaky", page)
            self.assertIn("run-incomplete: run.json is missing", page)
            self.assertIn("run-invalid: unable to load run record", page)
            self.assertIn("run-future-schema: unable to load run record", page)

    def test_detail_marks_missing_evidence_unavailable_and_shows_flaky_test(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            directory = _write_run(
                root,
                "run-flaky",
                "flaky",
                test_cases=[
                    {
                        "test_id": "checkout::purchase",
                        "outcome": "flaky",
                        "attempts": ["failed", "passed"],
                        "failure": "first attempt failed",
                        "duration_seconds": 0.123,
                    }
                ],
                evidence=["attempts/01/trace.zip"],
            )
            record_path = directory / "run.json"
            data = json.loads(record_path.read_text(encoding="utf-8"))
            data["warnings"] = ["JUnit report was missing."]
            record_path.write_text(json.dumps(data), encoding="utf-8")
            records, warnings = load_runs(root)
            self.assertEqual(warnings, [])

            page = render_detail(records[0])

            self.assertIn("checkout::purchase", page)
            self.assertIn("flaky", page)
            self.assertIn("first attempt failed", page)
            self.assertIn("0.123s", page)
            self.assertIn("JUnit report was missing.", page)
            self.assertIn("attempts/01/trace.zip", page)
            self.assertIn("Unavailable", page)
            self.assertIn("report.md", page)
            self.assertNotIn("/evidence/attempts/01/trace.zip", page)
            self.assertTrue(directory.is_dir())

    def test_dashboard_serves_records_and_only_files_inside_run_directory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_directory = _write_run(
                root, "run-passed", "passed", evidence=["attempts/01/test-output.log"]
            )
            evidence = run_directory / "attempts" / "01" / "test-output.log"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("captured test output", encoding="utf-8")
            (run_directory / "internal.txt").write_text("not evidence", encoding="utf-8")

            server = create_server(root, "127.0.0.1", 0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base_url) as response:
                    index = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("run-passed", index)

                with urlopen(f"{base_url}/runs/run-passed") as response:
                    detail = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("Attempts", detail)

                with urlopen(
                    f"{base_url}/runs/run-passed/evidence/attempts/01/test-output.log"
                ) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("attachment;", response.headers["Content-Disposition"])
                    self.assertEqual(response.read().decode(), "captured test output")

                for unlisted_path in ("run.json", "internal.txt", "../secret.txt"):
                    with self.subTest(path=unlisted_path):
                        try:
                            urlopen(
                                f"{base_url}/runs/run-passed/evidence/{quote(unlisted_path, safe='/')}"
                            )
                        except HTTPError as error:
                            self.assertEqual(error.code, 404)
                            error.close()
                        else:
                            self.fail(f"Unlisted evidence path was served: {unlisted_path}")

                with urlopen(f"{base_url}/runs/run-passed/evidence/report.md") as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read().decode(), "# saved report\n")
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_rejects_missing_artifact_directory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing"
            with self.assertRaises(FileNotFoundError):
                load_runs(missing)


if __name__ == "__main__":
    unittest.main()
