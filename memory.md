# QualityPilot project memory

## Current milestone

Docker and pull-request CI implementation is under review in [PR #1](https://github.com/Atul0607/quality-pilot/pull/1), from `qualitypilot/docker-ci-reliability` to `main`. Review identified and fixed two issues: concurrent checkout order creation and synchronous work in async API handlers. The fix is being validated locally and will require a fresh hosted CI run before merge.

## Next-step plan

1. Push the review fixes, confirm hosted PR checks pass, and merge PR #1.
2. Build a local, read-only dashboard for real QualityPilot run history, failure/flakiness summaries, and evidence links.
3. Defer hosted accounts, multi-user storage, and artifact hosting until the local dashboard proves useful.

## Local verification already completed

- Docker Compose configuration and image builds passed.
- The documented Compose smoke command passed after the fixes: 5 passed, 7 deselected.
- The full PostgreSQL-backed test run passed after the fixes: 12 tests.
- CLI unit tests passed: 6 tests; Ruff, Python compilation, and `git diff --check` passed.
- The prior hosted “Quality checks” run passed before these review fixes; a fresh run is pending.
