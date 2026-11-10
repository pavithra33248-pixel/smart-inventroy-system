
import os
import re
from decimal import Decimal, InvalidOperation

import pandas as pd
import MySQLdb.cursors

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_mysqldb import MySQL


# --------------------------------------------------
# FLASK APPLICATION CONFIGURATION
# --------------------------------------------------

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "dev-only-change-this-key"
)

app.config["MYSQL_HOST"] = os.getenv("MYSQL_HOST", "localhost")
app.config["MYSQL_USER"] = os.getenv("MYSQL_USER", "root")
app.config["MYSQL_PASSWORD"] = os.getenv("MYSQL_PASSWORD", "")
app.config["MYSQL_DB"] = os.getenv("MYSQL_DB", "smart_inventory")

# Return database rows as dictionaries
app.config["MYSQL_CURSORCLASS"] = "DictCursor"

# Maximum CSV upload size: 20 MB
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

mysql = MySQL(app)

ALLOWED_EXTENSIONS = {"csv"}


# --------------------------------------------------
# DATABASE HELPER FUNCTIONS
# --------------------------------------------------

def query_all(sql, params=()):
    """Fetch all rows as dictionaries."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def query_one(sql, params=()):
    """Fetch one row as a dictionary."""
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    """Execute an INSERT, UPDATE, or DELETE query."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        cur.execute(sql, params)
        mysql.connection.commit()
        return cur.lastrowid
    except Exception:
        mysql.connection.rollback()
        raise
    finally:
        cur.close()


# --------------------------------------------------
# STOCK ALERT MANAGEMENT
# --------------------------------------------------

def check_alert(product_id, name, quantity, reorder_level):
    """Create a stock alert or remove an outdated alert."""

    if quantity <= 0:
        alert_type = "OUT_OF_STOCK"
        message = f"{name} is out of stock. Restock required."

    elif quantity <= reorder_level:
        alert_type = "LOW_STOCK"
        message = (
            f"{name} is low in stock "
            f"({quantity} remaining; "
            f"reorder level {reorder_level})."
        )

    else:
        execute(
            "DELETE FROM notifications WHERE product_id=%s",
            (product_id,)
        )
        return

    # Keep only one active notification per product
    execute(
        "DELETE FROM notifications WHERE product_id=%s",
        (product_id,)
    )

    execute(
        """
        INSERT INTO notifications
            (product_id, alert_type, message)
        VALUES (%s, %s, %s)
        """,
        (product_id, alert_type, message)
    )


# --------------------------------------------------
# PRODUCT FORM VALIDATION
# --------------------------------------------------

def product_from_form():
    """Read and validate product form fields."""

    store_id = (
        request.form.get("store_id") or "MAIN"
    ).strip()[:30]

    code = (
        request.form.get("product_code") or ""
    ).strip()[:60]

    name = (
        request.form.get("product_name") or ""
    ).strip()[:160]

    category = (
        request.form.get("category") or ""
    ).strip()[:100]

    try:
        quantity = int(request.form.get("quantity", "0"))
        reorder_level = int(
            request.form.get("reorder_level", "10")
        )
        price = Decimal(
            request.form.get("unit_price", "0")
        )

    except (ValueError, InvalidOperation):
        raise ValueError(
            "Quantity, reorder level, and price must be valid numbers."
        )

    if not code or not name:
        raise ValueError(
            "Product code and product name are required."
        )

    if quantity < 0 or reorder_level < 0 or price < 0:
        raise ValueError(
            "Quantity, reorder level, and price cannot be negative."
        )

    if not price.is_finite():
        raise ValueError("Price must be a valid finite number.")

    return (
        store_id,
        code,
        name,
        category,
        quantity,
        reorder_level,
        price,
    )


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/")
def dashboard():

    stats = query_one(
        """
        SELECT
            COUNT(*) AS total_products,
            COALESCE(SUM(quantity), 0) AS total_units,
            COALESCE(
                SUM(quantity > 0 AND quantity <= reorder_level),
                0
            ) AS low_stock,
            COALESCE(SUM(quantity = 0), 0) AS out_of_stock
        FROM products
        """
    )

    low_products = query_all(
        """
        SELECT *
        FROM products
        WHERE quantity > 0
          AND quantity <= reorder_level
        ORDER BY quantity ASC, product_name
        LIMIT 10
        """
    )

    recent = query_all(
        """
        SELECT
            sm.*,
            p.product_name,
            p.product_code,
            p.store_id
        FROM stock_movements sm
        JOIN products p ON p.id = sm.product_id
        ORDER BY sm.created_at DESC
        LIMIT 8
        """
    )

    unread_row = query_one(
        """
        SELECT COUNT(*) AS n
        FROM notifications
        WHERE is_read = FALSE
        """
    )

    unread = unread_row["n"] if unread_row else 0

    return render_template(
        "dashboard.html",
        stats=stats,
        low_products=low_products,
        recent=recent,
        unread=unread,
    )


