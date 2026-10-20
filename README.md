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

```sh
python3 -m pip install -e .
quality-pilot check --config quality-pilot.example.toml
quality-pilot run --config quality-pilot.example.toml
```

Use `quality-pilot --help` for other commands. Reports and evidence are written under `.quality-pilot/runs/`; each attempt gets a fresh Compose environment. Failed or flaky runs exit nonzero.

The CLI currently classifies a whole-suite retry as flaky if a test case changes between failing and passing outcomes. JUnit test-case details are included when the runner emits a report; additional test-runner integrations and a hosted service are out of scope for this initial setup.

Unique Compose project names isolate ordinary containers, networks, and project-scoped volumes. External volumes and host bind mounts are intentionally not reset between attempts, so configure test-specific resources if those contain mutable state.

## Pull request CI

The [GitHub Actions workflow](.github/workflows/quality.yml) runs Ruff linting, the Quality Pilot unit tests, Compose validation, image builds, and the Docker-backed browser smoke suite on pull requests. Test failures fail the job. HTML/JUnit reports and Playwright screenshots/traces are uploaded even on failure when generated. The workflow has been added to the repository; its hosted GitHub Actions run has not yet been executed here.

See [docs/architecture.md](docs/architecture.md) for the architecture and implementation plan.

UI concept: [docs/ui-mockup.svg](docs/ui-mockup.svg).
