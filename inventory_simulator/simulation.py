"""Demand generation and the inventory simulation engine.

Everything is stored in NumPy arrays shaped (days, products): row d is day d+1 and
column i is product i of the Catalogue. The engine loops over days, because today's
stock depends on yesterday's, but each day updates all products at once.
"""

from collections import namedtuple

import numpy as np

from .policies import ReplenishmentPolicy

RNG_METHOD = "numpy.random.default_rng (PCG64), poisson"


class Catalogue:
    """The products being simulated, always in the same order.

    Position i in every array refers to product_ids[i].
    """

    def __init__(
        self,
        product_ids: list[str],
        price_cents: list[int],
        cost_cents: list[int],
        initial_stock: list[int],
        mean_demand: list[float],
    ) -> None:
        self.product_ids = list(product_ids)
        self.price_cents = np.array(price_cents, dtype=np.int64)
        self.cost_cents = np.array(cost_cents, dtype=np.int64)
        self.initial_stock = np.array(initial_stock, dtype=np.int64)
        self.mean_demand = np.array(mean_demand, dtype=float)

        n = len(self.product_ids)
        if len(set(self.product_ids)) != n:
            raise ValueError("product ids must be unique")
        for array in (self.price_cents, self.cost_cents, self.initial_stock, self.mean_demand):
            if array.shape != (n,):
                raise ValueError("every product needs a price, cost, initial stock and mean")
        if (self.initial_stock < 0).any() or (self.mean_demand < 0).any():
            raise ValueError("initial stock and mean demand must be non-negative")

    def __len__(self) -> int:
        return len(self.product_ids)

    def unit_margins(self) -> np.ndarray:
        """Selling price minus purchase cost for each product, in cents."""
        return self.price_cents - self.cost_cents


# Storage extension settings for one run: total capacity and allocation rule.
StorageLimit = namedtuple("StorageLimit", ["capacity", "rule"])


def generate_demand(mean_demand: np.ndarray, days: int, seed: int) -> np.ndarray:
    """Draw a (days, products) array of Poisson demand. Same seed, same array.

    A Poisson draw is a whole number >= 0. Day to day it goes up and down around the
    product's mean, and over many days it averages out to that mean, which is how
    we picture "about 8 notebooks a day, sometimes 5, sometimes 12".
    """
    rng = np.random.default_rng(seed)
    # lam has shape (products,) and is broadcast over the rows,
    # so column i is drawn with product i's mean.
    return rng.poisson(lam=mean_demand, size=(days, len(mean_demand)))


def allocation_priority(catalogue: Catalogue, rule: str) -> list[int]:
    """Product positions in the order they get storage space under `rule`."""
    positions = range(len(catalogue))
    margins = catalogue.unit_margins()

    def by_product_id(i: int) -> str:
        return catalogue.product_ids[i]

    def by_margin(i: int) -> tuple:
        # Highest margin first (hence the minus); equal margins fall back to product id.
        return (-margins[i], catalogue.product_ids[i])

    if rule == "product_id_ascending":
        return sorted(positions, key=by_product_id)
    if rule == "unit_margin_descending":
        return sorted(positions, key=by_margin)
    raise ValueError(f"unknown allocation rule {rule!r}")


def allocate_capacity(requested: np.ndarray, free_capacity: int, priority: list[int]) -> np.ndarray:
    """Cut orders down so they fit in the free space.

    Products are served in priority order. Each gets its full request if it fits,
    otherwise whatever space is left. Nobody gets more than they asked for.
    """
    allocated = np.zeros_like(requested)
    remaining = free_capacity
    for i in priority:
        allocated[i] = min(int(requested[i]), remaining)
        remaining -= allocated[i]
    return allocated


class SimulationResult:
    """What happened in one simulation run, as (days, products) arrays.

    Quantities come from the engine; the money arrays are worked out here, in cents.
    """

    def __init__(
        self,
        catalogue: Catalogue,
        demand: np.ndarray,
        stock_start: np.ndarray,
        units_sold: np.ndarray,
        stock_end: np.ndarray,
        orders: np.ndarray,
        holding_cost_cents: int,
        order_cost_cents: int,
    ) -> None:
        self.demand = demand
        self.stock_start = stock_start
        self.units_sold = units_sold
        self.stock_end = stock_end
        self.orders = orders
        self.lost_sales = demand - units_sold

        # (days, products) * (products,) broadcasts the price vector over every day.
        self.revenue_cents = units_sold * catalogue.price_cents
        self.cogs_cents = units_sold * catalogue.cost_cents
        self.holding_cost_cents = stock_end * holding_cost_cents
        # One fixed fee per product order; no fee on days with nothing ordered.
        self.ordering_cost_cents = (orders > 0).astype(np.int64) * order_cost_cents
        self.operating_result_cents = (
            self.revenue_cents - self.cogs_cents
            - self.holding_cost_cents - self.ordering_cost_cents
        )

    def total_operating_result_cents(self) -> int:
        return int(self.operating_result_cents.sum())


def simulate(
    catalogue: Catalogue,
    demand: np.ndarray,
    policy: ReplenishmentPolicy,
    holding_cost_cents: int,
    order_cost_cents: int,
    storage: StorageLimit | None = None,
) -> SimulationResult:
    """Run one replenishment policy against a fixed demand array.

    Each day, in this order:
      1. receive the orders placed at the end of the previous day
      2. sell min(demand, stock)
      3. demand that could not be met is lost for good
      4. holding cost is charged on end-of-day stock
      5. the policy places orders, which arrive the next morning
    Orders placed on the last day stay in `orders` and are reported as outstanding.
    """
    demand = np.asarray(demand, dtype=np.int64)
    days, n_products = demand.shape
    if n_products != len(catalogue):
        raise ValueError(f"demand has {n_products} columns but there are {len(catalogue)} products")
    if (demand < 0).any():
        raise ValueError("demand must be non-negative")

    priority = None
    if storage is not None:
        if catalogue.initial_stock.sum() > storage.capacity:
            raise ValueError("initial stock exceeds the storage capacity")
        priority = allocation_priority(catalogue, storage.rule)

    stock_start = np.zeros((days, n_products), dtype=np.int64)
    units_sold = np.zeros_like(stock_start)
    stock_end = np.zeros_like(stock_start)
    orders = np.zeros_like(stock_start)

    stock = catalogue.initial_stock.copy()
    arriving = np.zeros(n_products, dtype=np.int64)  # nothing is on order on day 1

    for day in range(days):
        stock = stock + arriving                          # 1
        stock_start[day] = stock
        units_sold[day] = np.minimum(demand[day], stock)  # 2 (3: the rest is lost)
        stock = stock - units_sold[day]
        stock_end[day] = stock                            # 4: costed in SimulationResult

        requested = policy.order_quantities(stock)        # 5
        if storage is not None:
            # Everything ordered today arrives tomorrow morning, before any sales,
            # so it has to fit next to the stock we already hold.
            free_capacity = storage.capacity - int(stock.sum())
            requested = allocate_capacity(requested, free_capacity, priority)
        orders[day] = requested
        arriving = requested

    return SimulationResult(catalogue, demand, stock_start, units_sold, stock_end, orders,
                            holding_cost_cents, order_cost_cents)
