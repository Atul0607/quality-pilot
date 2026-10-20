# QualityPilot project memory

## Current milestone

Docker and pull-request CI implementation is merged in [PR #1](https://github.com/Atul0607/quality-pilot/pull/1) to `main` (merged October 20, 2026). The local dashboard is proposed in [PR #2](https://github.com/Atul0607/quality-pilot/pull/2). Review identified and fixed evidence downloads being available for files not listed in a run record; the PR branch now requires a fresh hosted check.

## Next-step plan

1. Confirm PR #2 hosted CI passes with the evidence allowlist fix, then merge it.
2. Refine dashboard usability from feedback while preserving the run.json schema contract and read-only safety.
3. Keep the CLI workflow unchanged and defer hosted accounts, multi-user storage, and artifact hosting until the local dashboard proves useful.

## Local verification already completed

- Docker Compose configuration and image builds passed.
- The documented Compose smoke command passed after the fixes: 5 passed, 7 deselected.
- The full PostgreSQL-backed test run passed after the fixes: 12 tests.
- CLI unit tests passed: 6 tests; Ruff, Python compilation, and `git diff --check` passed.
- Hosted “Quality checks” passed on the review-fix commit `f013461` before PR #1 merged.
- Dashboard tests cover passed/failed/flaky records, invalid and incomplete runs, unavailable evidence, evidence download allowlisting, and traversal rejection; all 10 CLI unit tests, Ruff, compilation, Compose validation, and `git diff --check` pass.
- The dashboard was launched against existing `.quality-pilot/runs/` records; it showed 5 real runs (4 passed, 1 failed) and the 11 test cases in the latest run.
