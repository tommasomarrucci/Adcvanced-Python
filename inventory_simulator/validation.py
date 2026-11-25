"""Reading and validating the input CSV files.

Nothing here touches the database. The functions turn CSV rows into checked
records and collect every problem they find, with the file name and row number,
so the user can fix them all in one go. No problems means the data can be imported.
"""

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

from .money import to_cents

PRODUCT_COLUMNS = ["product_id", "name", "category", "purchase_cost", "selling_price",
                   "initial_stock"]
SALES_COLUMNS = ["date", "product_id", "units_sold"]
MIN_HISTORY_DAYS = 30
MAX_LISTED_GAPS = 10  # how many missing product-date pairs to spell out in the report


class ProductRecord(NamedTuple):
    product_id: str
    name: str
    category: str
    purchase_cost_cents: int
    selling_price_cents: int
    initial_stock: int


class SaleRecord(NamedTuple):
    sale_date: str  # ISO format, YYYY-MM-DD
    product_id: str
    units_sold: int


class ValidatedInput(NamedTuple):
    products: list[ProductRecord]
    sales: list[SaleRecord]
    problems: list[str]


# --- single values ------------------------------------------------------------


def parse_count(text: str) -> int:
    """Parse a non-negative whole number such as "12". Rejects "-1", "2.5" and ""."""
    cleaned = text.strip()
    if not cleaned.isdigit():
        raise ValueError(f"must be a non-negative integer, got {text!r}")
    return int(cleaned)


def parse_price(text: str) -> int:
    """Parse a positive euro amount with at most two decimals and return cents."""
    cents = to_cents(text)
    if cents <= 0:
        raise ValueError(f"must be positive, got {text!r}")
    return cents


def parse_iso_date(text: str) -> date:
    """Parse a date written exactly as YYYY-MM-DD."""
    cleaned = text.strip()
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError:
        raise ValueError(f"must be a valid YYYY-MM-DD date, got {text!r}") from None
    # fromisoformat also accepts other ISO forms such as "20260101".
    if parsed.isoformat() != cleaned:
        raise ValueError(f"must be written as YYYY-MM-DD, got {text!r}")
    return parsed


def _field(row: dict[str, str], column: str, parser):
    """Apply a parser to one column and put the column name in any error message."""
    try:
        return parser(row[column])
    except ValueError as error:
        raise ValueError(f"{column} {error}") from None


def _check_row_shape(row: dict) -> None:
    # csv.DictReader fills missing fields with None and stores extra ones under None.
    if None in row:
        raise ValueError("row has more fields than the header")
    if None in row.values():
        raise ValueError("row has fewer fields than the header")


# --- whole files --------------------------------------------------------------


