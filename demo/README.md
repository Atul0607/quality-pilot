# Demo storefront and E2E tests

This demo is a real, small FastAPI storefront, backed by PostgreSQL in Docker Compose (SQLite remains available for standalone development), that Quality Pilot runs as a Compose service. The test service uses pytest, Playwright Chromium, and Requests against that live app over the Compose network; tests do not mock the application or call its Python functions directly.

## Run through Quality Pilot

Run the smoke suite with one Compose command from the repository root:

```sh
docker compose up --build --abort-on-container-exit --exit-code-from smoke smoke
```

Compose waits for PostgreSQL's `pg_isready` health check before starting the app, then waits for the app's database-backed `/api/health` check before starting smoke tests. The browser reaches the app at `http://app:8000`; no host port is required. HTML/JUnit reports and Playwright failure screenshots/traces are saved under `test-results/`. The command returns nonzero if smoke tests fail. Clean up services and the ephemeral database with `docker compose down --volumes --remove-orphans`.

For full end-to-end reliability tests with Quality Pilot, run `quality-pilot check --config quality-pilot.example.toml` and then `quality-pilot run --config quality-pilot.example.toml`. The app and browser test dependencies are pinned; complete transitive dependency pins and hashes are in `requirements.lock` and `requirements-e2e.lock`. Both Dockerfiles install using hash verification. The Playwright base image includes the pinned Chromium browser and its OS dependencies, matched to the Playwright Python package version.

Database ports are private by default. If local development requires host access, add `compose.dev.yaml`; it publishes PostgreSQL and the app only on loopback (`127.0.0.1`).

The app is not published on a host port by default. The browser and API tests connect to `http://app:8000` inside their isolated Compose network. PostgreSQL uses a project-scoped named volume, which Quality Pilot removes after each run; fresh attempts therefore start from a clean database.

## Features exercised

- UI: valid and invalid login, product search, multi-item cart arithmetic, checkout postal-code validation, successful checkout, and order history.
- API: authentication, account-registration validation, authentication enforcement, checkout validation, empty-cart rejection, server-calculated order creation, and account/cart isolation.
- Every browser test gets a new browser context. Fixtures create unique users through the registration API and delete them after the test, cascading their carts and orders.
- Product IDs, names, and cent-based prices are fixed in `app.py`. Account identities are unique per test to avoid cross-test collisions.
- Locators use accessible roles and labels with Playwright's auto-waiting assertions; there are no fixed sleeps.

## Pytest markers

The suite uses three registered markers:

- `smoke`: login, search, and successful order creation/check-out journeys.
- `regression`: invalid input, cart arithmetic, and feature validation.
- `reliability`: isolation of carts between separate customer accounts.

To select marker groups, change the `test_command` in `quality-pilot.toml`, for example:

```toml
test_command = [
    "pytest",
    "-q",
    "-m",
    "smoke",
    "--junitxml={artifacts}/junit.xml",
    "--html={artifacts}/report.html",
    "--self-contained-html",
    "--screenshot=only-on-failure",
    "--tracing=retain-on-failure",
    "--output={artifacts}/playwright",
]
```

The default command runs the complete suite. Tests provision their own data and require no seeded account or secret.

## Demo API

- `GET /api/health`
- `GET /api/products?q=...`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/cart`
- `POST /api/cart/items`
- `POST /api/orders`
- `GET /api/orders`
- `GET /api/orders/{order_id}`
- `DELETE /api/account` (used by test cleanup)
