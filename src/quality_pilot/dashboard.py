from __future__ import annotations

import html
import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit


_OUTCOMES = {"passed", "failed", "flaky", "error", "cancelled"}


@dataclass(frozen=True)
class RunRecord:
    directory: Path
    data: dict[str, Any]

    @property
    def run_id(self) -> str:
        return str(self.data["run_id"])

    @property
    def outcome(self) -> str:
        value = self.data.get("outcome")
        return value if isinstance(value, str) and value in _OUTCOMES else "unknown"

    @property
    def test_cases(self) -> list[dict[str, Any]]:
        cases = self.data.get("test_cases", [])
        return [case for case in cases if isinstance(case, dict)] if isinstance(cases, list) else []

    @property
    def evidence(self) -> list[str]:
        paths = self.data.get("evidence", [])
        return [path for path in paths if isinstance(path, str)] if isinstance(paths, list) else []


def load_runs(artifacts_dir: Path) -> tuple[list[RunRecord], list[str]]:
    root = artifacts_dir.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Run artifacts path is not a directory: {root}")

    records: list[RunRecord] = []
    warnings: list[str] = []
    for directory in sorted(root.iterdir(), key=lambda path: path.name, reverse=True):
        if directory.is_symlink() or not directory.is_dir():
            continue
        record_path = directory / "run.json"
        if not record_path.is_file():
            warnings.append(f"{directory.name}: run.json is missing; run is not shown.")
            continue
        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("run record must be a JSON object")
            if data.get("schema_version") != 1:
                raise ValueError(
                    f"unsupported schema_version {data.get('schema_version')!r}"
                )
            if not isinstance(data.get("run_id"), str) or data["run_id"] != directory.name:
                raise ValueError("run_id must match its containing directory")
            if not isinstance(data.get("started_at"), str):
                raise ValueError("started_at must be a string")
            records.append(RunRecord(directory=directory.resolve(strict=True), data=data))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"{directory.name}: unable to load run record ({exc}).")

    records.sort(
        key=lambda record: str(record.data.get("started_at", "")),
        reverse=True,
    )
    return records, warnings


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _duration(data: dict[str, Any]) -> str:
    started = data.get("started_at")
    finished = data.get("finished_at")
    if not isinstance(started, str) or not isinstance(finished, str):
        return "—"
    try:
        elapsed = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return "—"
    if elapsed < 0:
        return "—"
    if elapsed < 60:
        return f"{elapsed:.1f}s"
    minutes, seconds = divmod(int(elapsed), 60)
    return f"{minutes}m {seconds}s"


