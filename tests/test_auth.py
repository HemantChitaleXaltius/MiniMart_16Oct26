"""Authentication and access-control tests: login, logout, and who may open what.

These use only the fixtures from tests/conftest.py (db_path, app, client).
The helper functions below are plain functions, not fixtures.
"""

import sqlite3
from urllib.parse import urlparse

import pytest
from werkzeug.security import check_password_hash

import config

NEW_PRODUCT = {"name": "Pen", "description": "Blue ballpoint pen", "price": "1.50"}


# ---------- helpers (plain functions, not fixtures) ----------

def seeded_password(username):
    # The password init_db() gave the seeded account, read the same way init_db() does.
    names = {"admin": "MINIMART_ADMIN_PASSWORD", "shopper": "MINIMART_SHOPPER_PASSWORD"}
    return config.seed_password(names[username])


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def log_in_as(client, username):
    response = login(client, username, seeded_password(username))
    assert response.status_code == 302  # fail loudly if the setup step itself broke
    return response


def redirect_path(response):
    # Where a redirect points, ignoring whether Flask wrote it as "/x" or "http://host/x".
    return urlparse(response.headers["Location"]).path


def product_count(db_path):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    finally:
        connection.close()


# ---------- login: success ----------

# If this fails, a correct admin login no longer sends the person to the home page.
def test_correct_admin_password_redirects_to_home(client):
    response = login(client, "admin", seeded_password("admin"))
    assert response.status_code == 302
    assert redirect_path(response) == "/"


# If this fails, logging in no longer remembers who you are or that you are an admin.
def test_correct_admin_password_stores_username_and_admin_role_in_session(client):
    log_in_as(client, "admin")
    with client.session_transaction() as sess:
        assert sess["username"] == "admin"
        assert sess["role"] == "admin"


# If this fails, shoppers are being given the wrong role when they log in.
def test_correct_shopper_password_stores_shopper_role_in_session(client):
    log_in_as(client, "shopper")
    with client.session_transaction() as sess:
        assert sess["username"] == "shopper"
        assert sess["role"] == "shopper"


# ---------- login: failures ----------

# If this fails, someone can log in as admin with the wrong password.
def test_wrong_password_does_not_log_in(client):
    response = login(client, "admin", "definitely-wrong")
    assert response.status_code == 200  # login page shown again, no redirect
    with client.session_transaction() as sess:
        assert "username" not in sess
        assert "role" not in sess


# If this fails, a username that does not exist can still get logged in.
def test_unknown_username_does_not_log_in(client):
    response = login(client, "nobody", "whatever")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert "username" not in sess


# If this fails, submitting an empty login form can log someone in (or crash the page).
def test_empty_login_form_does_not_log_in(client):
    response = client.post("/login", data={})
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert "username" not in sess


# If this fails, the login query is open to SQL injection and the SQL trick gets someone in.
@pytest.mark.parametrize(
    "username",
    ["admin' --", "' OR '1'='1"],
    ids=["comment-out-the-password-check", "always-true-condition"],
)
def test_sql_injection_style_username_does_not_log_in(client, username):
    response = login(client, username, "anything")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert "username" not in sess


# If this fails, the login page reveals which usernames exist (it answers differently).
def test_wrong_password_and_unknown_user_get_identical_responses(client):
    wrong_password = login(client, "admin", "definitely-wrong")
    unknown_user = login(client, "nobody", "definitely-wrong")
    assert wrong_password.status_code == unknown_user.status_code
    assert wrong_password.data == unknown_user.data


# If this fails, passwords are being stored readable in the database instead of hashed.
def test_seeded_passwords_are_stored_hashed_not_as_plain_text(app, db_path):
    connection = sqlite3.connect(db_path)
    try:
        stored = dict(connection.execute("SELECT username, password_hash FROM users").fetchall())
    finally:
        connection.close()
    for username in ("admin", "shopper"):
        plain = seeded_password(username)
        assert stored[username] != plain
        assert check_password_hash(stored[username], plain)


# If this fails, one visitor logging in logs in every other visitor too (shared session).
def test_one_clients_login_does_not_log_in_another_client(app, client):
    log_in_as(client, "admin")
    other_client = app.test_client()
    response = other_client.get("/admin")
    assert response.status_code == 302
    assert redirect_path(response) == "/login"


# ---------- who may open what ----------

# If this fails, one of these pages is open to people who are not logged in.
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/admin"),
        ("GET", "/admin/add"),
        ("POST", "/admin/add"),
        ("GET", "/checkout"),
        ("POST", "/checkout"),
    ],
    ids=["admin-page", "add-product-form", "add-product-submit", "checkout-page", "checkout-submit"],
)
def test_anonymous_visitor_is_redirected_to_login_from_protected_pages(client, method, path):
    response = client.open(path, method=method)
    assert response.status_code == 302
    assert redirect_path(response) == "/login"


# If this fails, a plain shopper can reach an admin page (or submit the admin form).
@pytest.mark.parametrize(
    "method,path",
    [("GET", "/admin"), ("GET", "/admin/add"), ("POST", "/admin/add")],
    ids=["admin-page", "add-product-form", "add-product-submit"],
)
def test_shopper_is_forbidden_from_admin_pages(client, method, path):
    log_in_as(client, "shopper")
    response = client.open(path, method=method, data=NEW_PRODUCT if method == "POST" else None)
    assert response.status_code == 403


# If this fails, an anonymous visitor can add products to the shop.
def test_anonymous_post_to_add_product_does_not_create_a_product(client, db_path):
    before = product_count(db_path)
    client.post("/admin/add", data=NEW_PRODUCT)
    assert product_count(db_path) == before


# If this fails, a shopper can add products to the shop even though they get an error page.
def test_shopper_post_to_add_product_does_not_create_a_product(client, db_path):
    log_in_as(client, "shopper")
    before = product_count(db_path)
    client.post("/admin/add", data=NEW_PRODUCT)
    assert product_count(db_path) == before


# If this fails, someone who is not logged in can place an order and empty their cart.
def test_anonymous_checkout_post_does_not_empty_the_cart(client):
    client.post("/cart/add/1")
    client.post("/checkout")
    with client.session_transaction() as sess:
        assert sess["cart"] == [1]


# If this fails, a logged-in admin is wrongly kept out of the admin page.
def test_admin_can_open_the_admin_page_and_sees_the_products(client):
    log_in_as(client, "admin")
    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Notebook" in response.data  # one of the seeded products


# ---------- logout ----------

# If this fails, logging out does not remove who you are from the session.
def test_logout_removes_username_and_role_from_session(client):
    log_in_as(client, "admin")
    response = client.get("/logout")
    assert response.status_code == 302
    assert redirect_path(response) == "/"
    with client.session_transaction() as sess:
        assert "username" not in sess
        assert "role" not in sess


# If this fails, a person who logged out can still use admin pages (back-button problem).
def test_admin_page_is_blocked_again_after_logout(client):
    log_in_as(client, "admin")
    client.get("/logout")
    response = client.get("/admin")
    assert response.status_code == 302
    assert redirect_path(response) == "/login"


# If this fails, logout stops clearing the cart (this pins down today's behaviour).
def test_logout_also_empties_the_cart(client):
    client.post("/cart/add/1")
    log_in_as(client, "shopper")
    client.get("/logout")
    with client.session_transaction() as sess:
        assert "cart" not in sess


# If this fails, visiting /logout without being logged in crashes instead of just redirecting.
def test_logout_when_not_logged_in_just_redirects_home(client):
    response = client.get("/logout")
    assert response.status_code == 302
    assert redirect_path(response) == "/"
