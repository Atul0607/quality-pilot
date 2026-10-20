from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_reports(run_dir: Path, data: dict[str, Any]) -> None:
    (run_dir / "run.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(render_markdown(data), encoding="utf-8")


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# Quality Pilot run: {data['run_id']}",
        "",
        f"**Result:** {data['outcome'].upper()}  ",
        f"**Started:** {data['started_at']}  ",
        f"**Finished:** {data.get('finished_at', 'in progress')}",
        "",
        "## Attempts",
        "",
        "| Attempt | Result | Test exit code | Issue |",
        "| ---: | --- | ---: | --- |",
    ]
    for attempt in data["attempts"]:
        code = attempt.get("test_exit_code")
        lines.append(
            f"| {attempt['number']} | {attempt['outcome']} | "
            f"{code if code is not None else 'n/a'} | "
            f"{_cell(attempt.get('error', ''))} |"
        )
    test_cases = data.get("test_cases", [])
    if test_cases:
        lines.extend(
            [
                "",
                "## Test cases",
                "",
                "| Test | Result | Attempt outcomes | Failure detail |",
                "| --- | --- | --- | --- |",
            ]
        )
        for case in test_cases:
            name = _cell(case["test_id"])
            outcomes = _cell(", ".join(case["attempts"]))
            failure = _cell(case.get("failure") or "")
            lines.append(f"| {name} | {case['outcome']} | {outcomes} | {failure} |")
    if data.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in data["warnings"])
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- `{path}`" for path in data.get("evidence", []))
    lines.append("")
    return "\n".join(lines)
