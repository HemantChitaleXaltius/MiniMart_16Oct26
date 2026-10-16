"""Smoke tests: a quick gate that the app starts and the basics work."""

import os
import sqlite3

import config


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_each_test_uses_its_own_fresh_database(app, db_path):
    # Not the real database, and the file really exists in the temp folder.
    assert app.config["DATABASE"] == db_path
    assert db_path != config.DATABASE
    assert os.path.exists(db_path)
    # Freshly created: only the 4 sample products, nothing left by other tests.
    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    finally:
        connection.close()
    assert count == 4


def test_admin_page_redirects_anonymous_visitors_to_login(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_seeded_admin_can_log_in(client, app):
    # Read the seeded admin's password the same way init_db() does.
    password = config.seed_password("MINIMART_ADMIN_PASSWORD")
    response = client.post("/login", data={"username": "admin", "password": password})
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "admin"
        assert sess["role"] == "admin"


def test_add_to_cart_stores_product_in_session(client):
    client.post("/cart/add/1")
    with client.session_transaction() as sess:
        assert sess["cart"] == [1]