# --------------------------------------------------
# VIEW AND SEARCH PRODUCTS
# --------------------------------------------------

@app.route("/products")
def products():

    search = (request.args.get("q") or "").strip()

    if search:
        like = f"%{search}%"

        rows = query_all(
            """
            SELECT *
            FROM products
            WHERE product_name LIKE %s
               OR product_code LIKE %s
               OR category LIKE %s
               OR store_id LIKE %s
            ORDER BY product_name
            """,
            (like, like, like, like)
        )

    else:
        rows = query_all(
            """
            SELECT *
            FROM products
            ORDER BY product_name, store_id
            """
        )

    return render_template(
        "products.html",
        products=rows,
        search=search,
    )


# --------------------------------------------------
# ADD PRODUCT
# --------------------------------------------------

@app.route("/products/add", methods=["GET", "POST"])
def add_product():

    if request.method == "POST":

        try:
            data = product_from_form()

            new_id = execute(
                """
                INSERT INTO products
                    (
                        store_id,
                        product_code,
                        product_name,
                        category,
                        quantity,
                        reorder_level,
                        unit_price
                    )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                data
            )

            execute(
                """
                INSERT INTO stock_movements
                    (
                        product_id,
                        movement_type,
                        quantity_change,
                        note
                    )
                VALUES (%s, 'ADJUSTMENT', %s, 'Initial stock')
                """,
                (new_id, data[4])
            )

            check_alert(
                new_id,
                data[2],
                data[4],
                data[5]
            )

            flash("Product added successfully.", "success")
            return redirect(url_for("products"))

        except ValueError as e:
            flash(str(e), "danger")

        except Exception:
            app.logger.exception("Failed to add product")
            flash(
                "Could not add product. Check your database "
                "and ensure the store/product code is not duplicated.",
                "danger"
            )

    return render_template(
        "product_form.html",
        product=None,
        page_title="Add product"
    )


# --------------------------------------------------
# EDIT PRODUCT
# --------------------------------------------------

@app.route(
    "/products/<int:product_id>/edit",
    methods=["GET", "POST"]
)
def edit_product(product_id):

    product = query_one(
        "SELECT * FROM products WHERE id=%s",
        (product_id,)
    )

    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("products"))

    if request.method == "POST":

        try:
            data = product_from_form()

            execute(
                """
                UPDATE products
                SET store_id=%s,
                    product_code=%s,
                    product_name=%s,
                    category=%s,
                    quantity=%s,
                    reorder_level=%s,
                    unit_price=%s
                WHERE id=%s
                """,
                (*data, product_id)
            )

            delta = data[4] - product["quantity"]

            if delta:
                execute(
                    """
                    INSERT INTO stock_movements
                        (
                            product_id,
                            movement_type,
                            quantity_change,
                            note
                        )
                    VALUES (
                        %s,
                        'ADJUSTMENT',
                        %s,
                        'Edited through product form'
                    )
                    """,
                    (product_id, delta)
                )

            check_alert(
                product_id,
                data[2],
                data[4],
                data[5]
            )

            flash("Product updated successfully.", "success")
            return redirect(url_for("products"))

        except ValueError as e:
            flash(str(e), "danger")

        except Exception:
            app.logger.exception("Failed to update product")
            flash(
                "Could not update product. Check your database "
                "and ensure the store/product code is not duplicated.",
                "danger"
            )

    return render_template(
        "product_form.html",
        product=product,
        page_title="Edit product"
    )


# --------------------------------------------------
# DELETE PRODUCT
# --------------------------------------------------

@app.route(
    "/products/<int:product_id>/delete",
    methods=["POST"]
)
def delete_product(product_id):

    product = query_one(
        "SELECT id FROM products WHERE id=%s",
        (product_id,)
    )

    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("products"))

    try:
        execute(
            "DELETE FROM products WHERE id=%s",
            (product_id,)
        )

        flash("Product deleted successfully.", "success")

    except Exception:
        app.logger.exception("Failed to delete product")
        flash(
            "Could not delete product. Check related database records.",
            "danger"
        )

    return redirect(url_for("products"))


# --------------------------------------------------
# RESTOCK PRODUCT
# --------------------------------------------------

@app.route(
    "/products/<int:product_id>/restock",
    methods=["POST"]
)
def restock(product_id):

    product = query_one(
        "SELECT * FROM products WHERE id=%s",
        (product_id,)
    )

    if not product:
        flash("Product not found.", "danger")
        return redirect(url_for("products"))

    try:
        amount = int(request.form.get("amount", "0"))

        if amount <= 0:
            raise ValueError

    except ValueError:
        flash(
            "Enter a restock quantity greater than zero.",
            "danger"
        )
        return redirect(
            request.referrer or url_for("products")
        )

    try:
        execute(
            """
            UPDATE products
            SET quantity = quantity + %s
            WHERE id = %s
            """,
            (amount, product_id)
        )

        execute(
            """
            INSERT INTO stock_movements
                (
                    product_id,
                    movement_type,
                    quantity_change,
                    note
                )
            VALUES (%s, 'RESTOCK', %s, 'Manual restock')
            """,
            (product_id, amount)
        )

        updated = query_one(
            "SELECT * FROM products WHERE id=%s",
            (product_id,)
        )

        check_alert(
            product_id,
            updated["product_name"],
            updated["quantity"],
            updated["reorder_level"]
        )

        flash(
            f"Restocked {amount} units. "
            f"New quantity: {updated['quantity']}.",
            "success"
        )

    except Exception:
        app.logger.exception("Failed to restock product")
        flash("Restocking failed. Please try again.", "danger")

    return redirect(
        request.referrer or url_for("products")
    )


# --------------------------------------------------
# CSV COLUMN NORMALIZATION
# --------------------------------------------------

def normalize_columns(df):
    """Convert dataset headers to lowercase underscore names."""

    mapping = {}

    for col in df.columns:
        key = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(col).strip().lower()
        ).strip("_")

        mapping[col] = key

    return df.rename(columns=mapping)


# --------------------------------------------------
# IMPORT PRODUCTS FROM CSV
# --------------------------------------------------

@app.route("/import", methods=["GET", "POST"])
def import_csv():

    if request.method == "POST":

        file = request.files.get("file")

        if not file or not file.filename:
            flash("Choose a CSV file first.", "danger")
            return redirect(url_for("import_csv"))

        if not file.filename.lower().endswith(".csv"):
            flash("Only CSV files are supported.", "danger")
            return redirect(url_for("import_csv"))

        try:
            df = pd.read_csv(file)

            df = normalize_columns(df)

            # Required dataset columns
            required = {"product_id", "inventory_level"}

            if not required.issubset(df.columns):
                flash(
                    "CSV must include Product ID and Inventory Level "
                    "columns. Check your CSV headers.",
                    "danger"
                )
                return redirect(url_for("import_csv"))

            # Default values for optional columns
            if "store_id" not in df.columns:
                df["store_id"] = "MAIN"

            if "category" not in df.columns:
                df["category"] = "Uncategorized"

            if "price" not in df.columns:
                df["price"] = 0

            # Convert inventory and price to numbers
            df["inventory_level"] = pd.to_numeric(
                df["inventory_level"],
                errors="coerce"
            )

            df["price"] = pd.to_numeric(
                df["price"],
                errors="coerce"
            ).fillna(0)

            # Remove rows with missing required data
            df = df.dropna(
                subset=["product_id", "inventory_level"]
            )

            df = df[df["inventory_level"] >= 0]

            df = df[df["price"] >= 0]

            # Ignore blank identifiers
            df = df[
                df["product_id"].astype(str).str.strip().ne("")
            ]

            df = df[
                df["store_id"].notna()
            ]

            # If dates exist, use the latest record per store/product
            if "date" in df.columns:
                df["date"] = pd.to_datetime(
                    df["date"],
                    errors="coerce",
                    dayfirst=True
                )

                df = df.sort_values(
                    "date",
                    na_position="first"
                )

            df = df.drop_duplicates(
                subset=["store_id", "product_id"],
                keep="last"
            )

            imported = 0

            for _, row in df.iterrows():

                store = str(row["store_id"]).strip()[:30]
                code = str(row["product_id"]).strip()[:60]

                if not store or not code:
                    continue

                # Dataset provides IDs rather than product names
                name = code

                category_value = row.get(
                    "category",
                    "Uncategorized"
                )

                category = (
                    "Uncategorized"
                    if pd.isna(category_value)
                    else str(category_value).strip()[:100]
                )

                qty = int(row["inventory_level"])

                price = Decimal(
                    str(round(float(row["price"]), 2))
                )

                existing = query_one(
                    """
                    SELECT id
                    FROM products
                    WHERE store_id=%s AND product_code=%s
                    """,
                    (store, code)
                )

                if existing:
                    pid = existing["id"]

                    execute(
                        """
                        UPDATE products
                        SET product_name=%s,
                            category=%s,
                            quantity=%s,
                            unit_price=%s
                        WHERE id=%s
                        """,
                        (name, category, qty, price, pid)
                    )

                else:
                    pid = execute(
                        """
                        INSERT INTO products
                            (
                                store_id,
                                product_code,
                                product_name,
                                category,
                                quantity,
                                reorder_level,
                                unit_price
                            )
                        VALUES (%s, %s, %s, %s, %s, 10, %s)
                        """,
                        (
                            store,
                            code,
                            name,
                            category,
                            qty,
                            price
                        )
                    )

                execute(
                    """
                    INSERT INTO stock_movements
                        (
                            product_id,
                            movement_type,
                            quantity_change,
                            note
                        )
                    VALUES (%s, 'IMPORT', %s, 'Imported from CSV')
                    """,
                    (pid, qty)
                )

                item = query_one(
                    "SELECT * FROM products WHERE id=%s",
                    (pid,)
                )

                check_alert(
                    pid,
                    item["product_name"],
                    item["quantity"],
                    item["reorder_level"]
                )

                imported += 1

            flash(
                f"CSV import complete: {imported} "
                "store/product records processed.",
                "success"
            )

            return redirect(url_for("products"))

        except Exception:
            mysql.connection.rollback()
            app.logger.exception("CSV import failed")

            flash(
                "Import failed. Verify the CSV columns, "
                "data values, database tables, and connection. "
                "Check the terminal for details.",
                "danger"
            )

            return redirect(url_for("import_csv"))

    return render_template("import.html")


# --------------------------------------------------
# NOTIFICATIONS
# --------------------------------------------------

@app.route("/notifications")
def notifications():

    rows = query_all(
        """
        SELECT
            n.*,
            p.product_name,
            p.product_code,
            p.store_id
        FROM notifications n
        JOIN products p ON p.id = n.product_id
        ORDER BY n.created_at DESC
        """
    )

    return render_template(
        "notifications.html",
        notifications=rows
    )


@app.route("/notifications/read", methods=["POST"])
def read_notifications():

    execute(
        "UPDATE notifications SET is_read=TRUE"
    )

    flash(
        "Notifications marked as read.",
        "success"
    )

    return redirect(url_for("notifications"))


# --------------------------------------------------
# INVENTORY CHATBOT
# --------------------------------------------------

@app.route("/chat", methods=["GET", "POST"])
def chat():

    answer = None
    question = ""

    if request.method == "POST":

        question = (
            request.form.get("message") or ""
        ).strip()

        q = question.lower()

        if any(
            word in q
            for word in [
                "low stock",
                "low-stock",
                "running low",
                "nearly empty"
            ]
        ):

            rows = query_all(
                """
                SELECT
                    product_name,
                    store_id,
                    quantity,
                    reorder_level
                FROM products
                WHERE quantity > 0
                  AND quantity <= reorder_level
                ORDER BY quantity
                """
            )

            if rows:
                details = ", ".join(
                    f"{r['product_name']} "
                    f"(store {r['store_id']}): "
                    f"{r['quantity']} left; "
                    f"reorder at {r['reorder_level']}"
                    for r in rows
                )

                answer = "Low-stock products: " + details

            else:
                answer = (
                    "No products are currently low in stock."
                )

        elif any(
            word in q
            for word in [
                "out of stock",
                "empty",
                "zero stock"
            ]
        ):

            rows = query_all(
                """
                SELECT product_name, store_id
                FROM products
                WHERE quantity = 0
                ORDER BY product_name
                """
            )

            if rows:
                details = ", ".join(
                    f"{r['product_name']} "
                    f"(store {r['store_id']})"
                    for r in rows
                )

                answer = "Out-of-stock products: " + details

            else:
                answer = (
                    "No products are out of stock."
                )

        elif any(
            word in q
            for word in [
                "restock",
                "reorder",
                "order more"
            ]
        ):

            rows = query_all(
                """
                SELECT
                    product_name,
                    store_id,
                    quantity,
                    reorder_level
                FROM products
                WHERE quantity <= reorder_level
                ORDER BY quantity
                """
            )

            if rows:
                details = ", ".join(
                    f"{r['product_name']} "
                    f"(store {r['store_id']}): "
                    f"{r['quantity']} available, "
                    f"reorder level {r['reorder_level']}"
                    for r in rows
                )

                answer = (
                    "Products to review for restocking: "
                    + details
                )

            else:
                answer = (
                    "No restocking is currently indicated."
                )

        elif any(
            word in q
            for word in [
                "how many",
                "total",
                "count",
                "number of products"
            ]
        ):

            stats = query_one(
                """
                SELECT
                    COUNT(*) AS products,
                    COALESCE(SUM(quantity), 0) AS units
                FROM products
                """
            )

            answer = (
                f"There are {stats['products']} "
                f"store/product records and "
                f"{stats['units']} units in stock."
            )

        elif q in ["hello", "hi", "hey"]:

            answer = (
                "Hello! Ask me about low stock, "
                "out-of-stock products, total inventory, "
                "or products to restock."
            )

        else:

            answer = (
                "I can help with low stock, out-of-stock "
                "items, restock reminders, and total inventory. "
                "Try: 'Show low stock'."
            )

    return render_template(
        "chat.html",
        answer=answer,
        question=question
    )


# --------------------------------------------------
# APPLICATION ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
