from __future__ import annotations

from playwright.sync_api import Locator, Page


class LoginPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> None:
        self.page.goto("/login")

    def login(self, email: str, password: str) -> None:
        self.page.get_by_role("textbox", name="Email address").fill(email)
        self.page.get_by_label("Password").fill(password)
        self.page.get_by_role("button", name="Log in").click()

    @property
    def error(self) -> Locator:
        return self.page.get_by_role("alert")


class ShopPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> None:
        self.page.goto("/")

    def search(self, query: str) -> None:
        self.page.get_by_role("textbox", name="Search products").fill(query)
        self.page.get_by_role("button", name="Search").click()

    def add_to_cart(self, product_name: str) -> None:
        self.page.get_by_role("button", name=f"Add {product_name} to cart").click()


class CartPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> None:
        self.page.goto("/cart")

    @property
    def total(self) -> Locator:
        return self.page.get_by_label("Cart total")


class CheckoutPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> None:
        self.page.goto("/checkout")

    def fill_address(
        self,
        name: str,
        address: str,
        city: str,
        postal_code: str,
    ) -> None:
        self.page.get_by_label("Full name").fill(name)
        self.page.get_by_label("Street address").fill(address)
        self.page.get_by_label("City").fill(city)
        self.page.get_by_label("Postal code").fill(postal_code)

    def place_order(self) -> None:
        self.page.get_by_role("button", name="Place order").click()


class OrderHistoryPage:
    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> None:
        self.page.get_by_role("link", name="Order history", exact=True).click()
