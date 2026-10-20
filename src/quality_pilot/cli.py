from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from quality_pilot import __version__
from quality_pilot.compose import DockerCompose
from quality_pilot.config import ConfigError, load_config
from quality_pilot.dashboard import serve_dashboard
from quality_pilot.run import execute_run, read_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quality-pilot",
        description="Run Docker Compose end-to-end tests with isolated retries and evidence.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate configuration and Docker Compose availability")
    check.add_argument("--config", type=Path, default=Path("quality-pilot.toml"))
    run = commands.add_parser("run", help="run end-to-end tests")
    run.add_argument("--config", type=Path, default=Path("quality-pilot.toml"))
    report = commands.add_parser("report", help="print a saved Markdown report")
    report.add_argument("run_dir", type=Path)
    dashboard = commands.add_parser(
        "dashboard", help="browse local run history and evidence in a read-only dashboard"
    )
    dashboard.add_argument("--artifacts-dir", type=Path, default=Path(".quality-pilot/runs"))
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    return parser


def _check(config_path: Path) -> int:
    if shutil.which("docker") is None:
        print("Docker CLI was not found on PATH.", file=sys.stderr)
        return 2
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    version = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if version.returncode != 0:
        message = version.stderr.strip() or version.stdout.strip()
        print(f"Docker Compose is unavailable: {message}", file=sys.stderr)
        return 2
    compose = DockerCompose(config.compose_file, "qp-config-check")
    log_path = config.artifacts_dir / ".config-check.log"
    if compose.config_check(log_path) != 0:
        message = log_path.read_text(encoding="utf-8", errors="replace").strip()
        log_path.unlink(missing_ok=True)
        print(f"Compose configuration is invalid:\n{message}", file=sys.stderr)
        return 2
    log_path.unlink(missing_ok=True)
    print(f"Configuration valid. {version.stdout.strip()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "report":
        try:
            print(read_report(args.run_dir), end="")
        except (OSError, ValueError) as exc:
            print(f"Unable to read report: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "check":
        return _check(args.config)
    if args.command == "dashboard":
        try:
            serve_dashboard(args.artifacts_dir, args.host, args.port)
        except OSError as exc:
            print(f"Unable to start dashboard: {exc}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
        return 0

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    try:
        run_dir, result = execute_run(config)
    except OSError as exc:
        print(f"Unable to complete run: {exc}", file=sys.stderr)
        return 2
    print(f"Result: {result['outcome'].upper()}")
    print(f"Report: {run_dir / 'report.md'}")
    print(f"Evidence: {run_dir}")
    for warning in result["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)
    if result["outcome"] == "cancelled":
        return 130
    return 0 if result["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
