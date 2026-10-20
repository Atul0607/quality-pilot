from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import TypedDict

import pytest
import requests


BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


class Account(TypedDict):
    email: str
    password: str
    name: str


@pytest.fixture
def api() -> Iterator[requests.Session]:
    client = requests.Session()
    client.headers.update({"Accept": "application/json"})
    yield client
    client.close()


@pytest.fixture
def account() -> Iterator[Account]:
    client = requests.Session()
    identity = uuid.uuid4().hex
    details: Account = {
        "email": f"quality-pilot-{identity}@example.test",
        "password": "correct-horse-battery",
        "name": f"Test Customer {identity[:8]}",
    }
    response = client.post(f"{BASE_URL}/api/auth/register", json=details, timeout=10)
    assert response.status_code == 201, (
        f"Test account registration failed: {response.status_code} {response.text}"
    )
    try:
        yield details
    finally:
        try:
            cleanup = client.delete(f"{BASE_URL}/api/account", timeout=10)
            assert cleanup.status_code == 204, (
                f"Test account cleanup failed: {cleanup.status_code} {cleanup.text}"
            )
        finally:
            client.close()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, object]) -> dict[str, object]:
    return {**browser_context_args, "base_url": BASE_URL}
