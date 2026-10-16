"""MiniMart: hashed passwords, settings from the environment, and role checks.

The secret key, database path, debug mode and first-run passwords are read from
environment variables by config.py. See .env.example for the setting names.

The Flask app is built by create_app(), so tests can create their own app with
their own throwaway database.
"""

import logging
import os
import sqlite3
import time
from functools import wraps
from logging.handlers import RotatingFileHandler

from flask import Flask, abort, current_app, flash, has_request_context, redirect, render_template, request, session, url_for
from flask.logging import default_handler
from werkzeug.security import check_password_hash, generate_password_hash

import config

LOG_FORMAT = "%(asctime)sZ %(levelname)-8s %(name)s user=%(user)s %(method)s %(path)s | %(message)s"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _one_line(text, limit=200):
    """Escape line breaks and odd characters and cut the length, so text typed by a
    visitor cannot forge extra log lines."""
    return str(text).encode("unicode_escape").decode("ascii")[:limit]


class RequestContextFilter(logging.Filter):
    """Adds who/what to every log line: username, HTTP method and URL path.

    Deliberately limited to those three. It never reads the query string, form
    data, headers, cookies or the session contents, so passwords, hashes and
    tokens cannot reach the log through this filter.
    """

    def filter(self, record):
        if has_request_context():
            record.user = _one_line(session.get("username", "-"))
            record.method = _one_line(request.method)
            record.path = _one_line(request.path)
        else:
            record.user = record.method = record.path = "-"
        return True


def configure_logging(app, level=None, log_dir=None):
    """Send MiniMart's log lines to the console and to logs/minimart.log.

    level   -- DEBUG, INFO, WARNING, ERROR or CRITICAL. If not given, it is read
               from MINIMART_LOG_LEVEL in the environment (your .env), else INFO.
               An unrecognised value falls back to INFO and logs a warning.
    log_dir -- folder for the log file. Default: a "logs" folder next to app.py.
               While testing (app.testing) no file is written unless you pass this.

    Safe to call more than once: it replaces its own handlers instead of adding more.
    """
    requested = str(level or os.environ.get("MINIMART_LOG_LEVEL") or "INFO").strip().upper()
    level_name = requested if requested in LOG_LEVELS else "INFO"

    logger = app.logger
    logger.setLevel(getattr(logging, level_name))
    # Flask adds its own console handler; remove it so lines are not printed twice.
    logger.removeHandler(default_handler)
    # Remove the handlers a previous call added (they are marked _minimart).
    for old in [h for h in logger.handlers if getattr(h, "_minimart", False)]:
        logger.removeHandler(old)
        old.close()

    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime  # timestamps in UTC; the trailing Z means UTC

    handlers = [logging.StreamHandler()]  # console (stderr)
    log_file = None
    file_problem = None
    if log_dir is not None or not app.testing:
        folder = log_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        try:
            os.makedirs(folder, exist_ok=True)
            log_file = os.path.join(folder, "minimart.log")
            # Rotates at about 1 MB and keeps 5 old files, so the disk cannot fill up.
            handlers.append(RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8"))
        except OSError as error:
            log_file = None
            file_problem = f"{folder}: {error.strerror}"

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RequestContextFilter())
        handler._minimart = True
        logger.addHandler(handler)

    # Avoid duplicate lines if something configures the root logger. Tests keep
    # propagation on so pytest's caplog can see the messages.
    logger.propagate = app.testing

    if file_problem:
        logger.warning("Could not open the log file (%s); logging to the console only", file_problem)
    if requested != level_name:
        logger.warning("Unknown MINIMART_LOG_LEVEL %r; using INFO", _one_line(requested, 30))
    logger.info("Logging configured: level=%s file=%s", level_name, log_file or "none")