def read_csv_rows(path: Path, columns: list[str]) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file with a header row.

    Raises FileNotFoundError if the file is missing and ValueError if a column is missing.
    """
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        header = reader.fieldnames or []
        missing = [column for column in columns if column not in header]
        if missing:
            raise ValueError(f"missing column(s): {', '.join(missing)}")
        return list(reader)


def validate_products(rows: list[dict[str, str]]) -> tuple[list[ProductRecord], list[str]]:
    """Check catalogue rows. Returns the valid records and a list of problems."""
    products: list[ProductRecord] = []
    problems: list[str] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            _check_row_shape(row)
            product_id = row["product_id"].strip()
            if not product_id:
                raise ValueError("product_id is empty")
            if product_id in seen_ids:
                raise ValueError(f"duplicate product_id {product_id!r}")
            seen_ids.add(product_id)
            name, category = row["name"].strip(), row["category"].strip()
            if not name or not category:
                raise ValueError("name and category must not be empty")
            product = ProductRecord(
                product_id,
                name,
                category,
                _field(row, "purchase_cost", parse_price),
                _field(row, "selling_price", parse_price),
                _field(row, "initial_stock", parse_count),
            )
        except ValueError as error:
            problems.append(f"products row {row_number}: {error}")
        else:
            products.append(product)
    if not rows:
        problems.append("products: the file has no data rows")
    return products, problems


def validate_sales(
    rows: list[dict[str, str]], product_ids: set[str]
) -> tuple[list[SaleRecord], list[str]]:
    """Check sales rows, then check that the history is complete.

    Every product needs a row for every day between the first and last date, and at
    least MIN_HISTORY_DAYS days in total. A missing row is an error, not a zero.
    """
    sales: list[SaleRecord] = []
    problems: list[str] = []
    first_row_of: dict[tuple[date, str], int] = {}  # (day, product) -> row number

    for row_number, row in enumerate(rows, start=2):
        try:
            _check_row_shape(row)
            day = _field(row, "date", parse_iso_date)
            product_id = row["product_id"].strip()
            if product_id not in product_ids:
                raise ValueError(f"unknown product_id {product_id!r}")
            key = (day, product_id)
            if key in first_row_of:
                raise ValueError(
                    f"duplicate of row {first_row_of[key]} ({product_id} on {day})"
                )
            # Remember the pair before parsing the quantity: a row with a bad quantity
            # is reported once, not again as a "missing day".
            first_row_of[key] = row_number
            units = _field(row, "units_sold", parse_count)
        except ValueError as error:
            problems.append(f"historical_sales row {row_number}: {error}")
        else:
            sales.append(SaleRecord(day.isoformat(), product_id, units))

    problems.extend(check_history_complete(set(first_row_of), product_ids))
    return sales, problems


def check_history_complete(pairs: set[tuple[date, str]], product_ids: set[str]) -> list[str]:
    """Return problems if the (day, product) pairs do not form a complete window."""
    if not pairs:
        return ["historical_sales: no usable rows"]
    days = {day for day, _ in pairs}
    first, last = min(days), max(days)
    length = (last - first).days + 1
    problems = []
    if length < MIN_HISTORY_DAYS:
        problems.append(
            f"historical_sales: covers {length} day(s) from {first} to {last}; "
            f"at least {MIN_HISTORY_DAYS} consecutive days are required"
        )
    missing = [
        (first + timedelta(days=offset), product_id)
        for offset in range(length)
        for product_id in sorted(product_ids)
        if (first + timedelta(days=offset), product_id) not in pairs
    ]
    if missing:
        listed = ", ".join(f"{product_id} on {day}" for day, product_id in missing[:MAX_LISTED_GAPS])
        if len(missing) > MAX_LISTED_GAPS:
            listed += f" and {len(missing) - MAX_LISTED_GAPS} more"
        problems.append(
            f"historical_sales: incomplete history, {len(missing)} missing product-date "
            f"pair(s): {listed}. Missing rows are not treated as zero sales."
        )
    return problems


def validate_inputs(
    products_path: Path, sales_path: Path, storage_capacity: int | None = None
) -> ValidatedInput:
    """Read and check both input files. Never raises for bad data: see .problems."""
    try:
        product_rows = read_csv_rows(products_path, PRODUCT_COLUMNS)
    except (FileNotFoundError, ValueError) as error:
        return ValidatedInput([], [], [f"products file {products_path.name}: {error}"])

    products, problems = validate_products(product_rows)
    total_stock = sum(product.initial_stock for product in products)
    if storage_capacity is not None and total_stock > storage_capacity:
        problems.append(
            f"products: total initial stock {total_stock} exceeds the storage "
            f"capacity of {storage_capacity} units"
        )
    if problems:
        # Checking sales against a broken catalogue would only repeat the same errors.
        problems.append("historical_sales: not checked because the catalogue is invalid")
        return ValidatedInput(products, [], problems)

    try:
        sales_rows = read_csv_rows(sales_path, SALES_COLUMNS)
    except (FileNotFoundError, ValueError) as error:
        return ValidatedInput(products, [], [f"sales file {sales_path.name}: {error}"])

    product_ids = {product.product_id for product in products}
    sales, problems = validate_sales(sales_rows, product_ids)
    return ValidatedInput(products, sales, problems)
