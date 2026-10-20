from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import requests

from conftest import BASE_URL


@pytest.mark.smoke
def test_api_authentication_accepts_valid_and_rejects_invalid_credentials(
    account: dict[str, str],
) -> None:
    client = requests.Session()
    try:
        invalid = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": account["email"], "password": "wrong-password"},
            timeout=10,
        )
        assert invalid.status_code == 401
        assert invalid.json()["error"] == "Email or password is incorrect."

        valid = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": account["email"], "password": account["password"]},
            timeout=10,
        )
        assert valid.status_code == 200
        assert valid.json()["email"] == account["email"]
        assert client.get(f"{BASE_URL}/api/cart", timeout=10).status_code == 200
    finally:
        client.close()


@pytest.mark.regression
def test_api_registration_rejects_invalid_fields(api: requests.Session) -> None:
    response = api.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": "not-an-email", "name": "", "password": "short"},
        timeout=10,
    )

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert errors["email"] == "Enter a valid email address."
    assert errors["name"] == "Enter your full name."
    assert errors["password"] == "Password must be at least 8 characters."


@pytest.mark.regression
def test_api_orders_require_authentication(
    api: requests.Session,
) -> None:
    unauthenticated = api.post(
        f"{BASE_URL}/api/orders",
        json={},
        timeout=10,
    )
    assert unauthenticated.status_code == 401


@pytest.mark.smoke
def test_api_creates_order_with_server_calculated_total(
    account: dict[str, str],
) -> None:
    client = requests.Session()
    try:
        login = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": account["email"], "password": account["password"]},
            timeout=10,
        )
        assert login.status_code == 200

        invalid_order = client.post(
            f"{BASE_URL}/api/orders",
            json={"name": "", "address": "", "city": "", "postal_code": "!"},
            timeout=10,
        )
        assert invalid_order.status_code == 422
        assert set(invalid_order.json()["errors"]) == {"name", "address", "city", "postal_code"}

        empty_cart = client.post(
            f"{BASE_URL}/api/orders",
            json={
                "name": account["name"],
                "address": "14 River Road",
                "city": "Portland",
                "postal_code": "97201",
            },
            timeout=10,
        )
        assert empty_cart.status_code == 409
        assert empty_cart.json()["error"] == "Your cart is empty."

        added = client.post(
            f"{BASE_URL}/api/cart/items",
            json={"product_id": "trail-mug", "quantity": 2},
            timeout=10,
        )
        assert added.status_code == 201
        assert added.json()["total_cents"] == 2500

        order = client.post(
            f"{BASE_URL}/api/orders",
            json={
                "name": account["name"],
                "address": "14 River Road",
                "city": "Portland",
                "postal_code": "97201",
            },
            timeout=10,
        )
        assert order.status_code == 201
        result = order.json()
        assert result["status"] == "placed"
        assert result["total_cents"] == 2500
        assert result["items"][0]["name"] == "Trail Mug"
        assert result["items"][0]["quantity"] == 2
        assert client.get(f"{BASE_URL}/api/cart", timeout=10).json()["items"] == []
        assert client.get(f"{BASE_URL}/api/orders", timeout=10).json()["orders"][0]["id"] == result["id"]
    finally:
        client.close()


@pytest.mark.reliability
def test_concurrent_order_requests_consume_cart_only_once(
    account: dict[str, str],
) -> None:
    login_client = requests.Session()
    clients = [requests.Session(), requests.Session()]
    try:
        login = login_client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": account["email"], "password": account["password"]},
            timeout=10,
        )
        assert login.status_code == 200
        cookies = login_client.cookies.get_dict()
        for client in clients:
            client.cookies.update(cookies)

        added = login_client.post(
            f"{BASE_URL}/api/cart/items",
            json={"product_id": "trail-mug", "quantity": 2},
            timeout=10,
        )
        assert added.status_code == 201

        barrier = Barrier(2)
        checkout = {
            "name": account["name"],
            "address": "14 River Road",
            "city": "Portland",
            "postal_code": "97201",
        }

        def submit_order(client: requests.Session) -> requests.Response:
            barrier.wait(timeout=10)
            return client.post(
                f"{BASE_URL}/api/orders", json=checkout, timeout=10
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit_order, clients))

        assert sorted(response.status_code for response in responses) == [201, 409]
        placed = next(response for response in responses if response.status_code == 201)
        order_id = placed.json()["id"]
        assert login_client.get(f"{BASE_URL}/api/cart", timeout=10).json()["items"] == []
        orders = login_client.get(f"{BASE_URL}/api/orders", timeout=10).json()["orders"]
        assert [order["id"] for order in orders] == [order_id]
    finally:
        login_client.close()
        for client in clients:
            client.close()


@pytest.mark.reliability
def test_api_carts_are_isolated_between_independent_accounts(
    account: dict[str, str],
) -> None:
    first = requests.Session()
    second = requests.Session()
    second_details = None
    second_registered = False
    try:
        first_login = first.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": account["email"], "password": account["password"]},
            timeout=10,
        )
        assert first_login.status_code == 200

        identity = account["email"].replace("quality-pilot-", "").split("@", 1)[0]
        second_details = {
            "email": f"quality-pilot-isolation-{identity}@example.test",
            "password": "correct-horse-battery",
            "name": "Isolation Customer",
        }
        registered = second.post(
            f"{BASE_URL}/api/auth/register",
            json=second_details,
            timeout=10,
        )
        assert registered.status_code == 201
        second_registered = True

        added = first.post(
            f"{BASE_URL}/api/cart/items",
            json={"product_id": "coffee-beans", "quantity": 1},
            timeout=10,
        )
        assert added.status_code == 201
        first_cart = first.get(f"{BASE_URL}/api/cart", timeout=10).json()
        second_cart = second.get(f"{BASE_URL}/api/cart", timeout=10).json()
        assert first_cart["total_cents"] == 1800
        assert len(first_cart["items"]) == 1
        assert second_cart["total_cents"] == 0
        assert second_cart["items"] == []
    finally:
        try:
            if second_registered and second_details is not None:
                second_cleanup = second.delete(f"{BASE_URL}/api/account", timeout=10)
                assert second_cleanup.status_code == 204, (
                    f"Second account cleanup failed: "
                    f"{second_cleanup.status_code} {second_cleanup.text}"
                )
        finally:
            first.close()
            second.close()
