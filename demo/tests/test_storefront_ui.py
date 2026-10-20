from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from conftest import BASE_URL
from pages import CartPage, CheckoutPage, LoginPage, OrderHistoryPage, ShopPage


@pytest.mark.smoke
def test_valid_login_starts_an_authenticated_session(page: Page, account: dict[str, str]) -> None:
    login = LoginPage(page)
    login.open()
    login.login(account["email"], account["password"])

    expect(page).to_have_url(f"{BASE_URL}/")
    expect(page.get_by_text(f"Signed in as {account['name']}")).to_be_visible()


@pytest.mark.regression
def test_invalid_login_shows_an_error_without_authenticating(
    page: Page, account: dict[str, str]
) -> None:
    login = LoginPage(page)
    login.open()
    login.login(account["email"], "not-the-correct-password")

    expect(login.error).to_have_text("Email or password is incorrect.")
    expect(page).to_have_url(f"{BASE_URL}/login")
    expect(page.get_by_role("link", name="Log in")).to_be_visible()


@pytest.mark.smoke
def test_search_shows_matching_products_and_hides_nonmatches(page: Page) -> None:
    shop = ShopPage(page)
    shop.open()
    shop.search("coffee")

    expect(page.get_by_role("heading", name="Coffee Beans")).to_be_visible()
    expect(page.get_by_role("heading", name="Trail Mug")).to_have_count(0)


@pytest.mark.regression
def test_cart_calculates_line_and_order_totals(page: Page, account: dict[str, str]) -> None:
    login = LoginPage(page)
    login.open()
    login.login(account["email"], account["password"])

    shop = ShopPage(page)
    shop.open()
    shop.add_to_cart("Trail Mug")
    shop.open()
    shop.add_to_cart("Trail Mug")
    shop.open()
    shop.add_to_cart("Coffee Beans")

    cart = CartPage(page)
    expect(cart.total).to_have_text("$43.00")
    expect(page.get_by_label("Line total for Trail Mug")).to_have_text("$25.00")
    expect(page.get_by_label("Line total for Coffee Beans")).to_have_text("$18.00")


@pytest.mark.regression
def test_checkout_rejects_an_invalid_postal_code(
    page: Page, account: dict[str, str]
) -> None:
    login = LoginPage(page)
    login.open()
    login.login(account["email"], account["password"])
    ShopPage(page).add_to_cart("Trail Mug")

    checkout = CheckoutPage(page)
    checkout.open()
    checkout.fill_address(
        name=account["name"],
        address="14 River Road",
        city="Portland",
        postal_code="***",
    )
    checkout.place_order()

    expect(page.get_by_role("alert")).to_have_text("Enter a valid postal code.")
    expect(page.get_by_role("heading", name="Checkout")).to_be_visible()


@pytest.mark.smoke
def test_successful_checkout_appears_in_order_history(
    page: Page, account: dict[str, str]
) -> None:
    login = LoginPage(page)
    login.open()
    login.login(account["email"], account["password"])
    ShopPage(page).add_to_cart("Trail Mug")

    checkout = CheckoutPage(page)
    checkout.open()
    checkout.fill_address(
        name=account["name"],
        address="14 River Road",
        city="Portland",
        postal_code="97201",
    )
    checkout.place_order()

    expect(page.get_by_role("status")).to_contain_text("Order placed successfully.")
    expect(page.get_by_text("Order total: $12.50")).to_be_visible()
    OrderHistoryPage(page).open()
    expect(page.get_by_role("heading", name="Order history")).to_be_visible()
    expect(page.get_by_text("$12.50")).to_be_visible()
