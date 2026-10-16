"""Edge-case tests: unusual or hostile input that the normal flows don't exercise.

Uses only the fixtures from tests/conftest.py (db_path, app, client).

Tests marked xfail(strict=True) describe what the app SHOULD do but currently
does not (a known bug). They show up as "xfailed" and do not turn CI red. When
the bug is fixed the test starts passing, pytest reports that as a failure
("XPASS strict"), and you then delete the xfail marker so it guards the fix.
"""

import sqlite3

import pytest

import config

VALID_PRODUCT = {"name": "Pen", "description": "Blue ballpoint pen", "price": "1.50"}


# ---------- helpers (plain functions, not fixtures) ----------

def seeded_password(username):
    names = {"admin": "MINIMART_ADMIN_PASSWORD", "shopper": "MINIMART_SHOPPER_PASSWORD"}
    return config.seed_password(names[username])


def log_in_as(client, username):
    response = client.post(
        "/login", data={"username": username, "password": seeded_password(username)}
    )
    assert response.status_code == 302  # fail loudly if the setup step itself broke


def product_count(db_path):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    finally:
        connection.close()


def product_form(price):
    return {**VALID_PRODUCT, "price": price}


# ---------- 1. checking out with an empty cart ----------

# If this fails, a shopper can "place an order" for nothing and is told "Order placed".
@pytest.mark.xfail(
    strict=True,
    reason="BUG: checkout accepts an empty cart and answers 200 'Order placed ... 0 item(s)'",
)
def test_checkout_with_an_empty_cart_is_refused(client):
    log_in_as(client, "shopper")
    response = client.post("/checkout")
    assert response.status_code in (302, 400)  # sent back to the cart, or rejected
    assert b"Order placed" not in response.data


# ---------- 2. negative price ----------

# If this fails, the shop can end up selling a product with a negative price.
@pytest.mark.parametrize("price", ["-0.01", "-5", "-1000000"])
def test_negative_price_is_rejected_and_nothing_is_saved(client, db_path, price):
    log_in_as(client, "admin")
    before = product_count(db_path)
    response = client.post("/admin/add", data=product_form(price))
    assert response.status_code == 400
    assert product_count(db_path) == before


# ---------- 3. price that is not a number ----------

# If this fails, text like "abc" can be saved as a price (or crashes the form).
@pytest.mark.parametrize("price", ["abc", "", "twelve", "12,50"])
def test_non_numeric_price_is_rejected_and_nothing_is_saved(client, db_path, price):
    log_in_as(client, "admin")
    before = product_count(db_path)
    response = client.post("/admin/add", data=product_form(price))
    assert response.status_code == 400
    assert product_count(db_path) == before


# If this fails, "nan", "inf" or an overflow like 1e999 can be used as a product price.
@pytest.mark.xfail(
    strict=True,
    reason="BUG: float() accepts nan/inf; 'nan' gives a 500 error, 'inf' and '1e999' are saved",
)
@pytest.mark.parametrize("price", ["nan", "inf", "1e999"])
def test_not_a_real_number_price_is_rejected_and_nothing_is_saved(client, db_path, price):
    log_in_as(client, "admin")
    before = product_count(db_path)
    response = client.post("/admin/add", data=product_form(price))
    assert response.status_code == 400
    assert product_count(db_path) == before


# ---------- 4. registering a username that already exists ----------
# NOT WRITTEN: the app has no registration route, so there is nothing to test.
# POST /register answers 404. See the explanation in the chat.


# ---------- 5. a shopper trying to reach every admin route ----------

# If this fails, some admin route (including one added later) is open to plain shoppers.
def test_shopper_is_forbidden_on_every_admin_route_and_method(app, client):
    log_in_as(client, "shopper")
    adapter = app.url_map.bind("localhost")
    checked = 0
    offenders = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/admin"):
            continue
        path = adapter.build(rule.endpoint, {name: 1 for name in rule.arguments})
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            data = VALID_PRODUCT if method == "POST" else None
            status = client.open(path, method=method, data=data).status_code
            checked += 1
            if status != 403:
                offenders.append(f"{method} {path} -> {status}")
    assert checked >= 3, "found fewer admin routes than expected; is the /admin prefix still right?"
    assert offenders == []


# If this fails, a shopper can use an unexpected HTTP method to get past an admin route.
@pytest.mark.parametrize(
    "method,path",
    [("POST", "/admin"), ("PUT", "/admin/add"), ("DELETE", "/admin/add")],
    ids=["post-admin", "put-add", "delete-add"],
)
def test_shopper_cannot_succeed_with_unexpected_methods_on_admin_routes(client, method, path):
    log_in_as(client, "shopper")
    response = client.open(path, method=method)
    assert response.status_code in (403, 405)  # refused outright, never a 2xx or redirect


# ---------- 6. correct username, wrong password ----------

# If this fails, a correct username with a wrong password can log someone in.
@pytest.mark.parametrize("username", ["admin", "shopper"])
def test_correct_username_with_wrong_password_does_not_log_in(client, username):
    response = client.post("/login", data={"username": username, "password": "not-the-password"})
    assert response.status_code == 200  # login page shown again, no redirect
    with client.session_transaction() as sess:
        assert "username" not in sess
        assert "role" not in sess


# If this fails, a failed admin login while logged in as a shopper changes who you are.
def test_failed_login_does_not_change_who_is_logged_in(client):
    log_in_as(client, "shopper")
    response = client.post("/login", data={"username": "admin", "password": "not-the-password"})
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess["username"] == "shopper"
        assert sess["role"] == "shopper"
    assert client.get("/admin").status_code == 403
