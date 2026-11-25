"""Shared helpers for the tests: sample file paths and a temporary config writer."""

import csv
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT / "inventory_student_sample_files"
PRODUCTS = SAMPLES / "data" / "products.csv"
SALES = SAMPLES / "data" / "historical_sales.csv"
VALIDATION = SAMPLES / "validation"

CONFIG_TEMPLATE = """\
[files]
products = "{products}"
historical_sales = "{sales}"
database = "{database}"
output_directory = "{output}"

[simulation]
days = {days}
seed = {seed}
currency = "EUR"

[demand]
model = "poisson"
mean_source = "historical_daily_mean"

[costs]
holding_per_unit_per_day = {holding}
fixed_per_product_order = {order_cost}

[policies.fixed_quantity]
threshold = {fixed_threshold}
quantity = {fixed_quantity}

[policies.order_up_to]
threshold = {up_to_threshold}
target = {up_to_target}

[extension]
selected = "{extension}"

[storage]
capacity_units = {capacity}
allocation_rules = ["product_id_ascending", "unit_margin_descending"]
"""


def write_config(folder: Path, name: str = "test.toml", **changes) -> Path:
    """Write a valid config into `folder`, with any values overridden by keyword."""
    values = {
        "products": PRODUCTS.as_posix(),
        "sales": SALES.as_posix(),
        "database": "working/test.sqlite",
        "output": "results",
        "days": 60,
        "seed": 2026,
        "holding": 0.02,
        "order_cost": 1.00,
        "fixed_threshold": 20,
        "fixed_quantity": 40,
        "up_to_threshold": 20,
        "up_to_target": 60,
        "extension": "storage",
        "capacity": 300,
    }
    values.update(changes)
    path = folder / name
    path.write_text(CONFIG_TEMPLATE.format(**values), encoding="utf-8")
    return path


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return path