def _test_duration(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or value < 0:
        return "—"
    return f"{value:.3f}s"


def _time(value: object) -> str:
    if not isinstance(value, str):
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%b %d, %Y %H:%M:%S %Z")
    except (TypeError, ValueError):
        return value


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} · QualityPilot</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; color:#182230; background:#f4f6fa; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; }}
    header {{ background:#101b31; color:#f8fafc; padding:1.2rem max(1.25rem, calc((100% - 1120px)/2)); }}
    header a {{ color:inherit; text-decoration:none; font-weight:750; letter-spacing:.02em; }}
    main {{ max-width:1120px; margin:2.25rem auto; padding:0 1.25rem 3rem; }}
    h1 {{ margin:.2rem 0 .45rem; font-size:clamp(1.7rem, 4vw, 2.3rem); }}
    h2 {{ font-size:1.15rem; margin:1.8rem 0 .75rem; }}
    p {{ line-height:1.55; }}
    .muted {{ color:#627087; }}
    .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:.8rem; margin:1.5rem 0; }}
    .stat, .panel {{ background:white; border:1px solid #e0e6ef; border-radius:12px; padding:1rem; box-shadow:0 2px 8px #18223008; }}
    .stat span {{ display:block; color:#627087; font-size:.84rem; }}
    .stat strong {{ display:block; font-size:1.55rem; margin-top:.35rem; }}
    .table-wrap {{ overflow-x:auto; background:white; border:1px solid #e0e6ef; border-radius:12px; }}
    table {{ width:100%; border-collapse:collapse; min-width:650px; }}
    th, td {{ padding:.85rem 1rem; text-align:left; border-bottom:1px solid #edf0f5; }}
    th {{ color:#627087; font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; }}
    tr:last-child td {{ border-bottom:0; }}
    a {{ color:#2459bd; }}
    .badge {{ display:inline-block; border-radius:999px; padding:.24rem .58rem; font-size:.77rem; font-weight:700; text-transform:capitalize; }}
    .passed {{ color:#12633f; background:#e4f6eb; }}
    .failed, .error {{ color:#a92c31; background:#fde8e8; }}
    .flaky {{ color:#8a5900; background:#fff2d4; }}
    .cancelled, .unknown {{ color:#526075; background:#e9edf3; }}
    .warning {{ color:#694600; background:#fff6df; border:1px solid #f3dfad; border-radius:9px; padding:.75rem 1rem; }}
    .stack {{ display:grid; gap:.65rem; }}
    .row {{ display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding:.75rem 0; border-bottom:1px solid #edf0f5; }}
    .row:last-child {{ border-bottom:0; }}
    code {{ overflow-wrap:anywhere; }}
    @media (max-width:600px) {{ main {{ margin-top:1.4rem; }} .row {{ flex-direction:column; gap:.3rem; }} }}
  </style>
</head>
<body>
  <header><a href="/">QualityPilot <span class="muted">/ local run dashboard</span></a></header>
  <main>{body}</main>
</body>
</html>"""


def render_index(records: list[RunRecord], warnings: list[str]) -> str:
    totals = {outcome: sum(record.outcome == outcome for record in records) for outcome in _OUTCOMES}
    cards = "".join(
        f'<section class="stat"><span>{_escape(outcome.title())} runs</span>'
        f"<strong>{totals[outcome]}</strong></section>"
        for outcome in ("passed", "failed", "flaky", "error", "cancelled")
    )
    if records:
        rows = []
        for record in records:
            test_count = len(record.test_cases)
            link = f'<a href="/runs/{quote(record.run_id, safe="")}">{_escape(record.run_id)}</a>'
            rows.append(
                "<tr>"
                f"<td>{link}</td>"
                f'<td><span class="badge {_escape(record.outcome)}">{_escape(record.outcome)}</span></td>'
                f"<td>{_escape(_time(record.data.get('started_at')))}</td>"
                f"<td>{_escape(_duration(record.data))}</td>"
                f"<td>{test_count}</td>"
                "</tr>"
            )
        table = (
            '<div class="table-wrap"><table><thead><tr><th>Run</th><th>Result</th>'
            "<th>Started</th><th>Duration</th><th>Tests</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )
    else:
        table = '<section class="panel"><p>No completed run records found.</p>'
        table += "<p>Run `quality-pilot run` to create the first record.</p></section>"
    warning_html = "".join(
        f'<p class="warning">{_escape(warning)}</p>' for warning in warnings
    )
    body = (
        "<h1>Run history</h1>"
        '<p class="muted">A read-only view of QualityPilot run records on this machine.</p>'
        f'<div class="stats">{cards}<section class="stat"><span>Total runs</span>'
        f"<strong>{len(records)}</strong></section></div>"
        f"{warning_html}<h2>Recent runs</h2>{table}"
    )
    return _page("Run history", body)


def _evidence_path(run: RunRecord, relative_path: str) -> Path | None:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts or (
        relative_path != "report.md" and relative_path not in run.evidence
    ):
        return None
    try:
        resolved = (run.directory / path).resolve(strict=True)
        resolved.relative_to(run.directory.resolve(strict=True))
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def render_detail(record: RunRecord) -> str:
    data = record.data
    attempts = data.get("attempts", [])
    if not isinstance(attempts, list):
        attempts = []
    attempt_rows = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        attempt_rows.append(
            "<tr>"
            f"<td>{_escape(attempt.get('number', '—'))}</td>"
            f"<td>{_escape(attempt.get('outcome', 'unknown'))}</td>"
            f"<td>{_escape(attempt.get('test_exit_code', '—'))}</td>"
            f"<td>{_escape(attempt.get('error', ''))}</td>"
            "</tr>"
        )
    attempt_table = (
        '<div class="table-wrap"><table><thead><tr><th>Attempt</th><th>Result</th>'
        "<th>Exit code</th><th>Error</th></tr></thead><tbody>"
        + "".join(attempt_rows)
        + "</tbody></table></div>"
        if attempt_rows
        else '<p class="muted">No attempt details were recorded.</p>'
    )

    test_rows = []
    for case in record.test_cases:
        outcome = case.get("outcome", "unknown")
        outcomes = case.get("attempts", [])
        if not isinstance(outcomes, list):
            outcomes = []
        test_rows.append(
            "<tr>"
            f"<td><code>{_escape(case.get('test_id', 'unnamed test'))}</code></td>"
            f'<td><span class="badge {_escape(outcome)}">{_escape(outcome)}</span></td>'
            f"<td>{_escape(', '.join(str(value) for value in outcomes) or '—')}</td>"
            f"<td>{_escape(_test_duration(case.get('duration_seconds')))}</td>"
            f"<td>{_escape(case.get('failure') or case.get('message') or '')}</td>"
            "</tr>"
        )
    test_table = (
        '<div class="table-wrap"><table><thead><tr><th>Test</th><th>Result</th>'
        "<th>Attempts</th><th>Duration</th><th>Failure detail</th></tr></thead><tbody>"
        + "".join(test_rows)
        + "</tbody></table></div>"
        if test_rows
        else '<p class="muted">This run record does not contain per-test results.</p>'
    )

    evidence = list(record.evidence)
    if _evidence_path(record, "report.md") is not None:
        evidence.insert(0, "report.md")
    evidence_items = []
    for relative_path in dict.fromkeys(evidence):
        path = _evidence_path(record, relative_path)
        if path is None:
            evidence_items.append(
                f"<li><code>{_escape(relative_path)}</code> "
                '<span class="muted">Unavailable</span></li>'
            )
        else:
            href = (
                f"/runs/{quote(record.run_id, safe='')}/evidence/"
                f"{quote(relative_path, safe='/')}"
            )
            evidence_items.append(
                f'<li><a href="{_escape(href)}">{_escape(relative_path)}</a></li>'
            )
    evidence_list = (
        '<ul class="stack">' + "".join(evidence_items) + "</ul>"
        if evidence_items
        else '<p class="muted">No evidence files were recorded.</p>'
    )
    warnings = data.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    warning_html = "".join(
        f'<p class="warning">{_escape(warning)}</p>'
        for warning in warnings
        if isinstance(warning, str)
    )
    outcome = record.outcome
    body = (
        '<p><a href="/">← All runs</a></p>'
        f"<h1>Run {_escape(record.run_id)}</h1>"
        f'<p><span class="badge {_escape(outcome)}">{_escape(outcome)}</span> '
        f'<span class="muted">Started {_escape(_time(data.get("started_at")))}'
        f" · Duration {_escape(_duration(data))}</span></p>"
        '<section class="panel"><h2>Attempts</h2>'
        f"{attempt_table}</section>"
        f"{warning_html}"
        f"<h2>Test results ({len(record.test_cases)})</h2>{test_table}"
        f'<section class="panel"><h2>Evidence</h2>{evidence_list}</section>'
    )
    return _page(f"Run {record.run_id}", body)


def create_server(artifacts_dir: Path, host: str, port: int) -> ThreadingHTTPServer:
    root = artifacts_dir.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Run artifacts path is not a directory: {root}")

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "QualityPilotDashboard/1.0"

        def _respond(self, status: int, content: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            path = unquote(urlsplit(self.path).path)
            if path in {"/", "/index.html"}:
                try:
                    records, warnings = load_runs(root)
                except OSError as exc:
                    self._respond(500, _escape(exc).encode(), "text/plain; charset=utf-8")
                    return
                self._respond(
                    200,
                    render_index(records, warnings).encode("utf-8"),
                    "text/html; charset=utf-8",
                )
                return

            parts = path.split("/")
            if len(parts) >= 3 and parts[1] == "runs":
                try:
                    records, _ = load_runs(root)
                except OSError as exc:
                    self._respond(500, _escape(exc).encode(), "text/plain; charset=utf-8")
                    return
                record = next((item for item in records if item.run_id == parts[2]), None)
                if record is None:
                    self.send_error(404)
                    return
                if len(parts) == 3:
                    self._respond(
                        200,
                        render_detail(record).encode("utf-8"),
                        "text/html; charset=utf-8",
                    )
                    return
                if len(parts) >= 5 and parts[3] == "evidence":
                    relative_path = "/".join(parts[4:])
                    file_path = _evidence_path(record, relative_path)
                    if file_path is None:
                        self.send_error(404)
                        return
                    try:
                        content = file_path.read_bytes()
                    except OSError:
                        self.send_error(404)
                        return
                    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(content)))
                    filename = quote(file_path.name, safe="")
                    self.send_header(
                        "Content-Disposition",
                        f"attachment; filename*=UTF-8''{filename}",
                    )
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(content)
                    return
            self.send_error(404)

        def do_POST(self) -> None:
            self.send_error(405)

        def log_message(self, format_string: str, *args: object) -> None:
            super().log_message(format_string, *args)

    return ThreadingHTTPServer((host, port), DashboardHandler)


def serve_dashboard(artifacts_dir: Path, host: str, port: int) -> None:
    server = create_server(artifacts_dir, host, port)
    with server:
        print(f"QualityPilot dashboard: http://{host}:{server.server_port}/")
        server.serve_forever()
