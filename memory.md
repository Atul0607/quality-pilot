# QualityPilot project memory

## Current milestone

Docker and pull-request CI implementation is committed locally on `qualitypilot/docker-ci-reliability` as `52016ef`. The push to `origin` was rejected with HTTP 403, so the remote feature branch and pull request do not exist yet. Local validation was reported successful, but the GitHub-hosted workflow has not been run.

## Next-step plan

1. Push the feature branch using GitHub credentials with repository write access, then submit it as a pull request.
2. Verify the hosted GitHub Actions checks, including that failures fail the job and reports, screenshots, and traces upload on failure. Fix any hosted-only problems.
3. After CI is verified, build a local, read-only dashboard for real QualityPilot run history, failure/flakiness summaries, and evidence links.
4. Defer hosted accounts, multi-user storage, and artifact hosting until the local dashboard proves useful.

## Local verification already completed

- Docker Compose configuration and image builds passed.
- The documented Compose smoke command passed: 5 passed, 6 deselected.
- The full PostgreSQL-backed test run passed: 11 tests.
- CLI unit tests passed: 6 tests; Ruff, Python compilation, and `git diff --check` passed.
- Hosted GitHub Actions verification remains outstanding.
