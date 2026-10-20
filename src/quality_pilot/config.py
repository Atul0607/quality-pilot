from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a Quality Pilot configuration is invalid."""


@dataclass(frozen=True)
class Config:
    compose_file: Path
    app_services: tuple[str, ...]
    test_service: str
    test_command: tuple[str, ...]
    retries: int
    timeout_seconds: int
    artifacts_dir: Path
    junit_report: str


_ALLOWED_KEYS = {
    "version",
    "compose_file",
    "app_services",
    "test_service",
    "test_command",
    "retries",
    "timeout_seconds",
    "artifacts_dir",
    "junit_report",
}


def load_config(path: Path) -> Config:
    config_path = path.expanduser().resolve()
    try:
        with config_path.open("rb") as config_file:
            raw: dict[str, Any] = tomllib.load(config_file)
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc

    unknown_keys = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown_keys:
        raise ConfigError(f"Unknown configuration key(s): {', '.join(unknown_keys)}")
    if raw.get("version") != 1:
        raise ConfigError("Configuration must specify version = 1.")

    base_dir = config_path.parent
    compose_value = _string(raw, "compose_file", "compose.yaml")
    compose_file = (base_dir / compose_value).resolve()
    if not compose_file.is_file():
        raise ConfigError(f"Compose file does not exist: {compose_file}")

    app_services = _string_list(raw, "app_services")
    test_service = _string(raw, "test_service")
    test_command = _string_list(raw, "test_command")
    if not app_services:
        raise ConfigError("app_services must contain at least one service.")
    if len(set(app_services)) != len(app_services):
        raise ConfigError("app_services must not contain duplicates.")
    if not test_command:
        raise ConfigError("test_command must contain at least one argument.")
    if test_service in app_services:
        raise ConfigError("test_service must not also appear in app_services.")

    retries = _integer(raw, "retries", 2)
    if not 0 <= retries <= 10:
        raise ConfigError("retries must be between 0 and 10.")
    timeout_seconds = _integer(raw, "timeout_seconds", 900)
    if not 1 <= timeout_seconds <= 86400:
        raise ConfigError("timeout_seconds must be between 1 and 86400.")

    artifacts_value = _string(raw, "artifacts_dir", ".quality-pilot/runs")
    artifacts_dir = (base_dir / artifacts_value).resolve()
    report_value = _string(raw, "junit_report", "junit.xml")
    if not report_value or Path(report_value).is_absolute() or ".." in Path(report_value).parts:
        raise ConfigError("junit_report must be a relative path without '..'.")

    return Config(
        compose_file=compose_file,
        app_services=tuple(app_services),
        test_service=test_service,
        test_command=tuple(test_command),
        retries=retries,
        timeout_seconds=timeout_seconds,
        artifacts_dir=artifacts_dir,
        junit_report=report_value,
    )


def _string(raw: dict[str, Any], key: str, default: str | None = None) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string.")
    return value


def _string_list(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError(f"{key} must be a list of non-empty strings.")
    return value


def _integer(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer.")
    return value
