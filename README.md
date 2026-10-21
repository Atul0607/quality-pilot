# quality-pilot

A Docker-native end-to-end testing and reliability platform that tests real applications in isolated environments, detects flaky tests, collects debugging evidence, and generates actionable quality reports.

Quality Pilot is an early local CLI MVP. It starts application services with Docker Compose, runs an E2E test service in an isolated Compose project, retries the suite in fresh environments, and saves test results, service logs, and a Markdown report.

The repository includes a self-contained demo storefront, PostgreSQL service, and real browser/API tests. See [demo/README.md](demo/README.md) for the Compose workflow and test details.

## Requirements

- Python 3.11 or newer
- Docker with the Docker Compose plugin
- A Compose project with application services and a test-runner service

Docker access grants the CLI the privileges of the configured Docker user. Only run it on projects and configuration you trust. Artifacts stay local and may contain sensitive application output; inspect them before sharing.

## Run browser smoke tests

From the repository root:

```sh
docker compose up --build --abort-on-container-exit --exit-code-from smoke smoke
```

This starts PostgreSQL, waits for its health check, starts the application after the database is healthy, then runs the Playwright smoke suite against `http://app:8000` on the private Compose network. Test failure returns a nonzero exit code. The HTML report and JUnit XML are written to `test-results/`; Playwright screenshots and traces are retained for failures. Clean up containers and the test database with:

```sh
docker compose down --volumes --remove-orphans
```

No database port is published by default. For local development that needs host access, explicitly add the loopback-only override:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build --wait app
```

This publishes the app at `127.0.0.1:8000` and PostgreSQL at `127.0.0.1:5432`. Both ports are otherwise private to Compose.

## Run Quality Pilot end to end

Use Python 3.11 or newer. On macOS, first make sure `python3.11` (or another supported version such as `python3.12`) is installed. Create the virtual environment with that interpreter; using an older system `python3` can silently create an unsupported Python 3.9 environment. Upgrade pip before installing the project so editable installation from `pyproject.toml` is supported:

```sh
python3.11 --version
python3.11 -m venv .venv
source .venv/bin/activate
python --version
python -m pip install --upgrade pip
python -m pip install -e .
quality-pilot check --config quality-pilot.example.toml
quality-pilot run --config quality-pilot.example.toml
```

The `python --version` check should report 3.11 or newer. If `python3.11` is not installed, install a supported Python version or replace `python3.11` in the commands with the path to one that is. Activate `.venv` in each new terminal before running `quality-pilot`.

Use `quality-pilot --help` for other commands. Reports and evidence are written under `.quality-pilot/runs/`; each attempt gets a fresh Compose environment. Failed or flaky runs exit nonzero.

The CLI currently classifies a whole-suite retry as flaky if a test case changes between failing and passing outcomes. JUnit test-case details are included when the runner emits a report; additional test-runner integrations and a hosted service are out of scope for this initial setup.

Unique Compose project names isolate ordinary containers, networks, and project-scoped volumes. External volumes and host bind mounts are intentionally not reset between attempts, so configure test-specific resources if those contain mutable state.

## Browse local run history

Start the read-only dashboard after running Quality Pilot:

```sh
quality-pilot dashboard
```

This command is available after following the Python setup and editable install steps above. To launch without installing the CLI entry point, use `PYTHONPATH=src python -m quality_pilot dashboard` from the repository root with the supported virtual environment active.

Open `http://127.0.0.1:8765`. The dashboard reads `schema_version = 1` `run.json` records from `.quality-pilot/runs/` and shows the pass rate, run count, flaky-test count, median duration, a per-run test reliability chart, and the latest run. The date-range filter supports today, yesterday, the last 7/14/30/90 days, all dates, and a custom range; it applies to dashboard metrics and run lists. On Overview, selecting a preset applies it immediately; for a custom range, choose both dates to apply. The left sidebar contains **Overview** and **Test runs**; the overview focuses on metrics and trends, while the Test runs page contains a static All runs, Passed runs, and Failed runs summary above the filtered run list, paginated 10 runs at a time. These summary cards are informational, not clickable; use the date-range and result filters and their single Apply button to filter the list. The selected date range is carried over from Overview. Flaky-test runs remain available from the Flaky tests metric and run filters. Failed test cases and their details are available from each run's detail page. Use the icon buttons at the top right to switch between dark (default) and light mode; your choice is saved in the browser. Run details include attempts, failure details, warnings, and links to available evidence. Missing evidence is labeled unavailable; malformed, incomplete, or unsupported-version records are called out rather than presented as successful. Evidence files are served as downloads. The server binds to loopback by default; only change `--host` if you intentionally want to expose local run data to other machines. Stop it with Ctrl-C.

Use `quality-pilot dashboard --artifacts-dir PATH --host 127.0.0.1 --port 8765` to select another run directory or port.

## Pull request CI

The [GitHub Actions workflow](.github/workflows/quality.yml) runs Ruff linting, the Quality Pilot unit tests, Compose validation, image builds, and the Docker-backed browser smoke suite on pull requests. Test failures fail the job. HTML/JUnit reports and Playwright screenshots/traces are uploaded even on failure when generated. This workflow was verified on merged PR #1.

See [docs/architecture.md](docs/architecture.md) for the architecture and implementation plan.

UI concept: [docs/ui-mockup.svg](docs/ui-mockup.svg).
