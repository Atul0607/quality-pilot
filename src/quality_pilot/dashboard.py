from __future__ import annotations

import html
import json
import mimetypes
from statistics import median
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit


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


def _summary_text(value: object, limit: int = 220) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[:limit - 1].rstrip()}…"


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


def _page(
    title: str,
    body: str,
    run_count: int | None = None,
    runs_page: bool = False,
    period: str = "last_7_days",
    start_date: str = "",
    end_date: str = "",
) -> str:
    overview_active = " active" if not runs_page else ""
    overview_current = ' aria-current="page"' if not runs_page else ""
    test_runs_active = " active" if runs_page else ""
    test_runs_current = ' aria-current="page"' if runs_page else ""
    test_runs_url = _dashboard_url("all", period, start_date, end_date, True)
    overview_url = _dashboard_url("all", period, start_date, end_date, False)
    run_badge = (
        f'<span class="nav-count">{run_count}</span>' if run_count is not None else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} · QualityPilot</title>
  <style>
    :root {{ color-scheme:dark; font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:#dde3ec; background:#0b0e14; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; display:flex; }}
    a {{ color:#9fc5fa; }}
    a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible {{ outline:2px solid #72e3b6; outline-offset:2px; }}
    .sidebar {{ width:240px; flex:0 0 240px; min-height:100vh; display:flex; flex-direction:column; background:#0e121a; border-right:1px solid #202633; padding:24px 17px 18px; }}
    .brand {{ display:flex; align-items:center; gap:11px; color:#f1f4f8; text-decoration:none; margin:0 8px 40px; }}
    .brand-mark {{ display:grid; width:36px; height:36px; place-items:center; border-radius:11px; background:linear-gradient(145deg,#83f2c2,#40b98e); color:#10231e; font-size:23px; font-weight:800; }}
    .brand-name {{ display:block; font-size:15px; font-weight:750; }}
    .brand-subtitle {{ display:block; color:#738094; font-size:9px; font-weight:650; letter-spacing:.12em; margin-top:2px; }}
    .side-nav {{ display:grid; gap:5px; margin-bottom:28px; }}
    .side-nav a {{ display:flex; align-items:center; justify-content:space-between; min-height:39px; padding:0 11px; border-radius:8px; color:#c5cedb; text-decoration:none; font-size:13px; }}
    .side-nav a span {{ display:flex; align-items:center; gap:10px; }}
    .nav-icon {{ width:17px; height:17px; fill:none; stroke:#7e8a9e; stroke-width:1.5; stroke-linecap:round; stroke-linejoin:round; }}
    .side-nav a:hover, .side-nav a.active {{ color:#72e3b6; background:#16251f; }}
    .side-nav a.active {{ position:relative; font-weight:600; }}
    .side-nav a.active::before {{ position:absolute; left:0; top:10px; bottom:10px; width:3px; border-radius:2px; background:#54d9a4; content:""; }}
    .side-nav a:hover .nav-icon,.side-nav a.active .nav-icon {{ stroke:#6de4b5; }}
    .nav-count {{ min-width:21px; padding:3px 6px; border-radius:12px; background:#292f3b; color:#b5c0cf; text-align:center; font-size:10px; font-weight:700; }}
    .nav-count.failed {{ color:#ff9a7a; background:#452522; }}
    .sidebar-footer {{ margin-top:auto; border-top:1px solid #202633; padding:17px 7px 0; color:#aab3c3; font-size:11px; }}
    .sidebar-footer strong {{ display:block; color:#e0e6ef; font-size:12px; margin-bottom:3px; }}
    .workspace-path {{ overflow-wrap:anywhere; color:#738094; }}
    .app-main {{ width:calc(100% - 240px); min-width:0; max-width:1600px; margin:0 auto; padding:30px 38px 44px; }}
    .app-topbar {{ display:flex; justify-content:flex-end; margin-bottom:16px; }}
    .theme-controls {{ display:flex; gap:6px; }}
    .theme-button {{ display:grid; width:36px; height:36px; place-items:center; border:1px solid #30394a; border-radius:8px; background:#171e29; color:#aab3c3; cursor:pointer; }}
    .theme-button:hover,.theme-button[aria-pressed="true"] {{ border-color:#60718a; color:#f0f4f8; background:#202a38; }}
    .theme-button:focus-visible {{ outline:2px solid #72e3b6; outline-offset:2px; }}
    .theme-button svg {{ width:17px; height:17px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
    .page-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; margin-bottom:24px; }}
    h1 {{ margin:0 0 6px; color:#f2f5f9; font-size:clamp(1.7rem,3vw,2rem); }}
    h2 {{ margin:0; color:#e7ecf3; font-size:14px; }}
    p {{ line-height:1.5; }}
    .muted {{ color:#8993a6; }}
    .context {{ display:flex; align-items:center; gap:9px; margin-bottom:17px; color:#c5cedb; font-size:12px; }}
    .context-dot {{ color:#586477; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:0 0 16px; }}
    .stat, .panel {{ min-width:0; background:#111720; border:1px solid #242c3a; border-radius:12px; padding:18px 20px; }}
    .stat span {{ display:block; color:#aab3c3; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }}
    .stat strong {{ display:block; margin-top:11px; color:#f0f4f8; font-size:29px; line-height:1.1; }}
    .stat small {{ display:block; margin-top:10px; color:#8993a6; font-size:11px; }}
    a.stat-link {{ color:inherit; text-decoration:none; transition:border-color .15s,transform .15s; }}
    a.stat-link:hover {{ border-color:#4b5a70; transform:translateY(-2px); }}
    .overview-grid {{ display:grid; grid-template-columns:minmax(0,2fr) minmax(300px,.95fr); gap:16px; margin-bottom:16px; }}
    .panel-title {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:5px; }}
    .panel-subtitle {{ margin:4px 0 0; color:#8993a6; font-size:11px; }}
    .chart {{ display:block; width:100%; height:auto; margin-top:15px; }}
    .chart-empty {{ display:grid; min-height:210px; place-items:center; color:#8993a6; text-align:center; font-size:12px; }}
    .latest-meta {{ display:grid; grid-template-columns:1fr 1fr; gap:14px 12px; margin:18px 0; padding:16px 0; border-top:1px solid #242c3a; border-bottom:1px solid #242c3a; }}
    .meta-label {{ display:block; color:#8993a6; font-size:10px; margin-bottom:5px; }}
    .meta-value {{ color:#dce3ec; font-size:12px; overflow-wrap:anywhere; }}
    .result-summary {{ display:flex; flex-wrap:wrap; gap:12px; margin:13px 0 0; color:#aab3c3; font-size:11px; }}
    .result-count {{ display:flex; align-items:center; gap:6px; }}
    .result-count strong {{ color:#e0e6ef; }}
    .dot {{ width:7px; height:7px; display:inline-block; border-radius:50%; background:#596579; }}
    .dot.passed {{ background:#4ad49e; }} .dot.flaky {{ background:#e7b95b; }} .dot.failed {{ background:#e87565; }}
    .toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:1rem; margin-bottom:13px; }}
    .toolbar h2 {{ font-size:14px; }}
    .toolbar-title {{ display:flex; align-items:center; flex-wrap:wrap; gap:12px; }}
    .quick-filters {{ display:grid; width:100%; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .quick-filter {{ display:block; }}
    .quick-filter.active {{ border-color:#54d9a4; }}
    .quick-filter.passed,.quick-filter.passed.active {{ border-color:#2c8b63; background:#10231d; }}
    .quick-filter.passed span,.quick-filter.passed strong {{ color:#65dfa8; }}
    .quick-filter.failed,.quick-filter.failed.active {{ border-color:#a34c4c; background:#2a191b; }}
    .quick-filter.failed span,.quick-filter.failed strong {{ color:#f08b83; }}
    .has-tooltip {{ position:relative; }}
    .has-tooltip:hover,.has-tooltip:focus-visible {{ z-index:30; }}
    .has-tooltip::after {{ position:absolute; z-index:20; top:calc(100% + 8px); left:50%; width:max-content; max-width:260px; padding:7px 9px; border:1px solid #465268; border-radius:6px; background:#202a38; color:#f0f4f8; content:attr(data-tooltip); font-size:11px; font-weight:500; line-height:1.4; text-align:left; white-space:normal; box-shadow:0 5px 16px #0006; opacity:0; visibility:hidden; pointer-events:none; transform:translate(-50%,-3px); transition:opacity .12s ease,transform .12s ease,visibility .12s; }}
    .has-tooltip:hover::after,.has-tooltip:focus-visible::after {{ opacity:1; visibility:visible; transform:translate(-50%,0); }}
    .run-summary {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-bottom:13px; }}
    .run-summary-card {{ display:block; }}
    .run-summary-card.passed {{ border-color:#2c8b63; background:#10231d; }}
    .run-summary-card.passed span,.run-summary-card.passed strong {{ color:#65dfa8; }}
    .run-summary-card.failed {{ border-color:#a34c4c; background:#2a191b; }}
    .run-summary-card.failed span,.run-summary-card.failed strong {{ color:#f08b83; }}
    .filter {{ display:flex; flex-wrap:wrap; align-items:center; gap:.55rem; color:#aab3c3; font-size:.8rem; }}
    select,input[type="date"],.filter button {{ border:1px solid #293141; border-radius:7px; background:#161d28; color:#dce3ec; font:inherit; padding:.5rem .65rem; }}
    .filter button {{ cursor:pointer; }}
    .date-filter {{ justify-content:flex-start; margin:0 0 18px; }}
    .date-filter select {{ width:160px; min-height:36px; }}
    .date-filter button {{ min-height:36px; }}
    .date-range {{ display:flex; flex-wrap:wrap; align-items:center; gap:.45rem; }}
    .date-range[hidden] {{ display:none; }}
    .showing {{ margin:0 0 9px; color:#8993a6; font-size:12px; }}
    .table-wrap {{ overflow-x:auto; }}
    .pagination {{ display:flex; align-items:center; justify-content:flex-end; gap:10px; margin-top:12px; color:#8993a6; font-size:11px; }}
    .pagination a {{ display:grid; width:32px; height:30px; place-items:center; border:1px solid #30394a; border-radius:6px; color:#c5cedb; text-decoration:none; }}
    .pagination a:hover {{ border-color:#60718a; color:#f0f4f8; }}
    .pagination span {{ white-space:nowrap; }}
    .pagination svg {{ width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
    table {{ width:100%; border-collapse:collapse; min-width:700px; }}
    th,td {{ padding:12px 10px; text-align:left; border-bottom:1px solid #202835; }}
    th {{ color:#8993a6; font-size:10px; text-transform:uppercase; letter-spacing:.07em; }}
    td {{ color:#c6ceda; font-size:12px; }}
    tr:last-child td {{ border-bottom:0; }}
    .run-link {{ color:#dbe2ec; font-weight:600; text-decoration:none; }}
    .run-link:hover {{ color:#72e3b6; }}
    .run-id-short {{ display:block; margin-top:4px; color:#738094; font-size:10px; }}
    .test-summary {{ white-space:nowrap; }}
    .badge {{ display:inline-block; border-radius:999px; padding:.25rem .55rem; font-size:10px; font-weight:700; text-transform:uppercase; }}
    .passed {{ color:#73ddaf; background:#183326; }}
    .failed,.error {{ color:#f18e7c; background:#351f20; }}
    .flaky {{ color:#e5c16c; background:#30271a; }}
    .cancelled,.unknown {{ color:#b4becc; background:#222b38; }}
    .warning {{ color:#e7c777; background:#221e17; border:1px solid #40351f; border-radius:9px; padding:.75rem 1rem; }}
    .stack {{ display:grid; gap:.65rem; }}
    .row {{ display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding:.75rem 0; border-bottom:1px solid #202835; }}
    .row:last-child {{ border-bottom:0; }}
    .detail-heading {{ display:flex; align-items:center; justify-content:space-between; gap:1rem; margin-bottom:18px; }}
    .detail-heading a {{ color:#9fc5fa; font-size:12px; text-decoration:none; }}
    .detail-panel {{ margin-bottom:16px; }}
    .empty {{ padding:35px 20px; color:#8993a6; text-align:center; }}
    code {{ color:#c6d7ef; overflow-wrap:anywhere; }}
    .brand {{ margin-bottom:28px; }}
    :root[data-theme="light"] {{ color-scheme:light; color:#182230; background:#f4f6fa; }}
    :root[data-theme="light"] a {{ color:#2459bd; }}
    :root[data-theme="light"] .sidebar {{ background:#fff; border-color:#e0e6ef; }}
    :root[data-theme="light"] .brand {{ color:#182230; }}
    :root[data-theme="light"] .brand-subtitle,
    :root[data-theme="light"] .workspace-path,
    :root[data-theme="light"] .muted,
    :root[data-theme="light"] .panel-subtitle,
    :root[data-theme="light"] .chart-empty,
    :root[data-theme="light"] .meta-label,
    :root[data-theme="light"] .showing,
    :root[data-theme="light"] .pagination,
    :root[data-theme="light"] .run-id-short,
    :root[data-theme="light"] th,
    :root[data-theme="light"] .empty {{ color:#627087; }}
    :root[data-theme="light"] .side-nav a,
    :root[data-theme="light"] .sidebar-footer,
    :root[data-theme="light"] .context,
    :root[data-theme="light"] .filter,
    :root[data-theme="light"] .quick-filter {{ color:#46546a; }}
    :root[data-theme="light"] .side-nav a:hover,
    :root[data-theme="light"] .side-nav a.active {{ color:#12633f; background:#e4f6eb; }}
    :root[data-theme="light"] .nav-icon {{ stroke:#627087; }}
    :root[data-theme="light"] .side-nav a:hover .nav-icon,
    :root[data-theme="light"] .side-nav a.active .nav-icon {{ stroke:#12633f; }}
    :root[data-theme="light"] .nav-count {{ background:#e9edf3; color:#526075; }}
    :root[data-theme="light"] .nav-count.failed {{ background:#fde8e8; color:#a92c31; }}
    :root[data-theme="light"] .sidebar-footer,
    :root[data-theme="light"] .latest-meta {{ border-color:#e0e6ef; }}
    :root[data-theme="light"] .sidebar-footer strong,
    :root[data-theme="light"] h1,
    :root[data-theme="light"] h2,
    :root[data-theme="light"] .stat strong,
    :root[data-theme="light"] .meta-value,
    :root[data-theme="light"] .result-count strong {{ color:#182230; }}
    :root[data-theme="light"] .context-dot {{ color:#9aa6b7; }}
    :root[data-theme="light"] .stat,
    :root[data-theme="light"] .panel {{ background:#fff; border-color:#e0e6ef; box-shadow:0 2px 8px #18223008; }}
    :root[data-theme="light"] .stat span,
    :root[data-theme="light"] .result-summary,
    :root[data-theme="light"] td {{ color:#46546a; }}
    :root[data-theme="light"] a.stat-link:hover {{ border-color:#91a8d1; }}
    :root[data-theme="light"] .quick-filter.active {{ border-color:#21976e; }}
    :root[data-theme="light"] .quick-filter strong {{ color:#182230; }}
    :root[data-theme="light"] .quick-filter.passed,
    :root[data-theme="light"] .quick-filter.passed.active {{ border-color:#77c9a3; background:#e8f7ef; }}
    :root[data-theme="light"] .quick-filter.passed span,
    :root[data-theme="light"] .quick-filter.passed strong {{ color:#12633f; }}
    :root[data-theme="light"] .quick-filter.failed,
    :root[data-theme="light"] .quick-filter.failed.active {{ border-color:#e6a2a0; background:#fff0ef; }}
    :root[data-theme="light"] .quick-filter.failed span,
    :root[data-theme="light"] .quick-filter.failed strong {{ color:#9b302d; }}
    :root[data-theme="light"] .has-tooltip::after {{ border-color:#cbd4e1; background:#182230; color:#fff; }}
    :root[data-theme="light"] .run-summary-card.passed {{ border-color:#77c9a3; background:#e8f7ef; }}
    :root[data-theme="light"] .run-summary-card.passed span,
    :root[data-theme="light"] .run-summary-card.passed strong {{ color:#12633f; }}
    :root[data-theme="light"] .run-summary-card.failed {{ border-color:#e6a2a0; background:#fff0ef; }}
    :root[data-theme="light"] .run-summary-card.failed span,
    :root[data-theme="light"] .run-summary-card.failed strong {{ color:#9b302d; }}
    :root[data-theme="light"] .pagination a {{ border-color:#cbd4e1; color:#46546a; }}
    :root[data-theme="light"] .pagination a:hover {{ border-color:#91a8d1; color:#182230; }}
    :root[data-theme="light"] select,
    :root[data-theme="light"] .filter button,
    :root[data-theme="light"] input[type="date"] {{ color:#182230; background:#fff; border-color:#cbd4e1; }}
    :root[data-theme="light"] th,
    :root[data-theme="light"] td,
    :root[data-theme="light"] .row {{ border-color:#edf0f5; }}
    :root[data-theme="light"] .run-link {{ color:#253247; }}
    :root[data-theme="light"] .run-link:hover {{ color:#12633f; }}
    :root[data-theme="light"] .passed {{ color:#12633f; background:#e4f6eb; }}
    :root[data-theme="light"] .failed,
    :root[data-theme="light"] .error {{ color:#a92c31; background:#fde8e8; }}
    :root[data-theme="light"] .flaky {{ color:#8a5900; background:#fff2d4; }}
    :root[data-theme="light"] .cancelled,
    :root[data-theme="light"] .unknown {{ color:#526075; background:#e9edf3; }}
    :root[data-theme="light"] .warning {{ color:#694600; background:#fff6df; border-color:#f3dfad; }}
    :root[data-theme="light"] code {{ color:#34435a; }}
    :root[data-theme="light"] .theme-button {{ color:#46546a; background:#fff; border-color:#cbd4e1; }}
    :root[data-theme="light"] .theme-button:hover,
    :root[data-theme="light"] .theme-button[aria-pressed="true"] {{ color:#182230; background:#edf2f8; border-color:#91a8d1; }}
    :root[data-theme="light"] .chart line {{ stroke:#dfe5ed; }}
    :root[data-theme="light"] .chart text {{ fill:#627087; }}
    :root[data-theme="light"] .chart polyline {{ stroke:#21976e; }}
    :root[data-theme="light"] .chart circle {{ fill:#21976e; stroke:#fff; }}
    @media (max-width:1000px) {{ .sidebar {{ width:205px; flex-basis:205px; }} .app-main {{ width:calc(100% - 205px); padding:26px 24px; }} }}
    @media (max-width:1100px) {{ .stats {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .overview-grid {{ grid-template-columns:1fr; }} }}
    @media (max-width:700px) {{ body {{ display:block; }} .sidebar {{ width:100%; min-height:0; padding:12px 16px; border-right:0; border-bottom:1px solid #202633; }} .side-label,.sidebar-footer {{ display:none; }} .side-nav {{ display:flex; margin:0; }} .side-nav a {{ min-height:34px; }} .app-main {{ width:100%; padding:24px 16px 36px; }} .stats {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .page-head {{ flex-direction:column; }} .toolbar {{ align-items:flex-start; flex-direction:column; }} .toolbar-title {{ width:100%; }} .quick-filters {{ max-width:none; grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media (max-width:420px) {{ .stats,.run-summary {{ grid-template-columns:1fr; }} .date-filter {{ align-items:flex-start; }} }}
  </style>
</head>
<body>
  <aside class="sidebar">
    <a class="brand" href="/">
      <span class="brand-mark" aria-hidden="true">✓</span>
      <span><span class="brand-name">quality pilot</span><span class="brand-subtitle">TEST RELIABILITY</span></span>
    </a>
    <nav class="side-nav" aria-label="Monitor">
      <a class="has-tooltip{overview_active}"{overview_current} data-tooltip="View quality metrics and reliability trends" href="{overview_url}" title="View quality metrics and reliability trends"><span><svg class="nav-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M3 3h5v5H3zM12 3h5v5h-5zM3 12h5v5H3zM12 12h5v5h-5z"/></svg>Overview</span></a>
      <a class="has-tooltip{test_runs_active}"{test_runs_current} data-tooltip="Browse and filter recorded test runs" href="{test_runs_url}" title="Browse and filter recorded test runs"><span><svg class="nav-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M3 4h14M3 8h14M3 12h9M3 16h9"/><circle cx="15" cy="14" r="2.5"/></svg>Test runs</span>{run_badge}</a>
    </nav>
    <div class="sidebar-footer"><strong>Local workspace</strong><span class="workspace-path">.quality-pilot/runs</span></div>
  </aside>
  <main class="app-main">
    <div class="app-topbar">
      <div class="theme-controls" role="group" aria-label="Color theme">
        <button class="theme-button has-tooltip" type="button" data-theme-choice="light" aria-label="Use light mode" data-tooltip="Switch to light theme" title="Switch to light theme" aria-pressed="false">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>
        </button>
        <button class="theme-button has-tooltip" type="button" data-theme-choice="dark" aria-label="Use dark mode" data-tooltip="Switch to dark theme" title="Switch to dark theme" aria-pressed="false">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/></svg>
        </button>
      </div>
    </div>
    {body}
  </main>
  <script>
    (() => {{
      const storageKey = "qualitypilot-theme";
      const root = document.documentElement;
      const buttons = document.querySelectorAll("[data-theme-choice]");
      let theme = localStorage.getItem(storageKey) === "light" ? "light" : "dark";
      const applyTheme = (nextTheme, persist = false) => {{
        theme = nextTheme;
        root.dataset.theme = theme;
        buttons.forEach((button) => {{
          button.setAttribute("aria-pressed", String(button.dataset.themeChoice === theme));
        }});
        if (persist) localStorage.setItem(storageKey, theme);
      }};
      applyTheme(theme);
      buttons.forEach((button) => {{
        button.addEventListener("click", () => applyTheme(button.dataset.themeChoice, true));
      }});
      const periodSelect = document.getElementById("period");
      const dateRange = document.getElementById("custom-date-range");
      if (periodSelect && dateRange) {{
        const dateInputs = dateRange.querySelectorAll('input[type="date"]');
        const dateForm = periodSelect.form;
        const autoApply = dateForm?.dataset.autoApply === "true";
        const updateDateRange = () => {{
          const isCustom = periodSelect.value === "custom";
          dateRange.hidden = !isCustom;
          dateInputs.forEach((input) => {{
            input.disabled = !isCustom;
            input.required = isCustom;
          }});
        }};
        periodSelect.addEventListener("change", () => {{
          updateDateRange();
          if (autoApply && periodSelect.value !== "custom") dateForm.requestSubmit();
        }});
        dateInputs.forEach((input) => {{
          input.addEventListener("change", () => {{
            if (autoApply && [...dateInputs].every((dateInput) => dateInput.value)) {{
              dateForm.requestSubmit();
            }}
          }});
        }});
        updateDateRange();
      }}
    }})();
  </script>
</body>
</html>"""


def _case_counts(record: RunRecord) -> dict[str, int]:
    return {
        outcome: sum(case.get("outcome") == outcome for case in record.test_cases)
        for outcome in ("passed", "failed", "flaky")
    }


def _run_duration_seconds(record: RunRecord) -> float | None:
    started, finished = record.data.get("started_at"), record.data.get("finished_at")
    if not isinstance(started, str) or not isinstance(finished, str):
        return None
    try:
        elapsed = (
            datetime.fromisoformat(finished) - datetime.fromisoformat(started)
        ).total_seconds()
    except (TypeError, ValueError):
        return None
    return elapsed if elapsed >= 0 else None


def _reliability_chart(records: list[RunRecord]) -> str:
    points: list[tuple[RunRecord, float]] = []
    for record in reversed(records):
        counts = _case_counts(record)
        completed = sum(counts.values())
        if completed:
            points.append((record, counts["passed"] / completed * 100))
    points = points[-8:]
    if not points:
        return (
            '<div class="chart-empty">Per-test results are not available yet.<br>'
            "Run a test suite with a JUnit report to populate this chart.</div>"
        )

    width, height = 720, 260
    left, right, top, bottom = 48, 12, 16, 42
    plot_width = width - left - right
    plot_height = height - top - bottom
    min_rate = min(rate for _, rate in points)
    lower_bound = max(0, int(min_rate // 10) * 10 - 10)
    value_range = max(100 - lower_bound, 10)
    coordinates = []
    for index, (_, rate) in enumerate(points):
        x = left + (plot_width / max(len(points) - 1, 1)) * index
        y = top + (100 - rate) / value_range * plot_height
        coordinates.append((x, y))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coordinates)
    area = (
        f"{coordinates[0][0]:.1f},{height - bottom} "
        f"{polyline} {coordinates[-1][0]:.1f},{height - bottom}"
    )
    middle_bound = lower_bound + value_range / 2
    grid = "".join(
        f'<line x1="{left}" y1="{top + (100 - value) / value_range * plot_height:.1f}" '
        f'x2="{width - right}" y2="{top + (100 - value) / value_range * plot_height:.1f}" '
        'stroke="#293141" stroke-dasharray="3 5" stroke-width="1"/>'
        f'<text x="0" y="{top + (100 - value) / value_range * plot_height + 4:.1f}" '
        'fill="#8993a6" font-size="10">'
        f"{value:.0f}%</text>"
        for value in (100, middle_bound, lower_bound)
    )
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#72e3b6" '
        f'stroke="#111720" stroke-width="2"><title>{_escape(points[index][0].run_id)}: '
        f"{points[index][1]:.1f}% passing</title></circle>"
        for index, (x, y) in enumerate(coordinates)
    )
    labels = "".join(
        f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" '
        f'fill="#8993a6" font-size="9">{_escape(_chart_label(points[index][0]))}</text>'
        for index, (x, _) in enumerate(coordinates)
    )
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Per-run test pass rate across {len(points)} recent runs">'
        '<defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="#4ad49e" stop-opacity=".25"/>'
        '<stop offset="100%" stop-color="#4ad49e" stop-opacity="0"/></linearGradient></defs>'
        f"{grid}<polygon points=\"{area}\" fill=\"url(#chart-fill)\"/>"
        f'<polyline points="{polyline}" fill="none" stroke="#4ad49e" '
        f'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f"{dots}{labels}</svg>"
    )


def _chart_label(record: RunRecord) -> str:
    started = record.data.get("started_at")
    if isinstance(started, str):
        try:
            return datetime.fromisoformat(started).astimezone().strftime("%H:%M")
        except (TypeError, ValueError):
            pass
    return record.run_id[-4:]


def _run_detail_url(run_id: str, return_to: str) -> str:
    params = urlencode({"return_to": return_to})
    return _escape(f"/runs/{quote(run_id, safe='')}?{params}")


def _latest_run_panel(record: RunRecord | None, return_to: str = "/runs") -> str:
    if record is None:
        return (
            '<section class="panel"><div class="panel-title"><h2>Latest run</h2></div>'
            '<div class="empty">No completed run records found.</div></section>'
        )
    counts = _case_counts(record)
    test_count = len(record.test_cases)
    status = (
        f'<span class="badge {_escape(record.outcome)}">{_escape(record.outcome)}</span>'
    )
    summary = "".join(
        f'<span class="result-count"><i class="dot {outcome}"></i>'
        f'<strong>{counts[outcome]}</strong> {_escape(outcome)}</span>'
        for outcome in ("passed", "flaky", "failed")
        if counts[outcome]
    ) or '<span class="muted">No per-test results recorded</span>'
    return (
        '<section class="panel"><div class="panel-title"><h2>Latest run</h2>'
        f"{status}</div>"
        f'<p class="panel-subtitle">{_escape(_time(record.data.get("started_at")))}</p>'
        '<div class="latest-meta">'
        '<div><span class="meta-label">Run ID</span>'
        f'<span class="meta-value"><code>{_escape(record.run_id)}</code></span></div>'
        '<div><span class="meta-label">Duration</span>'
        f'<span class="meta-value">{_escape(_duration(record.data))}</span></div>'
        '<div><span class="meta-label">Tests recorded</span>'
        f'<span class="meta-value">{test_count}</span></div>'
        '<div><span class="meta-label">Result</span>'
        f'<span class="meta-value">{_escape(record.outcome.title())}</span></div>'
        f'</div><div class="result-summary">{summary}</div>'
        f'<p><a href="{_run_detail_url(record.run_id, return_to)}">View run details →</a></p>'
        '</section>'
    )


_DATE_RANGES = {
    "all": "All dates",
    "today": "Today",
    "yesterday": "Yesterday",
    "last_7_days": "Last 7 days",
    "last_14_days": "Last 14 days",
    "last_30_days": "Last 30 days",
    "last_90_days": "Last 90 days",
    "custom": "Custom range",
}


def _date_filtered_runs(
    records: list[RunRecord],
    period: str,
    start_value: str,
    end_value: str,
) -> tuple[list[RunRecord], str, str]:
    if period not in _DATE_RANGES:
        return [], "last_7_days", "Unknown date range; select a valid range."
    if period == "all":
        return records, period, ""

    today = date.today()
    if period == "today":
        start_day = end_day = today
    elif period == "yesterday":
        start_day = end_day = today - timedelta(days=1)
    elif period.startswith("last_"):
        days = int(period.removeprefix("last_").removesuffix("_days"))
        start_day, end_day = today - timedelta(days=days - 1), today
    else:
        try:
            start_day = date.fromisoformat(start_value)
            end_day = date.fromisoformat(end_value)
        except ValueError:
            return [], period, "Enter a valid start and end date for the custom range."
        if start_day > end_day:
            return [], period, "The custom range start date must be on or before its end date."

    selected = []
    for record in records:
        try:
            run_day = datetime.fromisoformat(
                str(record.data.get("started_at"))
            ).astimezone().date()
        except (TypeError, ValueError):
            continue
        if start_day <= run_day <= end_day:
            selected.append(record)
    return selected, period, ""


def _dashboard_url(
    status: str,
    period: str,
    start_date: str,
    end_date: str,
    runs_page: bool,
    page: int = 1,
) -> str:
    params = {"status": status, "period": period}
    if period == "custom":
        params.update({"start_date": start_date, "end_date": end_date})
    if runs_page and page > 1:
        params["page"] = str(page)
    return _escape(f"{'/runs' if runs_page else '/'}?{urlencode(params)}")


def render_index(
    records: list[RunRecord],
    warnings: list[str],
    status_filter: str = "all",
    period: str = "last_7_days",
    start_date: str = "",
    end_date: str = "",
    runs_page: bool = False,
    page: int = 1,
) -> str:
    status_options = (
        "all", "passed", "failed", "flaky", "flaky_tests",
        "timed_runs", "error", "cancelled", "unknown",
    )
    result_options = ("all", "passed", "failed", "flaky", "error", "cancelled", "unknown")
    if status_filter not in status_options:
        status_filter = "all"
    result_filter_value = (
        status_filter if status_filter in result_options else "all"
    )
    date_records, period, date_error = _date_filtered_runs(
        records, period, start_date, end_date
    )
    totals = {
        outcome: sum(record.outcome == outcome for record in date_records)
        for outcome in _OUTCOMES
    }
    pass_rate = (
        f"{totals['passed'] / len(date_records) * 100:.0f}%"
        if date_records
        else "—"
    )
    flaky_tests = {
        case.get("test_id")
        for record in date_records
        for case in record.test_cases
        if case.get("outcome") == "flaky" and isinstance(case.get("test_id"), str)
    }
    durations: list[float] = []
    for record in date_records:
        elapsed = _run_duration_seconds(record)
        if elapsed is not None:
            durations.append(elapsed)
    median_seconds = median(durations) if durations else None
    if median_seconds is None:
        median_duration = "—"
    elif median_seconds < 60:
        median_duration = f"{median_seconds:.1f}s"
    else:
        minutes, seconds = divmod(int(median_seconds), 60)
        median_duration = f"{minutes}m {seconds}s"
    cards = (
        f'<a class="stat stat-link has-tooltip" data-tooltip="Percentage of recorded runs that passed in this date range" title="Percentage of recorded runs that passed in this date range" href="{_dashboard_url("passed", period, start_date, end_date, True)}"><span>Pass rate</span>'
        f'<strong>{pass_rate}</strong><small>of recorded runs passed</small></a>'
        f'<a class="stat stat-link has-tooltip" data-tooltip="Total recorded runs in this date range" title="Total recorded runs in this date range" href="{_dashboard_url("all", period, start_date, end_date, True)}"><span>Test runs</span>'
        f'<strong>{len(date_records)}</strong><small>run records in {_escape(_DATE_RANGES[period].lower())}</small></a>'
        f'<a class="stat stat-link has-tooltip" data-tooltip="Unique tests that had inconsistent results in this date range" title="Unique tests that had inconsistent results in this date range" href="{_dashboard_url("flaky_tests", period, start_date, end_date, True)}"><span>Flaky tests</span>'
        f'<strong>{len(flaky_tests)}</strong><small>unique tests marked flaky</small></a>'
        f'<a class="stat stat-link has-tooltip" data-tooltip="Median duration of runs with timing data in this date range" title="Median duration of runs with timing data in this date range" href="{_dashboard_url("timed_runs", period, start_date, end_date, True)}"><span>Median duration</span>'
        f'<strong>{median_duration}</strong><small>across runs with timing data</small></a>'
    )
    if status_filter == "all":
        filtered_records = date_records
    elif status_filter == "flaky_tests":
        filtered_records = [
            record for record in date_records
            if any(case.get("outcome") == "flaky" for case in record.test_cases)
        ]
    elif status_filter == "timed_runs":
        filtered_records = [
            record for record in date_records
            if _run_duration_seconds(record) is not None
        ]
    else:
        filtered_records = [
            record for record in date_records if record.outcome == status_filter
        ]
    page_size = 10
    page_count = max(1, (len(filtered_records) + page_size - 1) // page_size)
    page = min(max(page, 1), page_count)
    page_start = (page - 1) * page_size
    page_records = filtered_records[page_start : page_start + page_size]
    return_to = html.unescape(
        _dashboard_url(
            status_filter, period, start_date, end_date, runs_page, page
        )
    )
    if filtered_records:
        rows = []
        for record in page_records:
            test_count = len(record.test_cases)
            counts = _case_counts(record)
            short_id = _escape(record.run_id[:12])
            link = (
                f'<a class="run-link" title="{_escape(record.run_id)}" '
                f'href="{_run_detail_url(record.run_id, return_to)}">{short_id}</a>'
                f'<span class="run-id-short">{_escape(record.run_id[12:])}</span>'
            )
            test_summary = (
                f'<span class="test-summary">{counts["passed"]} passed'
                f" · {counts['failed']} failed · {counts['flaky']} flaky</span>"
                if test_count
                else "—"
            )
            rows.append(
                "<tr>"
                f"<td>{link}</td>"
                f'<td><span class="badge {_escape(record.outcome)}">{_escape(record.outcome)}</span></td>'
                f"<td>{_escape(_time(record.data.get('started_at')))}</td>"
                f"<td>{_escape(_duration(record.data))}</td>"
                f"<td>{test_summary}</td>"
                "</tr>"
            )
        table = (
            '<div class="table-wrap"><table><thead><tr><th>Run ID</th><th>Result</th>'
            "<th>Started</th><th>Duration</th><th>Test results</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )
    else:
        message = (
            "No runs match this result filter."
            if date_records
            else "No completed run records found."
        )
        table = f'<section class="panel"><p>{_escape(message)}</p>'
        if not date_records:
            table += "<p>Run `quality-pilot run` to create the first record.</p>"
        else:
            table += (
                f'<p><a href="{_dashboard_url("all", period, start_date, end_date, runs_page)}">'
                "Clear the filter</a></p>"
            )
        table += "</section>"

    options = "".join(
        f'<option value="{value}"{" selected" if result_filter_value == value else ""}>'
        f'{_escape(value.title() if value != "all" else "All results")}</option>'
        for value in result_options
    )
    quick_filters = "".join(
        f'<a class="stat stat-link quick-filter {outcome}'
        f'{" active" if status_filter == outcome else ""}" '
        f'href="{_dashboard_url(filter_status, period, start_date, end_date, True)}">'
        f'<span>{label}</span><strong>{count}</strong></a>'
        for outcome, filter_status, label, count in (
            ("passed", "passed", "Passed runs", totals["passed"]),
            ("failed", "failed", "Failed runs", totals["failed"]),
        )
    )
    run_summary = (
        '<section class="run-summary" aria-label="Run results summary">'
        '<div class="stat run-summary-card has-tooltip" data-tooltip="Total number of runs in the selected date range" title="Total number of runs in the selected date range">'
        '<span>All runs</span>'
        f"<strong>{len(date_records)}</strong></div>"
        '<div class="stat run-summary-card passed has-tooltip" data-tooltip="Runs that passed in the selected date range" title="Runs that passed in the selected date range">'
        '<span>Passed runs</span>'
        f'<strong>{totals["passed"]}</strong></div>'
        '<div class="stat run-summary-card failed has-tooltip" data-tooltip="Runs that failed in the selected date range" title="Runs that failed in the selected date range">'
        '<span>Failed runs</span>'
        f'<strong>{totals["failed"]}</strong></div></section>'
    )
    warning_html = "".join(
        f'<p class="warning">{_escape(warning)}</p>' for warning in warnings
    )
    if date_error:
        warning_html += f'<p class="warning">{_escape(date_error)}</p>'
    date_options = "".join(
        f'<option value="{value}"{" selected" if period == value else ""}>'
        f"{label}</option>"
        for value, label in _DATE_RANGES.items()
    )
    date_controls = (
        '<label for="period">Date range</label>'
        f'<select id="period" name="period">{date_options}</select>'
        '<span class="date-range" id="custom-date-range">'
        '<label for="start-date">From</label>'
        f'<input id="start-date" type="date" name="start_date" value="{_escape(start_date)}">'
        '<label for="end-date">To</label>'
        f'<input id="end-date" type="date" name="end_date" value="{_escape(end_date)}">'
        "</span>"
    )
    if runs_page:
        date_filter = (
            '<form class="filter date-filter" action="/runs" method="get">'
            f"{date_controls}"
            '<label for="status">Filter by result</label>'
            f'<select id="status" name="status">{options}</select>'
            '<button type="submit">Apply</button></form>'
        )
    else:
        date_filter = (
            '<form class="filter date-filter" action="/" method="get" data-auto-apply="true">'
            '<input type="hidden" name="status" value="'
            f'{_escape(status_filter)}">'
            f"{date_controls}"
            "</form>"
        )
    chart_records = [record for record in date_records if record.test_cases]
    chart = _reliability_chart(date_records)
    chart_caption = (
        f"Per-run test pass rate · latest {min(len(chart_records), 8)} runs with results"
        if chart_records
        else "Per-run test pass rate"
    )
    latest = _latest_run_panel(
        filtered_records[0] if filtered_records else None, return_to
    )
    if runs_page:
        toolbar = run_summary
    else:
        toolbar = (
            '<div class="toolbar"><div class="toolbar-title"><h2>Recent runs</h2>'
            f'<nav class="quick-filters" aria-label="Quick run result filters">'
            f"{quick_filters}</nav></div></div>"
        )
    shown_range = (
        f"{page_start + 1}-{page_start + len(page_records)}"
        if filtered_records
        else "0"
    )
    run_table = (
        f'{table}<p class="muted showing">Showing {shown_range} of '
        f'{len(filtered_records)} runs</p>'
    )
    pagination = ""
    if page_count > 1:
        previous = (
            f'<a class="page-arrow" aria-label="Previous page" title="Previous page" '
            f'href="{_dashboard_url(status_filter, period, start_date, end_date, runs_page, page - 1)}">'
            '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15 4l-6 6 6 6M9 10H3"/></svg></a>'
            if page > 1
            else ""
        )
        next_page = (
            f'<a class="page-arrow" aria-label="Next page" title="Next page" '
            f'href="{_dashboard_url(status_filter, period, start_date, end_date, runs_page, page + 1)}">'
            '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 4l6 6-6 6m6-6h6"/></svg></a>'
            if page < page_count
            else ""
        )
        pagination = (
            '<nav class="pagination" aria-label="Run pages">'
            f"{previous}<span>Page {page} of {page_count}</span>{next_page}</nav>"
        )
    if runs_page:
        body = (
            '<div class="page-head"><div><h1>Test runs</h1>'
            '<p class="muted">Run results and failed test cases.</p></div></div>'
            f'{date_filter}'
            f"{warning_html}{toolbar}{run_table}{pagination}"
        )
    else:
        body = (
            '<div class="page-head"><div><h1>Run health</h1>'
            '<p class="muted">Reliability trends from your recorded test runs.</p></div></div>'
            f'{date_filter}'
            f'<div class="stats">{cards}</div>'
            f"{warning_html}"
            '<div class="overview-grid"><section class="panel">'
            '<div class="panel-title"><h2>Test reliability</h2></div>'
            f'<p class="panel-subtitle">{_escape(chart_caption)}</p>{chart}</section>'
            f"{latest}</div>"
        )
    title = "Test runs" if runs_page else "Run health"
    return _page(
        title,
        body,
        len(date_records),
        runs_page,
        period,
        start_date,
        end_date,
    )


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


def render_detail(record: RunRecord, return_to: str = "/runs") -> str:
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
    parsed_return_to = urlsplit(return_to)
    if (
        parsed_return_to.scheme
        or parsed_return_to.netloc
        or parsed_return_to.path not in {"/", "/runs"}
        or parsed_return_to.fragment
    ):
        return_to = "/runs"
    return_to = _escape(return_to)
    body = (
        f'<p><a href="{return_to}">← Back to runs</a></p>'
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
            parsed_url = urlsplit(self.path)
            path = unquote(parsed_url.path)
            if path in {"/", "/index.html", "/runs"}:
                try:
                    records, warnings = load_runs(root)
                except OSError as exc:
                    self._respond(500, _escape(exc).encode(), "text/plain; charset=utf-8")
                    return
                requested_status = parse_qs(parsed_url.query).get("status", ["all"])[0]
                query = parse_qs(parsed_url.query)
                valid_statuses = {
                    "all", *_OUTCOMES, "unknown", "flaky_tests", "timed_runs"
                }
                status_filter = (
                    requested_status if requested_status in valid_statuses else "all"
                )
                period = query.get("period", ["last_7_days"])[0]
                start_date = query.get("start_date", [""])[0]
                end_date = query.get("end_date", [""])[0]
                try:
                    page = int(query.get("page", ["1"])[0])
                except ValueError:
                    page = 1
                self._respond(
                    200,
                    render_index(
                        records,
                        warnings,
                        status_filter,
                        period,
                        start_date,
                        end_date,
                        path == "/runs",
                        page,
                    ).encode("utf-8"),
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
                    return_to = parse_qs(parsed_url.query).get(
                        "return_to", ["/runs"]
                    )[0]
                    self._respond(
                        200,
                        render_detail(record, return_to).encode("utf-8"),
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
