# Quality Pilot: Architecture and Implementation Plan

## Product goal

Quality Pilot runs an application's real end-to-end tests against a real, isolated application environment. It makes failures reproducible by retaining useful execution evidence, distinguishes intermittent failures from consistent failures, and turns the results into reports developers can act on.

## Design principles

- **Test the real app:** Start the application and its declared dependencies; do not substitute mocks for the system under test.
- **Isolate every run:** Use a unique Docker Compose project and dedicated network, volumes, and resource limits for each run.
- **Make runs reproducible:** Record the source revision, image references, test command, configuration, and platform versions.
- **Preserve failure evidence:** Collect logs and test artifacts before teardown, with explicit retention and redaction controls.
- **Start small:** Support a Compose-based project and one test runner well before adding integrations or a hosted control plane.
- **Be safe by default:** Treat application code, test output, and configuration as untrusted; do not expose the Docker daemon to the application container.

## Proposed MVP

The first release is a local CLI and a small run coordinator. A user points it at a repository containing a Docker Compose application and an end-to-end test command. Quality Pilot provisions an isolated stack, runs the tests, retries failed tests in fresh environments, gathers evidence, and emits a machine-readable result plus a human-readable report.

This repository now includes a runnable FastAPI/PostgreSQL demo storefront and a pytest/Playwright Chromium test service as a concrete end-to-end example. The demo scenario is described in [demo/README.md](../demo/README.md).

### Example workflow

```text
quality-pilot check
quality-pilot run
    1. Validate TOML configuration and Compose syntax
    2. Create a unique Compose project for the run
    3. Build/start application services and wait for readiness
    4. Run the configured test service with a per-attempt artifact mount
    5. Parse JUnit XML when available; retry failed suites in a clean project state
    6. Collect test output and service logs before teardown
    7. Write run.json and a Markdown summary
```

Use `quality-pilot report <run-directory>` to print a saved summary. Runs are local and are not resumable; failed startup or test attempts still retain their logs and reports.

## System components

### CLI

The CLI is the primary MVP interface. It provides `check`, `run`, and `report` commands. Failed, flaky, and errored runs return a nonzero exit status; cancellation returns 130.

### Run coordinator

The coordinator starts a unique run directory and records attempt timestamps and outcomes. Its terminal result is `passed`, `failed`, `flaky`, `error`, or `cancelled`; state transitions are not yet persisted individually.

### Docker environment manager

The environment manager invokes Docker Compose with a generated project name, for example `qp-<run-id>`. It owns startup, health/readiness checks, test execution, log and artifact collection, and teardown. It should use the Compose CLI rather than mounting the host Docker socket into containers. The application and test containers should only receive the configuration and network access they require.

### Test-runner adapter

The MVP accepts any test command configured for a Compose service and reads JUnit XML from the mounted artifact directory. Test cases are keyed by class and name; cases that fail in one attempt and pass in another are reported as flaky. Runner-specific command setup remains the project owner's responsibility.

### Evidence and report generator

The evidence collector writes run metadata, startup/test/service/cleanup logs, JUnit XML, and any other files written into the attempt artifact mount. The report generator produces `run.json` and `report.md`.

## Configuration and project contract

The initial CLI uses a versioned TOML file at the project root. Keep the contract deliberately small:

```toml
version = 1
compose_file = "compose.yaml"
app_services = ["app"]
test_service = "e2e"
test_command = ["pytest", "-q", "--junitxml={artifacts}/junit.xml"]
retries = 2
timeout_seconds = 900
artifacts_dir = ".quality-pilot/runs"
junit_report = "junit.xml"
```

The `{artifacts}` placeholder is replaced with a run-specific directory mounted into the test container. Validate the schema before starting containers, resolve relative paths against the configuration file's directory, and reject unknown or misspelled keys. TOML uses Python's standard library parser, keeping the starter CLI dependency-free.

The test command should run in a declared Compose service, not as a shell command on the host. This makes the test environment reproducible and avoids giving the runner implicit access to the host.

For this repository, Compose builds `demo/app.py` as the `app` service and the pinned Playwright/pytest environment as `e2e`. Tests exercise registered accounts, search, cart, checkout, order history, and API validation using fresh test users that are deleted by fixtures.

