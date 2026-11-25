"""SQLite storage: the schema, imports, saving runs and all SQL summaries.

Money columns end in _cents and hold integers. Open the database with
`with closing(connect(path)) as connection:` so it is always closed, and wrap
changes in `with connection:` so they are committed together or rolled back.
"""

import sqlite3
from pathlib import Path

import numpy as np

from .simulation import SimulationResult
from .validation import ProductRecord, SaleRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_id          TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    category            TEXT NOT NULL,
    purchase_cost_cents INTEGER NOT NULL CHECK (purchase_cost_cents > 0),
    selling_price_cents INTEGER NOT NULL CHECK (selling_price_cents > 0),
    initial_stock       INTEGER NOT NULL CHECK (initial_stock >= 0)
);

CREATE TABLE IF NOT EXISTS historical_sales (
    sale_date  TEXT NOT NULL,
    product_id TEXT NOT NULL,
    units_sold INTEGER NOT NULL CHECK (units_sold >= 0),
    PRIMARY KEY (sale_date, product_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id            TEXT PRIMARY KEY,
    scenario          TEXT NOT NULL,
    policy            TEXT NOT NULL,
    policy_parameters TEXT NOT NULL,
    allocation_rule   TEXT NOT NULL,
    storage_capacity  INTEGER,
    days              INTEGER NOT NULL CHECK (days > 0),
    seed              INTEGER NOT NULL,
    rng_method        TEXT NOT NULL,
    numpy_version     TEXT NOT NULL,
    effective_config  TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_results (
    run_id              TEXT NOT NULL,
    day                 INTEGER NOT NULL CHECK (day >= 1),
    product_id          TEXT NOT NULL,
    stock_start         INTEGER NOT NULL CHECK (stock_start >= 0),
    demand              INTEGER NOT NULL CHECK (demand >= 0),
    units_sold          INTEGER NOT NULL CHECK (units_sold >= 0),
    lost_sales          INTEGER NOT NULL CHECK (lost_sales >= 0),
    stock_end           INTEGER NOT NULL CHECK (stock_end >= 0),
    order_quantity      INTEGER NOT NULL CHECK (order_quantity >= 0),
    revenue_cents       INTEGER NOT NULL,
    cogs_cents          INTEGER NOT NULL,
    holding_cost_cents  INTEGER NOT NULL,
    ordering_cost_cents INTEGER NOT NULL,
    PRIMARY KEY (run_id, day, product_id),
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    CHECK (units_sold + lost_sales = demand),
    CHECK (stock_end = stock_start - units_sold)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open the database, creating the folder and tables if they do not exist yet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection


# --- importing ----------------------------------------------------------------


def find_conflicts(connection: sqlite3.Connection, sales: list[SaleRecord]) -> list[str]:
    """Sales rows that already exist in the database with a different quantity."""
    stored = {
        (row["sale_date"], row["product_id"]): row["units_sold"]
        for row in connection.execute(
            "SELECT sale_date, product_id, units_sold FROM historical_sales"
        )
    }
    conflicts = []
    for sale in sales:
        old = stored.get((sale.sale_date, sale.product_id))
        if old is not None and old != sale.units_sold:
            conflicts.append(
                f"historical_sales: {sale.product_id} on {sale.sale_date} is stored with "
                f"{old} units but the file says {sale.units_sold}"
            )
    return conflicts


def import_records(
    connection: sqlite3.Connection, products: list[ProductRecord], sales: list[SaleRecord]
) -> int:
    """Store validated products and sales in one transaction. Returns new sales rows.

    Products already in the database are updated to the values in the file (the
    catalogue file is the current price list). Sales rows that are already stored
    are skipped, so importing the same file twice adds nothing.
    """
    with connection:
        # An upsert, not INSERT OR REPLACE: REPLACE deletes the old row first,
        # which the foreign key from historical_sales would not allow.
        connection.executemany(
            """
            INSERT INTO products (product_id, name, category, purchase_cost_cents,
                                  selling_price_cents, initial_stock)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (product_id) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                purchase_cost_cents = excluded.purchase_cost_cents,
                selling_price_cents = excluded.selling_price_cents,
                initial_stock = excluded.initial_stock
            """,
            products,
        )
        cursor = connection.executemany(
            "INSERT OR IGNORE INTO historical_sales (sale_date, product_id, units_sold) "
            "VALUES (?, ?, ?)",
            sales,
        )
    return cursor.rowcount


def count_rows(connection: sqlite3.Connection, table: str) -> int:
    if table not in {"products", "historical_sales", "simulation_runs", "daily_results"}:
        raise ValueError(f"unknown table {table!r}")
    # Table names cannot be "?" parameters, hence the whitelist above.
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- historical summaries -----------------------------------------------------


def history_window(connection: sqlite3.Connection) -> sqlite3.Row:
    return connection.execute(
        """
        SELECT MIN(sale_date) AS first_day,
               MAX(sale_date) AS last_day,
               COUNT(DISTINCT sale_date) AS days,
               COUNT(DISTINCT product_id) AS products
        FROM historical_sales
        """
    ).fetchone()


def sales_by_product(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Units sold, revenue, cost of goods sold and gross profit per product."""
    return connection.execute(
        """
        SELECT p.product_id, p.name, p.category,
               COUNT(*) AS days,
               SUM(h.units_sold) AS units_sold,
               ROUND(AVG(h.units_sold), 8) AS mean_daily_units,
               SUM(h.units_sold * p.selling_price_cents) AS revenue_cents,
               SUM(h.units_sold * p.purchase_cost_cents) AS cogs_cents,
               SUM(h.units_sold * (p.selling_price_cents - p.purchase_cost_cents))
                   AS gross_profit_cents
        FROM products AS p
        JOIN historical_sales AS h ON h.product_id = p.product_id
        GROUP BY p.product_id, p.name, p.category
        ORDER BY p.product_id
        """
    ).fetchall()


def sales_by_category(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """The same totals per category, using a JOIN between sales and products."""
    return connection.execute(
        """
        SELECT p.category,
               COUNT(DISTINCT p.product_id) AS products,
               SUM(h.units_sold) AS units_sold,
               SUM(h.units_sold * p.selling_price_cents) AS revenue_cents,
               SUM(h.units_sold * p.purchase_cost_cents) AS cogs_cents,
               SUM(h.units_sold * (p.selling_price_cents - p.purchase_cost_cents))
                   AS gross_profit_cents
        FROM historical_sales AS h
        JOIN products AS p ON p.product_id = h.product_id
        GROUP BY p.category
        ORDER BY revenue_cents DESC
        """
    ).fetchall()


def best_sellers(
    connection: sqlite3.Connection, first_day: str, last_day: str, limit: int = 5
) -> list[sqlite3.Row]:
    """Products ranked by units sold between two dates (both included)."""
    return connection.execute(
        """
        SELECT p.product_id, p.name,
               SUM(h.units_sold) AS units_sold,
               SUM(h.units_sold * p.selling_price_cents) AS revenue_cents
        FROM historical_sales AS h
        JOIN products AS p ON p.product_id = h.product_id
        WHERE h.sale_date BETWEEN ? AND ?
        GROUP BY p.product_id, p.name
        ORDER BY units_sold DESC, p.product_id
        LIMIT ?
        """,
        (first_day, last_day, limit),
    ).fetchall()


# --- simulation runs ----------------------------------------------------------


def load_catalogue_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """Products with their mean daily demand over the stored history (unrounded)."""
    return connection.execute(
        """
        SELECT p.product_id, p.selling_price_cents, p.purchase_cost_cents,
               p.initial_stock, AVG(h.units_sold) AS mean_demand
        FROM products AS p
        JOIN historical_sales AS h ON h.product_id = p.product_id
        GROUP BY p.product_id
        ORDER BY p.product_id
        """
    ).fetchall()


def save_run(
    connection: sqlite3.Connection,
    run: dict[str, object],
    product_ids: list[str],
    result: SimulationResult,
) -> None:
    """Store one run and its daily rows. A run with the same run_id is replaced.

    Call this inside `with connection:` so all runs of a comparison are saved together.
    """
    # ON DELETE CASCADE removes the old daily rows together with the old run.
    connection.execute("DELETE FROM simulation_runs WHERE run_id = ?", (run["run_id"],))
    connection.execute(
        """
        INSERT INTO simulation_runs (run_id, scenario, policy, policy_parameters,
            allocation_rule, storage_capacity, days, seed, rng_method, numpy_version,
            effective_config)
        VALUES (:run_id, :scenario, :policy, :policy_parameters, :allocation_rule,
            :storage_capacity, :days, :seed, :rng_method, :numpy_version, :effective_config)
        """,
        run,
    )
    # Stack the ten (days, products) arrays into one (days, products, 10) array, in
    # the column order of the table. .tolist() gives plain Python ints for sqlite3.
    values = np.stack(
        [
            result.stock_start, result.demand, result.units_sold, result.lost_sales,
            result.stock_end, result.orders, result.revenue_cents, result.cogs_cents,
            result.holding_cost_cents, result.ordering_cost_cents,
        ],
        axis=2,
    ).tolist()
    rows = []
    for day, day_values in enumerate(values, start=1):
        for product_id, product_values in zip(product_ids, day_values):
            rows.append((run["run_id"], day, product_id, *product_values))
    connection.executemany(
        "INSERT INTO daily_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


# Shared by the shop-level and product-level comparisons. "Final" values come from
# the last simulated day (d.day = r.days): stock on hand and orders still on the way.
_RESULT_COLUMNS = """
    SUM(d.demand) AS demand,
    SUM(d.units_sold) AS units_sold,
    SUM(d.lost_sales) AS lost_sales,
    CASE WHEN SUM(d.demand) = 0 THEN NULL
         ELSE ROUND(1.0 * SUM(d.units_sold) / SUM(d.demand), 4) END AS fulfilment_rate,
    SUM(d.revenue_cents) AS revenue_cents,
    SUM(d.cogs_cents) AS cogs_cents,
    SUM(d.revenue_cents - d.cogs_cents) AS gross_profit_cents,
    SUM(d.holding_cost_cents) AS holding_cost_cents,
    SUM(d.ordering_cost_cents) AS ordering_cost_cents,
    SUM(d.revenue_cents - d.cogs_cents - d.holding_cost_cents - d.ordering_cost_cents)
        AS operating_result_cents,
    SUM(CASE WHEN d.day = r.days THEN d.stock_end ELSE 0 END) AS final_stock,
    SUM(CASE WHEN d.day = r.days THEN d.stock_end * p.purchase_cost_cents ELSE 0 END)
        AS final_inventory_value_cents,
    SUM(CASE WHEN d.day = r.days THEN d.order_quantity ELSE 0 END) AS outstanding_orders
"""


def shop_results(connection: sqlite3.Connection, scenario: str) -> list[sqlite3.Row]:
    """One row per run of a scenario, with totals over all products and days."""
    return connection.execute(
        f"""
        SELECT r.run_id, r.policy, r.policy_parameters, r.allocation_rule,
               {_RESULT_COLUMNS}
        FROM simulation_runs AS r
        JOIN daily_results AS d ON d.run_id = r.run_id
        JOIN products AS p ON p.product_id = d.product_id
        WHERE r.scenario = ?
        GROUP BY r.run_id
        ORDER BY r.policy, r.allocation_rule
        """,
        (scenario,),
    ).fetchall()


def product_results(connection: sqlite3.Connection, scenario: str) -> list[sqlite3.Row]:
    """One row per run and product."""
    return connection.execute(
        f"""
        SELECT r.run_id, r.policy, r.allocation_rule, d.product_id,
               {_RESULT_COLUMNS}
        FROM simulation_runs AS r
        JOIN daily_results AS d ON d.run_id = r.run_id
        JOIN products AS p ON p.product_id = d.product_id
        WHERE r.scenario = ?
        GROUP BY r.run_id, d.product_id
        ORDER BY r.policy, r.allocation_rule, d.product_id
        """,
        (scenario,),
    ).fetchall()


def daily_results(connection: sqlite3.Connection, scenario: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT r.run_id, r.policy, r.allocation_rule, r.seed, d.day, d.product_id,
               d.stock_start, d.demand, d.units_sold, d.lost_sales, d.stock_end,
               d.order_quantity, d.revenue_cents, d.cogs_cents,
               d.revenue_cents - d.cogs_cents AS gross_profit_cents,
               d.holding_cost_cents, d.ordering_cost_cents,
               d.revenue_cents - d.cogs_cents - d.holding_cost_cents - d.ordering_cost_cents
                   AS operating_result_cents
        FROM daily_results AS d
        JOIN simulation_runs AS r ON r.run_id = d.run_id
        WHERE r.scenario = ?
        ORDER BY r.policy, r.allocation_rule, d.day, d.product_id
        """,
        (scenario,),
    ).fetchall()


def saved_runs(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    """A summary of every run saved in the database, from any configuration."""
    return connection.execute(
        """
        SELECT r.run_id, r.scenario, r.policy, r.allocation_rule, r.seed, r.days,
               r.created_at,
               SUM(d.units_sold) AS units_sold,
               SUM(d.lost_sales) AS lost_sales,
               SUM(d.revenue_cents - d.cogs_cents - d.holding_cost_cents
                   - d.ordering_cost_cents) AS operating_result_cents
        FROM simulation_runs AS r
        JOIN daily_results AS d ON d.run_id = r.run_id
        GROUP BY r.run_id
        ORDER BY r.scenario, r.policy, r.allocation_rule
        """
    ).fetchall()
