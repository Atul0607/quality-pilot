from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
import psycopg
from psycopg.rows import dict_row
from starlette.concurrency import run_in_threadpool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/quality-pilot-storefront.sqlite3")
SESSION_COOKIE = "quality_pilot_session"
PASSWORD_ITERATIONS = 120_000

PRODUCTS = (
    {"id": "trail-mug", "name": "Trail Mug", "description": "Insulated stainless steel mug.", "price_cents": 1250},
    {"id": "coffee-beans", "name": "Coffee Beans", "description": "A balanced medium-roast whole bean coffee.", "price_cents": 1800},
    {"id": "canvas-tote", "name": "Canvas Tote", "description": "Reusable heavy-canvas everyday tote.", "price_cents": 1575},
    {"id": "pour-over-kit", "name": "Pour-over Kit", "description": "A simple ceramic pour-over starter set.", "price_cents": 3250},
)
PRODUCT_BY_ID = {product["id"]: product for product in PRODUCTS}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title="Quality Pilot Demo Storefront", version="1.0.0")


class Database:
    def __init__(self, raw_connection: Any, *, postgres: bool) -> None:
        self.raw_connection = raw_connection
        self.postgres = postgres

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        if self.postgres:
            query = query.replace("?", "%s")
        return self.raw_connection.execute(query, parameters)

    def executemany(self, query: str, parameters: list[tuple[Any, ...]]) -> Any:
        if self.postgres:
            query = query.replace("?", "%s")
        return self.raw_connection.cursor().executemany(query, parameters)

    def commit(self) -> None:
        self.raw_connection.commit()

    def rollback(self) -> None:
        self.raw_connection.rollback()

    def close(self) -> None:
        self.raw_connection.close()


@contextmanager
def connection() -> Iterator[Any]:
    if DATABASE_URL.startswith(("postgres://", "postgresql://")):
        db = Database(psycopg.connect(DATABASE_URL, row_factory=dict_row), postgres=True)
    elif DATABASE_URL.startswith("sqlite:///"):
        database_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_connection = sqlite3.connect(database_path, timeout=10)
        sqlite_connection.row_factory = sqlite3.Row
        sqlite_connection.execute("PRAGMA foreign_keys = ON")
        db = Database(sqlite_connection, postgres=False)
    else:
        raise ValueError("DATABASE_URL must use postgresql:// or sqlite:///")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    with connection() as db:
        statements = """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS cart_items (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99),
                PRIMARY KEY(user_id, product_id)
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                customer_name TEXT NOT NULL,
                address TEXT NOT NULL,
                city TEXT NOT NULL,
                postal_code TEXT NOT NULL,
                total_cents INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                unit_price_cents INTEGER NOT NULL,
                quantity INTEGER NOT NULL
            );
            """
        if DATABASE_URL.startswith(("postgres://", "postgresql://")):
            statements = statements.replace(
                "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY"
            ).replace("user_id INTEGER NOT NULL", "user_id BIGINT NOT NULL")
            statements = statements.replace("order_id INTEGER NOT NULL", "order_id BIGINT NOT NULL")
            statements = statements.replace("COLLATE NOCASE", "")
        for statement in statements.split(";"):
            if statement.strip():
                db.execute(statement)


initialize_database()


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS
    ).hex()


def _create_user(email: str, name: str, password: str) -> int:
    salt = secrets.token_hex(16)
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO users(email, name, password_salt, password_hash) VALUES (?, ?, ?, ?) RETURNING id",
            (email.strip().lower(), name.strip(), salt, _password_hash(password, salt)),
        )
        return int(cursor.fetchone()["id"])


def _new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with connection() as db:
        db.execute("INSERT INTO sessions(token, user_id) VALUES (?, ?)", (token, user_id))
    return token


def _current_user(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with connection() as db:
        return db.execute(
            "SELECT users.id, users.email, users.name FROM sessions "
            "JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?",
            (token,),
        ).fetchone()


def _require_user(request: Request) -> sqlite3.Row | None:
    return _current_user(request)


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24,
    )


