"""Shared helpers for the tests: sample file paths, file writers and a tiny test runner.

Every test is a plain function that uses assert. A test passes if it returns
without raising anything.
"""

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


def write_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def must_raise(exctype, f, *args):
    """Call f(*args) and check that it raises exctype. Returns the exception.

    The same helper as in the L08 multiset exercise.
    """
    got_exc = None
    try:
        f(*args)
    except exctype as exc:
        got_exc = exc
    if got_exc is None:
        raise AssertionError(f"No exception raised, was expecting a {exctype.__name__}")
    return got_exc


def run_tests(tests: list) -> int:
    """Call every test function, print ok or FAIL for each, and return the failures."""
    failures = 0
    for test in tests:
        try:
            test()
        # Any exception means the test failed: a wrong assert (AssertionError) or a
        # crash inside the code being tested. We report it and go on with the next test.
        except Exception as error:
            failures += 1
            print(f"FAIL  {test.__name__}: {type(error).__name__}: {error}")
        else:
            print(f"ok    {test.__name__}")
    print(f"\n{len(tests) - failures} of {len(tests)} tests passed")
    return failures
