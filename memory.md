# QualityPilot project memory

## Current milestone

Docker/CI and the local run-history dashboard are merged in [PR #1](https://github.com/Atul0607/quality-pilot/pull/1), [PR #2](https://github.com/Atul0607/quality-pilot/pull/2), and [PR #3](https://github.com/Atul0607/quality-pilot/pull/3). The onboarding UI is local-first with no login: an empty artifacts directory shows a clearly labeled, in-memory demo dashboard, and setup instructions live on a separate `/get-started` page. Demo runs cover every result filter and date preset; real run records automatically replace the demo.

## Next-step plan

1. Validate the complete `/get-started` journey from a clean environment, including prerequisites, project configuration, and the first real test run.
2. Keep quickstart, example configuration, and CLI guidance consistent as onboarding friction is discovered.
3. Ensure users can understand real run results, reports, and evidence, with clear recovery guidance for common setup failures.
4. Preserve the run.json schema contract and read-only evidence access.

## Local verification already completed

- Docker Compose configuration and image builds passed.
- The documented Compose smoke command passed after the fixes: 5 passed, 7 deselected.
- The full PostgreSQL-backed test run passed after the fixes: 12 tests.
- CLI unit tests passed: 6 tests; Ruff, Python compilation, and `git diff --check` passed.
- Hosted “Quality checks” passed on the review-fix commit `f013461` before PR #1 merged.
- Dashboard tests cover passed/failed/flaky records, invalid and incomplete runs, unavailable evidence, evidence download allowlisting, and traversal rejection; all 10 CLI unit tests, Ruff, compilation, Compose validation, and `git diff --check` pass.
- The dashboard was launched against existing `.quality-pilot/runs/` records; it showed 5 real runs (4 passed, 1 failed) and the 11 test cases in the latest run.
- Current UI iteration adds date-range filtering and a dedicated `/runs` list; the “Needs attention” panel appears there only when filtered records include failed test cases.
