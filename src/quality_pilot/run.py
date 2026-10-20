from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

from quality_pilot.compose import DockerCompose
from quality_pilot.config import Config
from quality_pilot.junit import TestCaseResult, classify_test_cases, parse_junit
from quality_pilot.reporting import write_reports


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_tail(path: Path, limit: int = 2000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""


def execute_run(config: Config) -> tuple[Path, dict[str, Any]]:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(8)}"
    project_name = f"qp-{secrets.token_hex(8)}"
    run_dir = config.artifacts_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    run_dir.chmod(0o700)

    compose = DockerCompose(config.compose_file, project_name)
    data: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "project_name": project_name,
        "outcome": "error",
        "started_at": _timestamp(),
        "finished_at": None,
        "config": {
            "compose_file": str(config.compose_file),
            "app_services": list(config.app_services),
            "test_service": config.test_service,
            "retries": config.retries,
            "timeout_seconds": config.timeout_seconds,
        },
        "attempts": [],
        "test_cases": [],
        "warnings": [],
        "evidence": [],
    }

    preflight_log = run_dir / "preflight.log"
    if compose.config_check(preflight_log) != 0:
        data["warnings"].append(
            f"Compose configuration validation failed: {_read_tail(preflight_log) or preflight_log.name}"
        )
        data["evidence"].append(preflight_log.name)
        data["finished_at"] = _timestamp()
        write_reports(run_dir, data)
        return run_dir, data
    preflight_log.unlink(missing_ok=True)

    parsed_attempts: list[list[TestCaseResult]] = []
    any_test_failure = False
    any_test_success = False
    any_setup_error = False
    attempts_total = config.retries + 1

    for number in range(1, attempts_total + 1):
        attempt_dir = run_dir / "attempts" / f"{number:02d}"
        attempt_dir.mkdir(parents=True)
        attempt: dict[str, Any] = {
            "number": number,
            "outcome": "error",
            "started_at": _timestamp(),
            "finished_at": None,
            "test_exit_code": None,
            "test_cases": [],
            "evidence": [],
        }
        data["attempts"].append(attempt)
        app_log = attempt_dir / "startup.log"
        test_log = attempt_dir / "test-output.log"
        service_log = attempt_dir / "services.log"
        cleanup_log = attempt_dir / "cleanup.log"

        try:
            start_code = compose.start(config.app_services, app_log, config.timeout_seconds)
            if start_code != 0:
                any_setup_error = True
                attempt["error"] = f"Application services failed to start (exit {start_code})."
            else:
                artifacts_dir = attempt_dir / "artifacts"
                artifacts_dir.mkdir()
                report_relative_path = Path(config.junit_report)
                (artifacts_dir / report_relative_path).parent.mkdir(parents=True, exist_ok=True)
                command_code = compose.test(
                    config.test_service,
                    config.test_command,
                    artifacts_dir,
                    test_log,
                    config.timeout_seconds,
                )
                attempt["test_exit_code"] = command_code
                test_failed = command_code != 0
                junit_path = artifacts_dir / report_relative_path
                if junit_path.is_file():
                    try:
                        resolved_junit_path = junit_path.resolve(strict=True)
                        if not resolved_junit_path.is_relative_to(artifacts_dir.resolve()):
                            raise ValueError("JUnit report resolves outside the mounted artifacts directory.")
                        cases = parse_junit(resolved_junit_path)
                        test_failed |= any(case.outcome == "failed" for case in cases)
                        parsed_attempts.append(cases)
                        attempt["test_cases"] = [
                            {
                                "test_id": case.test_id,
                                "name": case.name,
                                "outcome": case.outcome,
                                "duration_seconds": case.duration_seconds,
                                "message": case.message,
                            }
                            for case in cases
                        ]
                        attempt["evidence"].append(str(junit_path.relative_to(run_dir)))
                    except (OSError, ParseError, ValueError) as exc:
                        data["warnings"].append(
                            f"Attempt {number}: could not parse JUnit report {config.junit_report}: {exc}"
                        )
                else:
                    data["warnings"].append(
                        f"Attempt {number}: no JUnit report found at "
                        f"{junit_path.relative_to(run_dir)}; only suite-level retry status is available."
                    )
                any_test_failure |= test_failed
                any_test_success |= not test_failed
                attempt["outcome"] = "failed" if test_failed else "passed"
        except KeyboardInterrupt:
            data["outcome"] = "cancelled"
            attempt["error"] = "Run interrupted by user."
        except OSError as exc:
            any_setup_error = True
            attempt["error"] = str(exc)
        finally:
            if app_log.exists():
                attempt["evidence"].append(str(app_log.relative_to(run_dir)))
            if test_log.exists():
                attempt["evidence"].append(str(test_log.relative_to(run_dir)))
            logs_code = compose.logs(service_log)
            if service_log.exists():
                attempt["evidence"].append(str(service_log.relative_to(run_dir)))
            if logs_code != 0:
                data["warnings"].append(f"Attempt {number}: collecting service logs failed.")
            cleanup_code = compose.stop(cleanup_log)
            if cleanup_log.exists():
                attempt["evidence"].append(str(cleanup_log.relative_to(run_dir)))
            if cleanup_code != 0:
                data["warnings"].append(
                    f"Attempt {number}: Compose cleanup failed; inspect "
                    f"{cleanup_log.relative_to(run_dir)} and remove the run's resources manually."
                )
                any_setup_error = True
            attempt["finished_at"] = _timestamp()

        if data["outcome"] == "cancelled":
            break
        if any_setup_error or attempt["outcome"] == "passed":
            break

    data["test_cases"] = classify_test_cases(parsed_attempts)
    has_flaky_case = any(case["outcome"] == "flaky" for case in data["test_cases"])
    has_failed_case = any(case["outcome"] == "failed" for case in data["test_cases"])
    if data["outcome"] != "cancelled":
        if any_setup_error:
            data["outcome"] = "error"
        elif any_test_failure and any_test_success or has_flaky_case:
            data["outcome"] = "flaky"
        elif any_test_failure or has_failed_case:
            data["outcome"] = "failed"
        else:
            data["outcome"] = "passed"

    data["finished_at"] = _timestamp()
    data["evidence"] = [
        str(path.relative_to(run_dir))
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.name not in {"run.json", "report.md"}
    ]
    write_reports(run_dir, data)
    return run_dir, data


def read_report(run_dir: Path) -> str:
    report_path = run_dir.resolve() / "report.md"
    if not report_path.is_file():
        raise FileNotFoundError(f"No Quality Pilot report at {report_path}")
    return report_path.read_text(encoding="utf-8")
