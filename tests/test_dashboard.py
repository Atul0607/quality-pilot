from __future__ import annotations

import json
from datetime import date, timedelta
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
    started_at: str = "2026-10-20T09:00:00+00:00",
    finished_at: str = "2026-10-20T09:00:05+00:00",
) -> Path:
    directory = root / run_id
    directory.mkdir()
    data = {
        "schema_version": 1,
        "run_id": run_id,
        "outcome": outcome,
        "started_at": started_at,
        "finished_at": finished_at,
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
            _write_run(
                root,
                "run-failed",
                "failed",
                test_cases=[
                    {
                        "test_id": "checkout::payment",
                        "outcome": "failed",
                        "attempts": ["failed"],
                        "failure": "payment declined",
                    }
                ],
            )
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
            page = render_index(records, warnings, period="all")

            self.assertEqual(len(records), 3)
            self.assertIn('color-scheme:dark', page)
            self.assertIn('class="sidebar"', page)
            self.assertIn('data-theme-choice="light"', page)
            self.assertIn('data-theme-choice="dark"', page)
            self.assertIn('aria-label="Use light mode"', page)
            self.assertIn('aria-label="Use dark mode"', page)
            self.assertIn('title="Switch to light theme"', page)
            self.assertIn('title="Switch to dark theme"', page)
            self.assertIn(".has-tooltip::after", page)
            self.assertIn(
                ".has-tooltip:hover,.has-tooltip:focus-visible { z-index:30; }",
                page,
            )
            self.assertIn(
                ".has-tooltip:hover::after,.has-tooltip:focus-visible::after",
                page,
            )
            self.assertIn('data-tooltip="Switch to light theme"', page)
            self.assertIn('data-tooltip="Switch to dark theme"', page)
            self.assertIn('title="View quality metrics and reliability trends"', page)
            self.assertIn('title="Browse and filter recorded test runs"', page)
            for tooltip in (
                "Percentage of recorded runs that passed in this date range",
                "Total recorded runs in this date range",
                "Unique tests that had inconsistent results in this date range",
                "Median duration of runs with timing data in this date range",
            ):
                self.assertIn(f'title="{tooltip}"', page)
            self.assertIn(
                "a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible",
                page,
            )
            self.assertIn("th { color:#8993a6; font-size:10px;", page)
            self.assertIn("td { color:#c6ceda; font-size:12px;", page)
            self.assertNotIn("theme-toggle", page)
            self.assertIn('const storageKey = "qualitypilot-theme"', page)
            self.assertIn("localStorage.getItem(storageKey)", page)
            self.assertIn('localStorage.setItem(storageKey, theme)', page)
            self.assertIn("Test reliability", page)
            self.assertIn("Pass rate", page)
            self.assertIn('<option value="all" selected>All dates</option>', page)
            overview_date_form = page.split(
                '<form class="filter date-filter"', 1
            )[1].split("</form>", 1)[0]
            self.assertIn('data-auto-apply="true"', page)
            self.assertNotIn("<button", overview_date_form)
            self.assertIn('periodSelect.addEventListener("change"', page)
            self.assertIn("dateForm.requestSubmit()", page)
            self.assertNotIn("Local run history", page)
            self.assertNotIn("3 records · All dates", page)
            self.assertNotIn("Recent runs", page)
            self.assertNotIn('aria-label="Filter recent runs"', page)
            self.assertNotIn("Showing 1 of 1 runs", page)
            self.assertIn("<strong>33%</strong>", page)
            self.assertIn("Flaky tests", page)
            self.assertIn("unique tests marked flaky", page)
            self.assertIn("5.0s", page)
            self.assertIn('role="img"', page)
            self.assertIn('<polygon points="', page)
            self.assertIn('fill="url(#chart-fill)"', page)
            self.assertIn("0.0% passing", page)
            self.assertRegex(
                page,
                r'<text x="[^"]+" y="[^"]+" text-anchor="middle" fill="#8993a6" '
                r'font-size="9">[0-9]{2}:[0-9]{2}</text>',
            )
            self.assertIn('href="/runs?status=passed&amp;period=all"', page)
            self.assertIn('href="/runs?status=flaky_tests&amp;period=all"', page)
            self.assertIn('href="/runs?status=timed_runs&amp;period=all"', page)
            self.assertEqual(page.count('class="stat stat-link has-tooltip"'), 4)
            self.assertIn(
                '<small>across runs with timing data</small></a>', page
            )
            self.assertIn('href="/runs?status=all&amp;period=all"', page)
            self.assertIn('aria-label="Monitor"', page)
            self.assertIn(
                '<a class="has-tooltip active" aria-current="page" '
                'data-tooltip="View quality metrics and reliability trends" '
                'href="/?status=all&amp;period=all"',
                page,
            )
            self.assertIn('aria-current="page"', page)
            self.assertIn('href="/runs?status=all&amp;period=all"', page)
            sidebar_nav = page.split('<nav class="side-nav"', 1)[1].split("</nav>", 1)[0]
            self.assertEqual(sidebar_nav.count("<a "), 2)
            self.assertIn(">Overview</span>", sidebar_nav)
            self.assertIn(">Test runs</span>", sidebar_nav)
            self.assertNotIn("Flaky tests", sidebar_nav)
            self.assertIn("<span class=\"nav-count\">3</span>", page)
            self.assertNotIn("<section class=\"panel attention\">", page)
            self.assertIn("run-flaky", page)
            self.assertIn("run-incomplete: run.json is missing", page)
            self.assertIn("run-invalid: unable to load run record", page)
            self.assertIn("run-future-schema: unable to load run record", page)
            runs_page = render_index(records, warnings, period="all", runs_page=True)
            self.assertNotIn("Needs attention", runs_page)
            self.assertNotIn("payment declined", runs_page)
            self.assertNotIn("3 records · All dates", runs_page)
            run_summary = runs_page.split(
                '<section class="run-summary"', 1
            )[1].split("</section>", 1)[0]
            self.assertIn('aria-label="Run results summary"', run_summary)
            self.assertIn("<span>All runs</span><strong>3</strong>", run_summary)
            self.assertIn("<span>Passed runs</span><strong>1</strong>", run_summary)
            self.assertIn("<span>Failed runs</span><strong>1</strong>", run_summary)
            self.assertIn(
                'title="Total number of runs in the selected date range"',
                run_summary,
            )
            self.assertIn(
                'title="Runs that passed in the selected date range"',
                run_summary,
            )
            self.assertIn(
                'title="Runs that failed in the selected date range"',
                run_summary,
            )
            self.assertEqual(run_summary.count('data-tooltip="'), 3)
            self.assertEqual(run_summary.count('<div class="stat run-summary-card'), 3)
            self.assertNotIn("<a ", run_summary)
            self.assertNotIn("<button", run_summary)
            self.assertIn(
                ".run-summary-card.passed span,.run-summary-card.passed strong",
                runs_page,
            )
            self.assertIn(
                ".run-summary-card.failed span,.run-summary-card.failed strong",
                runs_page,
            )
            self.assertNotIn("<h2>Test runs</h2>", runs_page)
            self.assertIn(
                ".run-summary { display:grid; "
                "grid-template-columns:repeat(3,minmax(0,1fr));",
                runs_page,
            )
            self.assertIn(".stat strong { display:block;", runs_page)
            self.assertIn('href="/runs?status=all&amp;period=all"', runs_page)
            self.assertIn(
                '<a class="has-tooltip active" aria-current="page" '
                'data-tooltip="Browse and filter recorded test runs" '
                'href="/runs?status=all&amp;period=all" '
                'title="Browse and filter recorded test runs">',
                runs_page,
            )
            self.assertIn("Showing 1-3 of 3 runs", runs_page)
            self.assertIn('aria-label="Run results summary"', runs_page)
            runs_date_form = runs_page.split(
                '<form class="filter date-filter"', 1
            )[1].split("</form>", 1)[0]
            self.assertNotIn('data-auto-apply="true"', runs_page)
            self.assertIn('<button type="submit">Apply</button>', runs_date_form)
            combined_filter = runs_page.split(
                '<form class="filter date-filter"', 1
            )[1].split("</form>", 1)[0]
            self.assertIn('<select id="period" name="period">', combined_filter)
            self.assertIn('<select id="status" name="status">', combined_filter)
            self.assertEqual(combined_filter.count('type="submit"'), 1)
            self.assertNotIn('value="flaky_tests"', combined_filter)
            self.assertNotIn('value="timed_runs"', combined_filter)
            for result in ("all", "passed", "failed", "flaky", "error", "cancelled", "unknown"):
                self.assertIn(f'value="{result}"', combined_filter)
            self.assertGreater(
                runs_page.index("Showing 1-3 of 3 runs"),
                runs_page.index("</table>"),
            )
            custom_runs_page = render_index(
                records,
                warnings,
                "failed",
                period="custom",
                start_date="2026-10-20",
                end_date="2026-10-20",
                runs_page=True,
            )
            self.assertIn('<option value="custom" selected>', custom_runs_page)
            self.assertIn('name="start_date" value="2026-10-20"', custom_runs_page)
            self.assertIn('name="end_date" value="2026-10-20"', custom_runs_page)

            failed_page = render_index(
                records, warnings, "failed", period="all", runs_page=True
            )
            self.assertIn("Showing 1-1 of 1 runs", failed_page)
            self.assertIn("run-failed", failed_page)
            self.assertNotIn("run-passed", failed_page)
            self.assertIn('option value="failed" selected', failed_page)
            flaky_tests_page = render_index(
                records, warnings, "flaky_tests", period="all", runs_page=True
            )
            self.assertIn(
                '<a class="has-tooltip active" aria-current="page" '
                'data-tooltip="Browse and filter recorded test runs" '
                'href="/runs?status=all&amp;period=all" '
                'title="Browse and filter recorded test runs">',
                flaky_tests_page,
            )
            self.assertIn("run-flaky", flaky_tests_page)
            self.assertNotIn("run-failed", flaky_tests_page)
            self.assertIn('option value="all" selected', flaky_tests_page)
            self.assertNotIn("Needs attention", flaky_tests_page)
            self.assertNotIn(
                "payment declined",
                render_index(records, warnings, "passed", period="all", runs_page=True),
            )

    def test_run_list_paginates_large_result_sets_and_preserves_filters(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index in range(100):
                outcome = "failed" if index % 2 == 0 else "passed"
                _write_run(root, f"many-run-{index:03d}", outcome)
            records, warnings = load_runs(root)

            first_page = render_index(
                records, warnings, "failed", period="all", runs_page=True
            )
            self.assertIn("Showing 1-10 of 50 runs", first_page)
            self.assertIn("Page 1 of 5", first_page)
            self.assertEqual(first_page.count('class="run-link"'), 10)
            self.assertIn(
                'href="/runs?status=failed&amp;period=all&amp;page=2">',
                first_page,
            )
            self.assertIn('aria-label="Next page"', first_page)

            second_page = render_index(
                records, warnings, "failed", period="all", runs_page=True, page=2
            )
            self.assertIn("Showing 11-20 of 50 runs", second_page)
            self.assertIn("Page 2 of 5", second_page)
            self.assertEqual(second_page.count('class="run-link"'), 10)
            self.assertGreater(
                second_page.index("Showing 11-20 of 50 runs"),
                second_page.index("</table>"),
            )
            self.assertIn(
                'href="/runs?status=failed&amp;period=all">',
                second_page,
            )
            self.assertIn('aria-label="Previous page"', second_page)
            self.assertIn(
                "return_to=%2Fruns%3Fstatus%3Dfailed%26period%3Dall%26page%3D2",
                second_page,
            )

            last_page = render_index(
                records, warnings, "failed", period="all", runs_page=True, page=99
            )
            self.assertIn("Showing 41-50 of 50 runs", last_page)
            self.assertIn("Page 5 of 5", last_page)
            self.assertEqual(last_page.count('class="run-link"'), 10)
            self.assertNotIn('aria-label="Next page"', last_page)

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
            self.assertIn('data-theme-choice="light"', page)
            self.assertIn('data-theme-choice="dark"', page)
            self.assertNotIn("/evidence/attempts/01/trace.zip", page)
            self.assertTrue(directory.is_dir())

    def test_date_ranges_filter_every_run_summary_and_validate_custom_dates(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _write_run(
                root,
                "run-in-range",
                "passed",
                test_cases=[
                    {"test_id": "cart::checkout", "outcome": "passed"},
                    {"test_id": "cart::retry", "outcome": "flaky"},
                ],
            )
            _write_run(
                root,
                "run-before-range",
                "failed",
                started_at="2026-10-19T12:00:00+00:00",
                finished_at="2026-10-19T12:01:05+00:00",
                test_cases=[
                    {
                        "test_id": "checkout::payment",
                        "outcome": "failed",
                        "failure": "payment declined",
                    },
                    {"test_id": "catalog::retry", "outcome": "flaky"},
                ],
            )
            records, warnings = load_runs(root)

            selected = render_index(
                records,
                warnings,
                period="custom",
                start_date="2026-10-20",
                end_date="2026-10-20",
            )
            self.assertIn("<strong>100%</strong>", selected)
            self.assertIn("<strong>1</strong><small>run records in custom range</small>", selected)
            self.assertIn(
                "<strong>1</strong><small>unique tests marked flaky</small>", selected
            )
            self.assertIn("5.0s", selected)
            self.assertIn("Per-run test pass rate across 1 recent runs", selected)
            self.assertIn("run-in-range", selected)
            self.assertNotIn("payment declined", selected)
            self.assertNotIn("run-before-range", selected)
            self.assertIn("start_date=2026-10-20", selected)
            self.assertIn("end_date=2026-10-20", selected)

            invalid = render_index(
                records,
                warnings,
                period="custom",
                start_date="2026-10-21",
                end_date="2026-10-20",
            )
            self.assertIn("must be on or before", invalid)
            self.assertIn("<strong>—</strong>", invalid)
            self.assertNotIn("run-in-range", invalid)

            all_time = render_index(records, warnings, period="all")
            self.assertIn("<strong>50%</strong>", all_time)
            self.assertIn(
                "<strong>2</strong><small>unique tests marked flaky</small>", all_time
            )
            self.assertIn("35.0s", all_time)
            self.assertIn("Per-run test pass rate across 2 recent runs", all_time)
            self.assertIn("run-before-range", all_time)

            selected_runs = render_index(
                records,
                warnings,
                period="custom",
                start_date="2026-10-20",
                end_date="2026-10-20",
                runs_page=True,
            )
            all_runs = render_index(records, warnings, period="all", runs_page=True)
            self.assertNotIn("Needs attention", selected_runs)
            self.assertNotIn("Needs attention", all_runs)
            timed_runs = render_index(
                records, warnings, "timed_runs", period="all", runs_page=True
            )
            self.assertIn("run-in-range", timed_runs)
            self.assertIn("run-before-range", timed_runs)

    def test_date_presets_include_the_selected_calendar_days(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            today = date.today()
            _write_run(
                root,
                "run-today",
                "passed",
                started_at=f"{today.isoformat()}T12:00:00",
            )
            _write_run(
                root,
                "run-yesterday",
                "failed",
                started_at=f"{(today - timedelta(days=1)).isoformat()}T12:00:00",
            )
            _write_run(
                root,
                "run-eight-days-ago",
                "passed",
                started_at=f"{(today - timedelta(days=8)).isoformat()}T12:00:00",
            )
            records, warnings = load_runs(root)

            for period, expected_count in (
                ("today", 1),
                ("yesterday", 1),
                ("last_7_days", 2),
                ("last_14_days", 3),
                ("last_30_days", 3),
                ("last_90_days", 3),
                ("all", 3),
            ):
                with self.subTest(period=period):
                    page = render_index(records, warnings, period=period)
                    self.assertIn(
                        f"<strong>{expected_count}</strong><small>run records in "
                        f"{period.replace('_', ' ') if period != 'all' else 'all dates'}"
                        "</small>",
                        page,
                    )

    def test_dashboard_serves_records_and_only_files_inside_run_directory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_directory = _write_run(
                root, "run-passed", "passed", evidence=["attempts/01/test-output.log"]
            )
            _write_run(
                root,
                "run-failed",
                "failed",
                test_cases=[
                    {
                        "test_id": "checkout::payment",
                        "outcome": "failed",
                        "attempts": ["failed"],
                        "failure": "payment declined",
                    }
                ],
            )
            _write_run(
                root,
                "run-flaky",
                "flaky",
                test_cases=[
                    {
                        "test_id": "checkout::purchase",
                        "outcome": "flaky",
                        "attempts": ["failed", "passed"],
                    }
                ],
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
                with urlopen(f"{base_url}/?period=all") as response:
                    index = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("run-passed", index)
                    self.assertNotIn("Needs attention", index)

                with urlopen(f"{base_url}/runs?period=all") as response:
                    runs_page = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("<h1>Test runs</h1>", runs_page)
                    self.assertNotIn("Needs attention", runs_page)
                    self.assertNotIn("payment declined", runs_page)

                with urlopen(f"{base_url}/runs?status=failed&period=all") as response:
                    failed_index = response.read().decode()
                    self.assertIn("run-failed", failed_index)
                    self.assertNotIn("run-passed", failed_index)
                    self.assertNotIn("payment declined", failed_index)
                    self.assertIn(
                        "return_to=%2Fruns%3Fstatus%3Dfailed%26period%3Dall", failed_index
                    )

                with urlopen(f"{base_url}/runs?status=flaky_tests&period=all") as response:
                    flaky_index = response.read().decode()
                    self.assertIn("run-flaky", flaky_index)
                    self.assertNotIn("run-failed", flaky_index)

                with urlopen(f"{base_url}/runs?status=timed_runs&period=all") as response:
                    timed_index = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("run-passed", timed_index)
                    self.assertNotIn("Runs with duration data", timed_index)
                    self.assertNotIn('value="timed_runs"', timed_index)

                with urlopen(f"{base_url}/runs/run-passed") as response:
                    detail = response.read().decode()
                    self.assertEqual(response.status, 200)
                    self.assertIn("Attempts", detail)
                    self.assertIn('href="/runs">← Back to runs</a>', detail)

                with urlopen(
                    f"{base_url}/runs/run-failed?"
                    "return_to=%2Fruns%3Fstatus%3Dfailed%26period%3Dall"
                ) as response:
                    detail = response.read().decode()
                    self.assertIn(
                        'href="/runs?status=failed&amp;period=all">← Back to runs</a>',
                        detail,
                    )

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
