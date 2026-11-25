"""Tests for parsing single values and validating the input CSV files."""

from pathlib import Path
from tempfile import TemporaryDirectory

from inventory_simulator.money import format_eur, to_cents
from inventory_simulator.validation import (PRODUCT_COLUMNS, SALES_COLUMNS, parse_count,
                                            parse_iso_date, validate_inputs)
from tests.support import PRODUCTS, SALES, VALIDATION, must_raise, run_tests, write_csv


def test_counts():
    assert parse_count(" 12 ") == 12
    assert parse_count("0") == 0
    for bad in ("-1", "2.5", "", "ten"):
        must_raise(ValueError, parse_count, bad)


def test_dates():
    assert parse_iso_date("2026-03-31").day == 31
    for bad in ("2026-02-30", "20260101", "31/03/2026", ""):
        must_raise(ValueError, parse_iso_date, bad)


def test_money():
    assert to_cents("1.20") == 120
    assert to_cents("3") == 300
    assert to_cents("0.5") == 50
    assert to_cents(0.07) == 7  # no float rounding error
    assert to_cents(-0.02) == -2
    assert format_eur(123456) == "1234.56"
    assert format_eur(-5) == "-0.05"
    for bad in ("1.234", "abc", "nan", "", "1.2.3", "-"):
        must_raise(ValueError, to_cents, bad)


def test_valid_sample_has_no_problems():
    inputs = validate_inputs(PRODUCTS, SALES, storage_capacity=300)
    assert inputs.problems == []
    assert len(inputs.products) == 8
    assert len(inputs.sales) == 720


def test_each_invalid_sales_file_is_rejected_with_its_reason():
    cases = {
        "sales_negative_quantity.csv": "row 2: units_sold must be a non-negative integer",
        "sales_missing_day.csv": "P001 on 2026-01-01",
        "sales_duplicate_pair.csv": "duplicate of row 2",
        "sales_unknown_product.csv": "row 2: unknown product_id 'P999'",
    }
    for filename, expected in cases.items():
        problems = validate_inputs(PRODUCTS, VALIDATION / filename).problems
        found = [problem for problem in problems if expected in problem]
        assert found, (filename, problems)


def test_zero_cost_catalogue_is_rejected():
    problems = validate_inputs(VALIDATION / "products_zero_cost.csv", SALES).problems
    assert "products row 2: purchase_cost must be positive, got '0.00'" in problems


def test_initial_stock_above_capacity():
    # The sample starts with 270 units in total.
    assert validate_inputs(PRODUCTS, SALES, storage_capacity=270).problems == []
    problems = validate_inputs(PRODUCTS, SALES, storage_capacity=269).problems
    assert [p for p in problems if "exceeds the storage capacity" in p], problems


# --- hand-made files in a temporary folder -----------------------------------------


def write_one_product(folder: Path) -> Path:
    return write_csv(folder / "products.csv", PRODUCT_COLUMNS,
                     [["A", "Item", "Cat", "1.00", "2.00", "3"]])


def thirty_days(product: str = "A") -> list[list]:
    return [[f"2026-01-{day:02d}", product, day % 4] for day in range(1, 31)]


def test_thirty_days_is_enough_twenty_nine_is_not():
    with TemporaryDirectory() as name:
        folder = Path(name)
        products = write_one_product(folder)
        sales = write_csv(folder / "sales.csv", SALES_COLUMNS, thirty_days())
        assert validate_inputs(products, sales).problems == []

        sales = write_csv(folder / "sales.csv", SALES_COLUMNS, thirty_days()[:29])
        problems = validate_inputs(products, sales).problems
        assert [p for p in problems if "at least 30 consecutive days" in p], problems


def test_all_zero_history_is_allowed():
    with TemporaryDirectory() as name:
        folder = Path(name)
        rows = [[f"2026-01-{day:02d}", "A", 0] for day in range(1, 31)]
        sales = write_csv(folder / "sales.csv", SALES_COLUMNS, rows)
        assert validate_inputs(write_one_product(folder), sales).problems == []


def test_gap_in_the_middle_is_reported():
    with TemporaryDirectory() as name:
        folder = Path(name)
        rows = [row for row in thirty_days() if row[0] != "2026-01-15"]
        sales = write_csv(folder / "sales.csv", SALES_COLUMNS, rows)
        problems = validate_inputs(write_one_product(folder), sales).problems
    assert [p for p in problems if "A on 2026-01-15" in p], problems


def test_malformed_rows_name_the_row():
    with TemporaryDirectory() as name:
        folder = Path(name)
        rows = thirty_days()
        rows[4] = ["2026-01-05", "A", "2.5"]  # file row 6
        rows[9] = ["2026/01/10", "A", "1"]    # file row 11
        sales = write_csv(folder / "sales.csv", SALES_COLUMNS, rows)
        problems = validate_inputs(write_one_product(folder), sales).problems
    assert [p for p in problems if p.startswith("historical_sales row 6: units_sold")], problems
    assert [p for p in problems if p.startswith("historical_sales row 11: date")], problems


def test_short_row_and_missing_column():
    with TemporaryDirectory() as name:
        folder = Path(name)
        products = write_one_product(folder)
        path = folder / "short.csv"

        path.write_text("date,product_id,units_sold\n2026-01-01,A\n", encoding="utf-8")
        problems = validate_inputs(products, path).problems
        assert [p for p in problems if "fewer fields" in p], problems

        path.write_text("date,product,units_sold\n", encoding="utf-8")
        problems = validate_inputs(products, path).problems
        assert [p for p in problems if "missing column(s): product_id" in p], problems


def test_missing_file_is_a_problem_not_a_crash():
    with TemporaryDirectory() as name:
        problems = validate_inputs(Path(name) / "nope.csv", SALES).problems
    assert len(problems) == 1
    assert "nope.csv" in problems[0]


def test_duplicate_product_and_empty_catalogue():
    with TemporaryDirectory() as name:
        folder = Path(name)
        products = write_csv(folder / "dupes.csv", PRODUCT_COLUMNS,
                             [["A", "x", "c", "1", "2", "3"], ["A", "y", "c", "1", "2", "3"]])
        problems = validate_inputs(products, SALES).problems
        assert [p for p in problems if "row 3: duplicate product_id 'A'" in p], problems

        empty = write_csv(folder / "empty.csv", PRODUCT_COLUMNS, [])
        problems = validate_inputs(empty, SALES).problems
        assert [p for p in problems if "no data rows" in p], problems


TESTS = [
    test_counts,
    test_dates,
    test_money,
    test_valid_sample_has_no_problems,
    test_each_invalid_sales_file_is_rejected_with_its_reason,
    test_zero_cost_catalogue_is_rejected,
    test_initial_stock_above_capacity,
    test_thirty_days_is_enough_twenty_nine_is_not,
    test_all_zero_history_is_allowed,
    test_gap_in_the_middle_is_reported,
    test_malformed_rows_name_the_row,
    test_short_row_and_missing_column,
    test_missing_file_is_a_problem_not_a_crash,
    test_duplicate_product_and_empty_catalogue,
]

if __name__ == "__main__":
    run_tests(TESTS)
