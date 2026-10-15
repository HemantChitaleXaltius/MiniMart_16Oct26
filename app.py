"""MiniMart: hashed passwords, settings from the environment, and role checks.

The secret key, database path, debug mode and first-run passwords are read from
environment variables by config.py. See .env.example for the setting names.
"""

import sqlite3
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
DATABASE = config.DATABASE


def get_db():
    connection = sqlite3.connect(DATABASE)
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
        app.logger.exception("Database initialisation failed")
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
        app.logger.exception("Cart query failed")
        return []
    finally:
        connection.close()


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


if __name__ == "__main__":
    init_db()
    app.run(debug=config.DEBUG)
