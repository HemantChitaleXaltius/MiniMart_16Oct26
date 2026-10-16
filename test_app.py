"""Basic MiniMart tests. Run with:  python -m unittest -v"""

import os
import sqlite3
import tempfile
import unittest

from werkzeug.security import generate_password_hash

import config
from app import create_app, init_db


class MiniMartTestCase(unittest.TestCase):
    def setUp(self):
        # Every test gets its own empty database in a temporary folder.
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.app = create_app(database=self.db_path, test_config={"TESTING": True})
        with self.app.app_context():
            init_db()
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def add_user(self, username, password, role):
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
        connection.commit()
        connection.close()


class DatabaseIsolationTests(MiniMartTestCase):
    def test_app_uses_the_test_database_not_the_real_one(self):
        self.assertEqual(self.app.config["DATABASE"], self.db_path)
        self.assertNotEqual(self.db_path, config.DATABASE)
        self.assertTrue(os.path.exists(self.db_path))

    def test_each_app_has_its_own_database(self):
        other_path = os.path.join(self.tmp.name, "other.db")
        other_app = create_app(database=other_path, test_config={"TESTING": True})
        self.assertNotEqual(other_app.config["DATABASE"], self.app.config["DATABASE"])


class AccessTests(MiniMartTestCase):
    def test_admin_page_redirects_anonymous_visitors_to_login(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_shopper_is_forbidden_from_admin_page(self):
        self.add_user("tester", "pw12345", "shopper")
        self.client.post("/login", data={"username": "tester", "password": "pw12345"})
        self.assertEqual(self.client.get("/admin").status_code, 403)

    def test_login_stores_username_and_role_in_session(self):
        self.add_user("boss", "pw12345", "admin")
        response = self.client.post("/login", data={"username": "boss", "password": "pw12345"})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["username"], "boss")
            self.assertEqual(sess["role"], "admin")


class CartTests(MiniMartTestCase):
    def test_add_to_cart_stores_product_id_in_session(self):
        self.client.post("/cart/add/1")
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["cart"], [1])

    def test_carts_are_not_shared_between_clients(self):
        self.client.post("/cart/add/1")
        other_client = self.app.test_client()
        with other_client.session_transaction() as sess:
            self.assertEqual(sess.get("cart", []), [])


if __name__ == "__main__":
    unittest.main()
