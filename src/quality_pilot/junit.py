from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestCaseResult:
    test_id: str
    name: str
    outcome: str
    duration_seconds: float
    message: str | None = None


def parse_junit(path: Path) -> list[TestCaseResult]:
    root = ET.parse(path).getroot()
    nodes = [root] if root.tag == "testcase" else list(root.iter("testcase"))
    results: list[TestCaseResult] = []
    for node in nodes:
        name = node.attrib.get("name", "unnamed test")
        classname = node.attrib.get("classname", "")
        test_id = f"{classname}::{name}" if classname else name
        failure = node.find("failure")
        error = node.find("error")
        skipped = node.find("skipped")
        issue = failure if failure is not None else error
        if issue is not None:
            outcome = "failed"
            message = issue.attrib.get("message") or (issue.text or "").strip() or None
        elif skipped is not None:
            outcome = "skipped"
            message = skipped.attrib.get("message") or (skipped.text or "").strip() or None
        else:
            outcome = "passed"
            message = None
        try:
            duration = float(node.attrib.get("time", "0"))
        except ValueError:
            duration = 0.0
        results.append(TestCaseResult(test_id, name, outcome, duration, message))
    return results


def classify_test_cases(
    attempts: list[list[TestCaseResult]],
) -> list[dict[str, object]]:
    by_id: dict[str, list[TestCaseResult]] = {}
    for attempt in attempts:
        for result in attempt:
            by_id.setdefault(result.test_id, []).append(result)

    classified: list[dict[str, object]] = []
    for test_id, results in sorted(by_id.items()):
        outcomes = {result.outcome for result in results}
        if "failed" in outcomes and "passed" in outcomes:
            outcome = "flaky"
        elif "failed" in outcomes:
            outcome = "failed"
        elif outcomes == {"skipped"}:
            outcome = "skipped"
        else:
            outcome = "passed"
        classified.append(
            {
                "test_id": test_id,
                "name": results[0].name,
                "outcome": outcome,
                "attempts": [result.outcome for result in results],
                "duration_seconds": round(sum(result.duration_seconds for result in results), 3),
                "failure": next((result.message for result in results if result.message), None),
            }
        )
    return classified