## Isolation and resource lifecycle

- Generate an unpredictable run identifier and a unique Compose project name.
- Use Compose project scoping for containers, networks, and volumes; never reuse a project name for concurrent runs.
- External volumes and host bind mounts are outside Compose project isolation and are not reset between retries; projects must use test-specific resources when those contain mutable state.
- Apply a configurable timeout to service startup and each test attempt. CPU and memory limits are future work.
- Avoid host port publishing by default. When access is needed, assign an ephemeral port and report it.
- Do not mount the Docker socket into application or test services.
- On all exits, collect available evidence before teardown, then remove run-owned resources. The CLI scopes volume removal by Compose project labels instead of issuing an unqualified Docker prune; external volumes are not removed.
- A command for cleaning stale projects is future work; do not use broad Docker pruning.
- Make cleanup idempotent and report resources that could not be removed.

Docker daemon access is powerful: the CLI effectively has the privileges of the user controlling Docker. The MVP should state this clearly and must not expose a remote daemon or accept untrusted configurations through a network service.

## Flake detection

A retry does not prove that a test is healthy; the report records observed outcomes. The MVP retries the full suite in a fresh project state and classifies the run as:

- **Passed:** the suite passed and no test case failure was reported.
- **Failed:** all attempted suites failed, or a JUnit test case failed without a passing attempt.
- **Flaky:** a suite failed and later passed, or an individual JUnit case both failed and passed.
- **Error:** setup, Compose validation, or cleanup failed.
- **Cancelled:** the user interrupted the run.

Retry count is configurable and bounded. If JUnit is missing or invalid, the CLI still classifies at suite level and emits a warning. A retry resets project-scoped services and volumes; bind mounts and external volumes can retain state.

## Result and evidence model

Persist each run as a directory with a stable, documented layout:

```text
.quality-pilot/runs/<run-id>/
  run.json
  report.md
  attempts/<attempt-number>/
    startup.log
    test-output.log
    services.log
    cleanup.log
    project-volumes.txt
    artifacts/
      junit.xml
```

`run.json` includes schema version, run ID, timestamps, outcome, Compose project name, selected service names, attempt outcomes, normalized JUnit test cases, warnings, and evidence paths. Full logs remain separate files.

Evidence can contain secrets or personal data. Artifacts are local and are not uploaded; users should inspect them before sharing. Configurable redaction and retention are future work.

## Suggested implementation structure

The MVP is a small Python CLI:

```text
src/quality_pilot/         CLI, configuration, Compose, retries, reports
tests/                     Unit tests that do not require Docker
demo/app.py                Runnable FastAPI/PostgreSQL sample storefront (SQLite for standalone development)
demo/tests/                Playwright UI and HTTP API tests
compose.yaml               Isolated app and E2E test services
```

Python 3.11+ provides TOML parsing in the standard library. Docker Compose is the execution backend, and JUnit XML is the initial test-result format. There is no hosted service or database in the MVP.

## Validation strategy

- Unit-test configuration validation, JUnit parsing, retry classification, artifact paths, and project-scoped cleanup.
- Use mocked Compose calls to test retry behavior and evidence generation without a daemon.
- Add opt-in integration tests with a tiny Compose fixture and a deliberately failing or intermittent test.
- Exercise startup timeout, unhealthy services, failed image builds, interruption, missing reports, and partial evidence collection.

## Implementation plan

1. **Harden the local runner:** Validate configured service names, improve cancellation/cleanup diagnostics, and add integration fixtures.
2. **Improve evidence handling:** Add configurable redaction, retention settings, richer reports, and a stale-resource cleanup command.
3. **Expand test integrations:** Add runner adapters, CI annotations, and historical flake trends based on usage.
4. **Consider hosted execution:** Add remote execution or a hosted UI only when users need them.

## Explicitly out of MVP scope

- Hosted multi-tenant control plane, user accounts, and artifact uploads.
- Arbitrary remote Docker daemon access.
- Automatic source-code fixes or claims that a retry proves a test is healthy.
- Broad test-framework support before the adapter contract and first runner are stable.
- Unbounded retries, artifact retention, or host-level Docker cleanup.
