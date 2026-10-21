# QualityPilot project memory

## Current milestone

Docker/CI and the local run-history dashboard are merged in [PR #1](https://github.com/Atul0607/quality-pilot/pull/1) and [PR #2](https://github.com/Atul0607/quality-pilot/pull/2). Dashboard UI improvements are in progress on `qualitypilot/dashboard-ui-improvements`: date-range filtering, a dedicated run list linked from the sidebar, and an accessible top-right theme control.

## Next-step plan

1. Verify sidebar navigation, date filtering, theme persistence, and failed-case summaries in the browser against actual run records.
2. Run the full unit/lint checks and submit a UI-improvements PR.
3. Gather feedback after merge; preserve the run.json schema contract, read-only evidence access, and defer hosted accounts/multi-user storage.

## Local verification already completed

- Docker Compose configuration and image builds passed.
- The documented Compose smoke command passed after the fixes: 5 passed, 7 deselected.
- The full PostgreSQL-backed test run passed after the fixes: 12 tests.
- CLI unit tests passed: 6 tests; Ruff, Python compilation, and `git diff --check` passed.
- Hosted “Quality checks” passed on the review-fix commit `f013461` before PR #1 merged.
- Dashboard tests cover passed/failed/flaky records, invalid and incomplete runs, unavailable evidence, evidence download allowlisting, and traversal rejection; all 10 CLI unit tests, Ruff, compilation, Compose validation, and `git diff --check` pass.
- The dashboard was launched against existing `.quality-pilot/runs/` records; it showed 5 real runs (4 passed, 1 failed) and the 11 test cases in the latest run.
- Current UI iteration adds date-range filtering and a dedicated `/runs` list; the “Needs attention” panel appears there only when filtered records include failed test cases.
