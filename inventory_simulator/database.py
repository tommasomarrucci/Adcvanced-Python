"""SQLite schema, imports, and required historical queries."""

import csv
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS products (
 product_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
 purchase_cost REAL NOT NULL CHECK(purchase_cost > 0),
 selling_price REAL NOT NULL CHECK(selling_price > 0),
 initial_stock INTEGER NOT NULL CHECK(initial_stock >= 0));
CREATE TABLE IF NOT EXISTS historical_sales (
 date TEXT NOT NULL, product_id TEXT NOT NULL REFERENCES products(product_id),
 units_sold INTEGER NOT NULL CHECK(units_sold >= 0),
 PRIMARY KEY(date, product_id));
CREATE TABLE IF NOT EXISTS simulation_runs (
 run_id TEXT PRIMARY KEY, config_path TEXT NOT NULL, seed INTEGER NOT NULL,
 days INTEGER NOT NULL, policy TEXT NOT NULL, allocation_rule TEXT NOT NULL,
 operating_result REAL NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS daily_simulation_results (
 run_id TEXT NOT NULL REFERENCES simulation_runs(run_id), day INTEGER NOT NULL,
 product_id TEXT NOT NULL REFERENCES products(product_id), stock_start INTEGER NOT NULL,
 demand INTEGER NOT NULL, units_sold INTEGER NOT NULL, lost_sales INTEGER NOT NULL,
 order_quantity INTEGER NOT NULL, stock_end INTEGER NOT NULL, revenue REAL NOT NULL,
 cogs REAL NOT NULL, holding_cost REAL NOT NULL, ordering_cost REAL NOT NULL,
 PRIMARY KEY(run_id, day, product_id));
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path}: required columns are {sorted(required)}")
        return list(reader)


def import_data(connection: sqlite3.Connection, products_path: Path, sales_path: Path, capacity: int | None = None) -> list[str]:
    errors: list[str] = []
    product_rows = _read_csv(products_path, {"product_id", "name", "category", "purchase_cost", "selling_price", "initial_stock"})
    sales_rows = _read_csv(sales_path, {"date", "product_id", "units_sold"})
    products: list[tuple[Any, ...]] = []
    ids: set[str] = set()
    for line, row in enumerate(product_rows, 2):
        try:
            pid = row["product_id"].strip()
            if not pid or pid in ids:
                raise ValueError("blank or duplicate product_id")
            cost, price = float(row["purchase_cost"]), float(row["selling_price"])
            stock = int(row["initial_stock"])
            if cost <= 0 or price <= 0 or stock < 0 or str(stock) != row["initial_stock"].strip():
                raise ValueError("cost/price must be positive and stock a non-negative integer")
            ids.add(pid)
            products.append((pid, row["name"].strip(), row["category"].strip(), cost, price, stock))
        except (ValueError, TypeError) as exc:
            errors.append(f"products.csv row {line}: {exc}")
    if capacity is not None and sum(row[5] for row in products) > capacity:
        errors.append(f"Initial stock {sum(row[5] for row in products)} exceeds capacity {capacity}")
    parsed_sales: list[tuple[str, str, int]] = []
    pairs: set[tuple[str, str]] = set()
    import datetime
    for line, row in enumerate(sales_rows, 2):
        try:
            day, pid = row["date"].strip(), row["product_id"].strip()
            datetime.date.fromisoformat(day)
            qty = int(row["units_sold"])
            if qty < 0 or str(qty) != row["units_sold"].strip():
                raise ValueError("units_sold must be a non-negative integer")
            if pid not in ids:
                raise ValueError(f"unknown product {pid}")
            if (day, pid) in pairs:
                raise ValueError(f"duplicate product-date pair {day}/{pid}")
            pairs.add((day, pid))
            parsed_sales.append((day, pid, qty))
        except (ValueError, TypeError) as exc:
            errors.append(f"historical_sales.csv row {line}: {exc}")
    if not errors and parsed_sales:
        dates = sorted({row[0] for row in parsed_sales})
        expected = {(day, pid) for day in dates for pid in ids}
        missing = expected - pairs
        if len(dates) < 30:
            errors.append(f"History has {len(dates)} days; at least 30 are required")
        if missing:
            errors.append(f"Incomplete history: {len(missing)} product-date pair(s) missing")
        if dates and any((datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days != 1 for a, b in zip(dates, dates[1:])):
            errors.append("Historical dates are not consecutive")
    if errors:
        return errors
    try:
        with connection:
            connection.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(product_id) DO UPDATE SET name=excluded.name, category=excluded.category, purchase_cost=excluded.purchase_cost, selling_price=excluded.selling_price, initial_stock=excluded.initial_stock", products)
            connection.executemany("INSERT OR IGNORE INTO historical_sales VALUES (?, ?, ?)", parsed_sales)
    except sqlite3.IntegrityError as exc:
        return [f"Database import failed: {exc}"]
    return []


def historical_summary(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("""SELECT p.product_id, COUNT(h.date) AS days,
      COALESCE(SUM(h.units_sold),0) AS units_sold,
      ROUND(AVG(h.units_sold),8) AS mean_daily_units,
      ROUND(SUM(h.units_sold*p.selling_price),2) AS revenue,
      ROUND(SUM(h.units_sold*p.purchase_cost),2) AS cost_of_goods_sold,
      ROUND(SUM(h.units_sold*(p.selling_price-p.purchase_cost)),2) AS gross_profit
      FROM products p JOIN historical_sales h USING(product_id)
      GROUP BY p.product_id ORDER BY p.product_id""").fetchall()


def category_revenue(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT p.category, ROUND(SUM(h.units_sold*p.selling_price),2) AS revenue FROM historical_sales h JOIN products p USING(product_id) GROUP BY p.category ORDER BY p.category").fetchall()


def best_sellers(connection: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return connection.execute("SELECT p.product_id, p.name, SUM(h.units_sold) AS units_sold FROM historical_sales h JOIN products p USING(product_id) WHERE h.date BETWEEN ? AND ? GROUP BY p.product_id ORDER BY units_sold DESC, p.product_id", (start, end)).fetchall()


def saved_runs(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT run_id, policy, allocation_rule, days, ROUND(operating_result,2) AS operating_result FROM simulation_runs ORDER BY created_at, run_id").fetchall()
