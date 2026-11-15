"""Demand generation and inventory policy simulation."""

from dataclasses import dataclass
import sqlite3
from abc import ABC, abstractmethod
import uuid

import numpy as np

from .config import Settings


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    category: str
    cost: float
    price: float
    initial_stock: int
    mean_demand: float


class ReplenishmentPolicy(ABC):
    name: str

    @abstractmethod
    def requested_order(self, stock: int) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class FixedQuantityPolicy(ReplenishmentPolicy):
    threshold: int
    quantity: int
    name: str = "fixed_quantity"

    def requested_order(self, stock: int) -> int:
        return self.quantity if stock < self.threshold else 0


@dataclass(frozen=True)
class OrderUpToPolicy(ReplenishmentPolicy):
    threshold: int
    target: int
    name: str = "order_up_to"

    def requested_order(self, stock: int) -> int:
        return self.target - stock if stock < self.threshold else 0


def load_products(connection: sqlite3.Connection) -> list[Product]:
    rows = connection.execute("""SELECT p.product_id,p.name,p.category,p.purchase_cost,p.selling_price,
      p.initial_stock,AVG(h.units_sold) AS mean_demand FROM products p
      JOIN historical_sales h USING(product_id) GROUP BY p.product_id ORDER BY p.product_id""").fetchall()
    if not rows:
        raise ValueError("No valid imported products and historical sales are available")
    return [Product(row["product_id"], row["name"], row["category"], row["purchase_cost"], row["selling_price"], row["initial_stock"], row["mean_demand"]) for row in rows]


def generate_demand(products: list[Product], days: int, seed: int) -> np.ndarray:
    generator = np.random.default_rng(seed)
    return np.stack([generator.poisson([product.mean_demand for product in products]) for _ in range(days)])


def simulate(connection: sqlite3.Connection, settings: Settings) -> tuple[list[dict], list[dict]]:
    products = load_products(connection)
    if settings.extension == "storage" and sum(product.initial_stock for product in products) > settings.capacity:
        raise ValueError("Initial stock exceeds storage capacity")
    policies: list[ReplenishmentPolicy] = [
        FixedQuantityPolicy(settings.fixed_threshold, settings.fixed_quantity),
        OrderUpToPolicy(settings.up_to_threshold, settings.up_to_target),
    ]
    rules = ["product_id_ascending", "unit_margin_descending"] if settings.extension == "storage" else ["unlimited"]
    demand = generate_demand(products, settings.days, settings.seed)
    daily_rows: list[dict] = []
    aggregate_rows: list[dict] = []
    for policy in policies:
        for rule in rules:
            run_id = f"{settings.seed}-{policy.name}-{rule}-{uuid.uuid5(uuid.NAMESPACE_URL, str(settings.config_path)).hex[:8]}"
            stock = [p.initial_stock for p in products]
            pending = [0] * len(products)
            totals = {key: 0.0 for key in ("revenue", "cogs", "gross_profit", "holding_cost", "ordering_cost", "operating_result", "units_sold", "lost_sales", "demand")}
            for day_index in range(settings.days):
                stock = [stock[i] + pending[i] for i in range(len(products))]
                pending = [0] * len(products)
                start_stock = stock.copy()
                sales = [min(int(demand[day_index, i]), stock[i]) for i in range(len(products))]
                lost = [int(demand[day_index, i]) - sales[i] for i in range(len(products))]
                end_stock = [stock[i] - sales[i] for i in range(len(products))]
                requested = [policy.requested_order(qty) for qty in end_stock]
                allocated = requested.copy()
                if settings.extension == "storage":
                    free_capacity = settings.capacity - sum(end_stock)
                    order = list(range(len(products)))
                    if rule == "unit_margin_descending":
                        order.sort(key=lambda i: (-(products[i].price - products[i].cost), products[i].product_id))
                    else:
                        order.sort(key=lambda i: products[i].product_id)
                    allocated = [0] * len(products)
                    for i in order:
                        allocated[i] = min(requested[i], max(0, free_capacity))
                        free_capacity -= allocated[i]
                for i, product in enumerate(products):
                    revenue = sales[i] * product.price
                    cogs = sales[i] * product.cost
                    holding = end_stock[i] * settings.holding_cost
                    ordering = settings.fixed_order_cost if allocated[i] > 0 else 0.0
                    totals["revenue"] += revenue
                    totals["cogs"] += cogs
                    totals["gross_profit"] += revenue - cogs
                    totals["holding_cost"] += holding
                    totals["ordering_cost"] += ordering
                    totals["units_sold"] += sales[i]
                    totals["lost_sales"] += lost[i]
                    totals["demand"] += int(demand[day_index, i])
                    daily_rows.append({"run_id": run_id, "policy": policy.name, "allocation_rule": rule,
                        "day": day_index + 1, "product_id": product.product_id, "stock_start": start_stock[i],
                        "demand": int(demand[day_index, i]), "units_sold": sales[i], "lost_sales": lost[i],
                        "order_quantity": allocated[i], "stock_end": end_stock[i], "revenue": revenue,
                        "cogs": cogs, "gross_profit": revenue-cogs, "holding_cost": holding,
                        "ordering_cost": ordering, "operating_result": revenue-cogs-holding-ordering})
                pending = allocated
                stock = end_stock
                totals["operating_result"] = totals["gross_profit"] - totals["holding_cost"] - totals["ordering_cost"]
            aggregate_rows.append({"run_id": run_id, "policy": policy.name, "allocation_rule": rule,
                **totals, "fulfilment_rate": totals["units_sold"] / totals["demand"] if totals["demand"] else "N/A",
                "final_stock": sum(stock), "outstanding_orders": sum(pending),
                "final_inventory_value": sum(stock[i] * products[i].cost for i in range(len(products)))})
    with connection:
        for result in aggregate_rows:
            connection.execute("DELETE FROM daily_simulation_results WHERE run_id = ?", (result["run_id"],))
            connection.execute("DELETE FROM simulation_runs WHERE run_id = ?", (result["run_id"],))
            connection.execute("INSERT INTO simulation_runs(run_id,config_path,seed,days,policy,allocation_rule,operating_result) VALUES(?,?,?,?,?,?,?)",
                (result["run_id"], str(settings.config_path), settings.seed, settings.days, result["policy"], result["allocation_rule"], result["operating_result"]))
            rows = [r for r in daily_rows if r["run_id"] == result["run_id"]]
            connection.executemany("INSERT INTO daily_simulation_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(r["run_id"], r["day"], r["product_id"], r["stock_start"], r["demand"], r["units_sold"], r["lost_sales"], r["order_quantity"], r["stock_end"], r["revenue"], r["cogs"], r["holding_cost"], r["ordering_cost"]) for r in rows])
    return daily_rows, aggregate_rows