def _layout(title: str, body: str, user: sqlite3.Row | None = None) -> str:
    account_link = (
        f'<span>Signed in as {_escape(user["name"])}</span> '
        '<form class="inline" action="/logout" method="post">'
        '<button class="link-button" type="submit">Log out</button></form>'
        if user
        else '<a href="/login">Log in</a>'
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} · Field &amp; Found</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #19251f; background: #f5f7f3; }}
    body {{ margin: 0; }} header {{ display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:1rem max(1.5rem, calc((100% - 1050px)/2)); background:#fff; border-bottom:1px solid #dfe5df; }}
    header nav {{ display:flex; align-items:center; gap:1rem; flex-wrap:wrap; }} a {{ color:#176b4d; }} main {{ max-width:1050px; margin:2rem auto; padding:0 1.5rem; }}
    h1 {{ margin-top:0; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; }} .card, .panel {{ background:#fff; border:1px solid #dfe5df; border-radius:12px; padding:1rem; }}
    .card h2 {{ margin:.2rem 0; font-size:1.15rem; }} .price {{ font-weight:700; }} label {{ display:block; margin:.8rem 0 .3rem; font-weight:600; }}
    input {{ box-sizing:border-box; width:100%; padding:.65rem; border:1px solid #9aa79d; border-radius:6px; font:inherit; }} button {{ border:0; border-radius:6px; padding:.65rem .9rem; background:#176b4d; color:white; font:inherit; font-weight:650; cursor:pointer; }}
    button.secondary {{ background:#e8eee9; color:#183b2d; }} .link-button {{ padding:0; background:none; color:#176b4d; text-decoration:underline; font-weight:500; }} .inline {{ display:inline; }} .row {{ display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.8rem 0; border-bottom:1px solid #e5e9e5; }}
    .errors {{ color:#a12626; }} .notice {{ padding:.75rem; background:#edf6ef; border-radius:6px; }} .muted {{ color:#5d6b61; }} .actions {{ display:flex; gap:.6rem; margin-top:1rem; }} .quantity {{ max-width:120px; }}
  </style>
</head>
<body>
  <header><a href="/" aria-label="Field and Found home"><strong>Field &amp; Found</strong></a>
    <nav aria-label="Main navigation"><a href="/">Shop</a><a href="/cart">Cart</a><a href="/orders">Order history</a>{account_link}</nav>
  </header>
  <main><h1>{_escape(title)}</h1>{body}</main>
</body>
</html>"""
    return page


def _cart_summary(user_id: int) -> tuple[list[dict[str, Any]], int]:
    with connection() as db:
        rows = db.execute(
            "SELECT product_id, quantity FROM cart_items WHERE user_id = ? ORDER BY product_id",
            (user_id,),
        ).fetchall()
    return _summarize_cart_rows(rows)


def _summarize_cart_rows(rows: list[Any]) -> tuple[list[dict[str, Any]], int]:
    items = []
    total = 0
    for row in rows:
        product = PRODUCT_BY_ID.get(row["product_id"])
        if product is None:
            continue
        quantity = int(row["quantity"])
        line_total = product["price_cents"] * quantity
        items.append({**product, "quantity": quantity, "line_total_cents": line_total})
        total += line_total
    return items, total


def _validate_checkout(payload: dict[str, object]) -> dict[str, str]:
    errors: dict[str, str] = {}
    required = {
        "name": "Enter your full name.",
        "address": "Enter your street address.",
        "city": "Enter your city.",
        "postal_code": "Enter a valid postal code.",
    }
    for field, message in required.items():
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            errors[field] = message
    postal = payload.get("postal_code")
    if isinstance(postal, str) and postal.strip() and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]{2,11}", postal.strip()):
        errors["postal_code"] = "Enter a valid postal code."
    return errors


def _login(email: str, password: str) -> tuple[int | None, str | None]:
    with connection() as db:
        user = db.execute(
            "SELECT id, password_salt, password_hash FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    if user is None or not secrets.compare_digest(
        str(user["password_hash"]), _password_hash(password, str(user["password_salt"]))
    ):
        return None, None
    return int(user["id"]), _new_session(int(user["id"]))


def _user_details(user_id: int) -> Any:
    with connection() as db:
        return db.execute(
            "SELECT id, email, name FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def _add_cart_item(
    user_id: int, product_id: str, quantity: int
) -> tuple[list[dict[str, Any]], int]:
    with connection() as db:
        db.execute(
            "INSERT INTO cart_items(user_id, product_id, quantity) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = "
            "CASE WHEN cart_items.quantity + excluded.quantity > 99 "
            "THEN 99 ELSE cart_items.quantity + excluded.quantity END",
            (user_id, product_id, quantity),
        )
    return _cart_summary(user_id)


def _is_integrity_error(error: Exception) -> bool:
    return isinstance(error, (sqlite3.IntegrityError, psycopg.IntegrityError))


def _login_error(message: str) -> HTMLResponse:
    body = (
        f'<p class="errors" role="alert">{_escape(message)}</p>'
        '<form action="/login" method="post">'
        '<label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="username" required>'
        '<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>'
        '<div class="actions"><button type="submit">Log in</button></div></form>'
    )
    return HTMLResponse(_layout("Log in", body), status_code=401)


@app.get("/api/health")
def health() -> dict[str, str]:
    with connection() as db:
        db.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/products")
def api_products(q: str = "") -> dict[str, list[dict[str, object]]]:
    query = q.strip().casefold()
    found = [
        product
        for product in PRODUCTS
        if not query
        or query in product["name"].casefold()
        or query in product["description"].casefold()
    ]
    return {"products": found}


@app.post("/api/auth/register")
async def api_register(request: Request) -> Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Request body must be a JSON object."}, status_code=400)
    email = payload.get("email")
    name = payload.get("name")
    password = payload.get("password")
    errors = {}
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()):
        errors["email"] = "Enter a valid email address."
    if not isinstance(name, str) or not name.strip():
        errors["name"] = "Enter your full name."
    if not isinstance(password, str) or len(password) < 8:
        errors["password"] = "Password must be at least 8 characters."
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    try:
        user_id = await run_in_threadpool(_create_user, email, name, password)
    except (sqlite3.IntegrityError, psycopg.IntegrityError):
        return JSONResponse({"errors": {"email": "An account with this email already exists."}}, status_code=409)
    token = await run_in_threadpool(_new_session, user_id)
    response = JSONResponse({"id": user_id, "email": email.strip().lower(), "name": name.strip()}, status_code=201)
    _set_session(response, token)
    return response


@app.post("/api/auth/login")
async def api_login(request: Request) -> Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Request body must be a JSON object."}, status_code=400)
    email = payload.get("email", "")
    password = payload.get("password", "")
    if not isinstance(email, str) or not isinstance(password, str) or not email.strip() or not password:
        return JSONResponse({"error": "Email and password are required."}, status_code=422)
    user_id, token = await run_in_threadpool(_login, email, password)
    if user_id is None or token is None:
        return JSONResponse({"error": "Email or password is incorrect."}, status_code=401)
    user = await run_in_threadpool(_user_details, user_id)
    response = JSONResponse({"id": user["id"], "email": user["email"], "name": user["name"]})
    _set_session(response, token)
    return response


@app.get("/api/cart")
def api_cart(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    items, total = _cart_summary(int(user["id"]))
    return JSONResponse({"items": items, "total_cents": total})


@app.post("/api/cart/items")
async def api_add_cart_item(request: Request) -> Response:
    user = await run_in_threadpool(_require_user, request)
    if user is None:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Request body must be a JSON object."}, status_code=400)
    product_id = payload.get("product_id")
    quantity = payload.get("quantity", 1)
    if product_id not in PRODUCT_BY_ID:
        return JSONResponse({"errors": {"product_id": "Choose an available product."}}, status_code=422)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 99:
        return JSONResponse({"errors": {"quantity": "Quantity must be between 1 and 99."}}, status_code=422)
    items, total = await run_in_threadpool(
        _add_cart_item, int(user["id"]), product_id, quantity
    )
    return JSONResponse({"items": items, "total_cents": total}, status_code=201)


@app.post("/api/orders")
async def api_create_order(request: Request) -> Response:
    user = await run_in_threadpool(_require_user, request)
    if user is None:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "Request body must be a JSON object."}, status_code=400)
    errors = _validate_checkout(payload)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    try:
        created = await run_in_threadpool(
            _create_order, int(user["id"]), payload
        )
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=409)
    return JSONResponse(
        {
            "id": created["id"],
            "total_cents": created["total_cents"],
            "items": created["items"],
            "status": "placed",
        },
        status_code=201,
    )


@app.get("/api/orders")
def api_orders(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    with connection() as db:
        orders = db.execute(
            "SELECT id, customer_name, total_cents, created_at FROM orders "
            "WHERE user_id = ? ORDER BY id DESC",
            (int(user["id"]),),
        ).fetchall()
        result = []
        for order in orders:
            items = db.execute(
                "SELECT product_id, product_name, unit_price_cents, quantity "
                "FROM order_items WHERE order_id = ? ORDER BY id",
                (order["id"],),
            ).fetchall()
            result.append({**dict(order), "items": [dict(item) for item in items]})
    return JSONResponse({"orders": result})


@app.delete("/api/account")
def api_delete_account(request: Request) -> Response:
    user = _require_user(request)
    if user is None:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    with connection() as db:
        db.execute("DELETE FROM users WHERE id = ?", (int(user["id"]),))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
def shop(request: Request, q: str = "") -> str:
    user = _current_user(request)
    query = q.strip()
    products = [
        product
        for product in PRODUCTS
        if not query
        or query.casefold() in product["name"].casefold()
        or query.casefold() in product["description"].casefold()
    ]
    product_cards = "".join(
        f'<article class="card"><h2>{_escape(product["name"])}</h2>'
        f'<p>{_escape(product["description"])}</p><p class="price">{_money(product["price_cents"])}</p>'
        + (
            f'<form action="/cart/add" method="post"><input type="hidden" name="product_id" value="{_escape(product["id"])}">'
            f'<button type="submit" aria-label="Add { _escape(product["name"]) } to cart">Add to cart</button></form>'
            if user
            else '<p class="muted">Log in to add items to your cart.</p>'
        )
        + "</article>"
        for product in products
    )
    result = product_cards or '<p role="status">No products found.</p>'
    body = (
        '<p>Thoughtful goods for your everyday adventures.</p>'
        '<form action="/" method="get"><label for="search">Search products</label>'
        f'<input id="search" name="q" value="{_escape(query)}" placeholder="Try coffee or mug">'
        '<div class="actions"><button type="submit">Search</button></div></form>'
        f'<section class="grid" aria-label="Products">{result}</section>'
    )
    return _layout("Shop", body, user)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> str:
    user = _current_user(request)
    body = (
        '<form action="/login" method="post">'
        '<label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="username" required>'
        '<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>'
        '<div class="actions"><button type="submit">Log in</button></div></form>'
        '<p class="muted">New here? <a href="/register">Create an account</a></p>'
    )
    return _layout("Log in", body, user)


@app.post("/login")
def login_form(email: str = Form(), password: str = Form()) -> Response:
    user_id, token = _login(email, password)
    if user_id is None or token is None:
        return _login_error("Email or password is incorrect.")
    response = RedirectResponse("/", status_code=303)
    _set_session(response, token)
    return response


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> str:
    body = (
        '<form action="/register" method="post">'
        '<label for="name">Full name</label><input id="name" name="name" autocomplete="name" required>'
        '<label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="email" required>'
        '<label for="password">Password</label><input id="password" name="password" type="password" minlength="8" autocomplete="new-password" required>'
        '<div class="actions"><button type="submit">Create account</button></div></form>'
    )
    return _layout("Create account", body, _current_user(request))


@app.post("/register")
def register_form(name: str = Form(), email: str = Form(), password: str = Form()) -> Response:
    errors = []
    if not name.strip():
        errors.append("Enter your full name.")
    if not EMAIL_RE.fullmatch(email.strip()):
        errors.append("Enter a valid email address.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if errors:
        return HTMLResponse(
            _layout("Create account", f'<p role="alert" class="errors">{_escape(" ".join(errors))}</p>'),
            status_code=422,
        )
    try:
        user_id = _create_user(email, name, password)
    except (sqlite3.IntegrityError, psycopg.IntegrityError):
        return HTMLResponse(
            _layout("Create account", '<p role="alert" class="errors">An account with this email already exists.</p>'),
            status_code=409,
        )
    response = RedirectResponse("/", status_code=303)
    _set_session(response, _new_session(user_id))
    return response


@app.post("/logout")
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with connection() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.post("/cart/add")
def add_to_cart(request: Request, product_id: str = Form()) -> Response:
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if product_id not in PRODUCT_BY_ID:
        return Response("Product not found.", status_code=404)
    with connection() as db:
        db.execute(
            "INSERT INTO cart_items(user_id, product_id, quantity) VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = "
            "CASE WHEN cart_items.quantity + 1 > 99 "
            "THEN 99 ELSE cart_items.quantity + 1 END",
            (int(user["id"]), product_id),
        )
    return RedirectResponse("/cart", status_code=303)


@app.post("/cart/update")
def update_cart(request: Request, product_id: str = Form(), quantity: int = Form()) -> Response:
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if product_id not in PRODUCT_BY_ID or not 1 <= quantity <= 99:
        return Response("Choose a valid product and quantity (1–99).", status_code=422)
    with connection() as db:
        db.execute(
            "UPDATE cart_items SET quantity = ? WHERE user_id = ? AND product_id = ?",
            (quantity, int(user["id"]), product_id),
        )
    return RedirectResponse("/cart", status_code=303)


@app.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request) -> Response:
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    items, total = _cart_summary(int(user["id"]))
    if not items:
        body = '<p role="status">Your cart is empty.</p><a href="/">Continue shopping</a>'
    else:
        rows = "".join(
            f'<section class="row"><div><strong>{_escape(item["name"])}</strong>'
            f'<p class="muted">{_money(item["price_cents"])} each · Line total: '
            f'<span aria-label="Line total for { _escape(item["name"]) }">{_money(item["line_total_cents"])}</span></p></div>'
            f'<form action="/cart/update" method="post"><input type="hidden" name="product_id" value="{_escape(item["id"])}">'
            f'<label for="quantity-{_escape(item["id"])}">Quantity for {_escape(item["name"])}</label>'
            f'<input class="quantity" id="quantity-{_escape(item["id"])}" name="quantity" type="number" min="1" max="99" value="{item["quantity"]}">'
            '<button class="secondary" type="submit">Update</button></form></section>'
            for item in items
        )
        body = (
            f'<div class="panel">{rows}<p><strong>Cart total: '
            f'<span aria-label="Cart total">{_money(total)}</span></strong></p>'
            '<a href="/checkout">Proceed to checkout</a></div>'
        )
    return HTMLResponse(_layout("Your cart", body, user))


@app.get("/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, errors: str = "") -> Response:
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    items, total = _cart_summary(int(user["id"]))
    if not items:
        return RedirectResponse("/cart", status_code=303)
    error_body = f'<p role="alert" class="errors">{_escape(errors)}</p>' if errors else ""
    body = (
        f'<p>Order total: <strong>{_money(total)}</strong></p>{error_body}'
        '<form action="/checkout" method="post" novalidate>'
        '<label for="name">Full name</label><input id="name" name="name" autocomplete="name">'
        '<label for="address">Street address</label><input id="address" name="address" autocomplete="street-address">'
        '<label for="city">City</label><input id="city" name="city" autocomplete="address-level2">'
        '<label for="postal_code">Postal code</label><input id="postal_code" name="postal_code" autocomplete="postal-code">'
        '<div class="actions"><button type="submit">Place order</button></div></form>'
    )
    return HTMLResponse(_layout("Checkout", body, user))


@app.post("/checkout")
def checkout_form(
    request: Request,
    name: str = Form(),
    address: str = Form(),
    city: str = Form(),
    postal_code: str = Form(),
) -> Response:
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    payload = {"name": name, "address": address, "city": city, "postal_code": postal_code}
    errors = _validate_checkout(payload)
    if errors:
        message = " ".join(errors.values())
        return HTMLResponse(
            _layout("Checkout", f'<p role="alert" class="errors">{_escape(message)}</p>'),
            status_code=422,
        )
    try:
        created = _create_order(int(user["id"]), payload)
    except ValueError as error:
        return HTMLResponse(
            _layout("Checkout", f'<p role="alert" class="errors">{_escape(error)}</p>'),
            status_code=409,
        )
    return RedirectResponse(f"/orders/{created['id']}", status_code=303)


def _create_order(user_id: int, payload: dict[str, object]) -> dict[str, Any]:
    with connection() as db:
        if not db.postgres:
            db.execute("BEGIN IMMEDIATE")
        cart_query = (
            "SELECT product_id, quantity FROM cart_items "
            "WHERE user_id = ? ORDER BY product_id"
        )
        if db.postgres:
            cart_query += " FOR UPDATE"
        rows = db.execute(cart_query, (user_id,)).fetchall()
        items, total = _summarize_cart_rows(rows)
        if not items:
            raise ValueError("Your cart is empty.")
        cursor = db.execute(
            "INSERT INTO orders(user_id, customer_name, address, city, postal_code, total_cents) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (
                user_id,
                str(payload["name"]).strip(),
                str(payload["address"]).strip(),
                str(payload["city"]).strip(),
                str(payload["postal_code"]).strip(),
                total,
            ),
        )
        order_id = int(cursor.fetchone()["id"])
        db.executemany(
            "INSERT INTO order_items(order_id, product_id, product_name, unit_price_cents, quantity) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (order_id, item["id"], item["name"], item["price_cents"], item["quantity"])
                for item in items
            ],
        )
        db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    return {"id": order_id, "total_cents": total, "items": items}


@app.get("/orders", response_class=HTMLResponse)
def order_history(request: Request) -> Response:
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    with connection() as db:
        orders = db.execute(
            "SELECT id, total_cents, created_at FROM orders WHERE user_id = ? ORDER BY id DESC",
            (int(user["id"]),),
        ).fetchall()
    if not orders:
        body = '<p role="status">You have no orders yet.</p><a href="/">Browse the shop</a>'
    else:
        body = '<div class="panel">' + "".join(
            f'<section class="row"><span>Order #{order["id"]}</span>'
            f'<span>{_money(order["total_cents"])}</span>'
            f'<a href="/orders/{order["id"]}">View order</a></section>'
            for order in orders
        ) + "</div>"
    return HTMLResponse(_layout("Order history", body, user))


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int) -> Response:
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    with connection() as db:
        order = db.execute(
            "SELECT id, total_cents, created_at FROM orders WHERE id = ? AND user_id = ?",
            (order_id, int(user["id"])),
        ).fetchone()
        items = db.execute(
            "SELECT product_name, quantity FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall() if order else []
    if order is None:
        return HTMLResponse(_layout("Order not found", '<p role="alert">This order could not be found.</p>', user), status_code=404)
    body = (
        f'<p class="notice" role="status">Order placed successfully. Order #{order["id"]}</p>'
        '<h2>Items</h2><ul>'
        + "".join(f'<li>{_escape(item["product_name"])} × {item["quantity"]}</li>' for item in items)
        + f'</ul><p><strong>Order total: {_money(order["total_cents"])}</strong></p>'
        '<a href="/orders">View order history</a>'
    )
    return HTMLResponse(_layout(f"Order #{order['id']}", body, user))


@app.get("/api/orders/{order_id}")
def api_order_detail(request: Request, order_id: int) -> Response:
    user = _require_user(request)
    if user is None:
        return JSONResponse({"error": "Authentication required."}, status_code=401)
    with connection() as db:
        order = db.execute(
            "SELECT id, customer_name, address, city, postal_code, total_cents, created_at "
            "FROM orders WHERE id = ? AND user_id = ?",
            (order_id, int(user["id"])),
        ).fetchone()
        if order is None:
            return JSONResponse({"error": "Order not found."}, status_code=404)
        items = db.execute(
            "SELECT product_id, product_name, unit_price_cents, quantity "
            "FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall()
    return JSONResponse({**dict(order), "items": [dict(item) for item in items]})
