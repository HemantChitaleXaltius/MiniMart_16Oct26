"""Shared pytest fixtures for MiniMart.

Every test that asks for `app` (or `client`) gets a brand-new app that points
at its own empty SQLite file, so tests cannot affect each other or your real
database.
"""

import pytest

from app import create_app, init_db


@pytest.fixture
def db_path(tmp_path):
    # tmp_path is a fresh folder pytest creates for EACH test function and
    # deletes later. A file inside it can never be shared with another test.
    return str(tmp_path / "test.db")


@pytest.fixture
def app(db_path):
    # Pass the temporary path in, so the app never touches config.DATABASE.
    app = create_app(database=db_path, test_config={"TESTING": True})
    with app.app_context():
        init_db()  # creates the tables and the sample products in the temp file
    return app


@pytest.fixture
def client(app):
    # A fresh browser-like client, with its own empty session (cart, login).
    return app.test_client()