def get_db():
    connection = sqlite3.connect(current_app.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    return connection

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            flash("Please log in to check out.", "danger")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def init_db():
    """Create tables and first-run data. Must be called inside an app context."""
    connection = get_db()
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL, price REAL NOT NULL)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            )   """
        )
        if connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO products (name, description, price) VALUES (?, ?, ?)",
                [("Notebook", "A5 ruled notebook", 4.50), ("Water Bottle", "Reusable 750 ml bottle", 12.00), ("Wireless Mouse", "Compact USB mouse", 18.90), ("Desk Lamp", "LED study lamp", 24.50)],
            )
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed_users = [
                ("admin", config.seed_password("MINIMART_ADMIN_PASSWORD"), "admin"),
                ("shopper", config.seed_password("MINIMART_SHOPPER_PASSWORD"), "shopper"),
            ]
            for username, password, role in seed_users:
                connection.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), role),
                )
        connection.commit()
    except sqlite3.Error:
        current_app.logger.exception("Database initialisation failed")
        raise
    finally:
        connection.close()


def fetch_cart_products():
    ids = session.get("cart", [])
    if not ids:
        return []
    connection = get_db()
    try:
        placeholders = ",".join("?" for _ in ids)
        return connection.execute(f"SELECT * FROM products WHERE id IN ({placeholders})", ids).fetchall()
    except sqlite3.Error:
        current_app.logger.exception("Cart query failed")
        return []
    finally:
        connection.close()


def create_app(database=None, test_config=None):
    """Build a fresh MiniMart app.

    database    -- path to the SQLite file; defaults to config.DATABASE.
    test_config -- optional dict of extra settings, e.g. {"TESTING": True}.
    """
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config["DATABASE"] = database or config.DATABASE
    if test_config:
        app.config.update(test_config)
    configure_logging(app)

    @app.route("/")
    def home():
        connection = get_db()
        products = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
        connection.close()
        return render_template("index.html", products=products)

    @app.route("/search")
    def search():
        term = request.args.get("q", "")
        connection = get_db()
        try:
            products = connection.execute("SELECT * FROM products WHERE name LIKE ?", (f"%{term}%",)).fetchall()
        except sqlite3.Error:
            app.logger.exception("Search failed")
            products = []
            flash("Search is temporarily unavailable.", "danger")
        finally:
            connection.close()
        return render_template("search.html", products=products, term=term)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            connection = get_db()
            try:
                user = connection.execute(
                    "SELECT username, password_hash, role FROM users WHERE username = ?",
                    (username,),
                ).fetchone()
            except sqlite3.Error:
                app.logger.exception("Login query failed")
                user = None
            finally:
                connection.close()
            if user and check_password_hash(user["password_hash"], password):
                session["username"] = user["username"]
                session["role"] = user["role"]
                return redirect(url_for("home"))
            flash("Wrong username or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    @app.post("/cart/add/<int:product_id>")
    def add_to_cart(product_id):
        ids = session.get("cart", [])
        ids.append(product_id)
        session["cart"] = ids
        return redirect(request.referrer or url_for("home"))

    @app.route("/cart")
    def cart():
        products = fetch_cart_products()
        return render_template("cart.html", products=products, total=sum(p["price"] for p in products))

    @app.route("/checkout", methods=["GET", "POST"])
    @login_required
    def checkout():
        products = fetch_cart_products()
        total = sum(p["price"] for p in products)
        if request.method == "POST":
            session["cart"] = []
            return render_template("message.html", title="Order placed", message=f"Thank you. Your order contained {len(products)} item(s).", category="success")
        return render_template("checkout.html", count=len(products), total=total)

    @app.route("/admin")
    @admin_required
    def admin():
        connection = get_db()
        products = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
        connection.close()
        return render_template("admin.html", products=products)

    @app.route("/admin/add", methods=["GET", "POST"])
    @admin_required
    def admin_add():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            raw_price = request.form.get("price", "")
            try:
                price = float(raw_price)
            except ValueError:
                flash("Price must be a number.", "danger")
                return render_template("add_product.html"), 400
            if not name:
                flash("Product name is required.", "danger")
                return render_template("add_product.html"), 400
            if price < 0:
                flash("Price cannot be negative.", "danger")
                return render_template("add_product.html"), 400
            connection = get_db()
            try:
                connection.execute("INSERT INTO products (name, description, price) VALUES (?, ?, ?)", (name, description, price))
                connection.commit()
            except sqlite3.Error:
                app.logger.exception("Adding product failed")
                flash("The product could not be saved.", "danger")
                return render_template("add_product.html"), 500
            finally:
                connection.close()
            return redirect(url_for("admin"))
        return render_template("add_product.html")

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        init_db()
    app.run(debug=config.DEBUG)
