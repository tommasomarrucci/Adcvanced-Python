import tempfile
import unittest
from pathlib import Path

from inventory_simulator.money import format_eur, to_cents
from inventory_simulator.validation import (PRODUCT_COLUMNS, SALES_COLUMNS, parse_count,
                                            parse_iso_date, validate_inputs)

from support import PRODUCTS, SALES, VALIDATION, write_csv


class ValueParsingTests(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(parse_count(" 12 "), 12)
        self.assertEqual(parse_count("0"), 0)
        for bad in ("-1", "2.5", "", "ten"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_count(bad)

    def test_dates(self):
        self.assertEqual(parse_iso_date("2026-03-31").day, 31)
        for bad in ("2026-02-30", "20260101", "31/03/2026", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_iso_date(bad)

    def test_money(self):
        self.assertEqual(to_cents("1.20"), 120)
        self.assertEqual(to_cents(0.07), 7)  # no float rounding error
        self.assertEqual(format_eur(123456), "1234.56")
        self.assertEqual(format_eur(-5), "-0.05")
        for bad in ("1.234", "abc", "nan"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                to_cents(bad)


class SuppliedSampleTests(unittest.TestCase):
    def test_valid_sample_has_no_problems(self):
        inputs = validate_inputs(PRODUCTS, SALES, storage_capacity=300)
        self.assertEqual(inputs.problems, [])
        self.assertEqual(len(inputs.products), 8)
        self.assertEqual(len(inputs.sales), 720)

    def test_each_invalid_sales_file_is_rejected_with_its_reason(self):
        cases = {
            "sales_negative_quantity.csv": "row 2: units_sold must be a non-negative integer",
            "sales_missing_day.csv": "P001 on 2026-01-01",
            "sales_duplicate_pair.csv": "duplicate of row 2",
            "sales_unknown_product.csv": "row 2: unknown product_id 'P999'",
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                problems = validate_inputs(PRODUCTS, VALIDATION / filename).problems
                self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_zero_cost_catalogue_is_rejected(self):
        problems = validate_inputs(VALIDATION / "products_zero_cost.csv", SALES).problems
        self.assertIn("products row 2: purchase_cost must be positive, got '0.00'", problems)

    def test_initial_stock_above_capacity(self):
        # The sample starts with 270 units in total.
        self.assertEqual(validate_inputs(PRODUCTS, SALES, storage_capacity=270).problems, [])
        problems = validate_inputs(PRODUCTS, SALES, storage_capacity=269).problems
        self.assertTrue(any("exceeds the storage capacity" in p for p in problems))


class HandMadeFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.products = write_csv(self.folder / "products.csv", PRODUCT_COLUMNS,
                                  [["A", "Item", "Cat", "1.00", "2.00", "3"]])

    def sales(self, rows):
        return write_csv(self.folder / "sales.csv", SALES_COLUMNS, rows)

    def thirty_days(self, product="A"):
        return [[f"2026-01-{day:02d}", product, day % 4] for day in range(1, 31)]

    def test_thirty_days_is_enough_twenty_nine_is_not(self):
        self.assertEqual(validate_inputs(self.products, self.sales(self.thirty_days())).problems, [])
        problems = validate_inputs(self.products, self.sales(self.thirty_days()[:29])).problems
        self.assertTrue(any("at least 30 consecutive days" in p for p in problems))

    def test_all_zero_history_is_allowed(self):
        rows = [[f"2026-01-{day:02d}", "A", 0] for day in range(1, 31)]
        self.assertEqual(validate_inputs(self.products, self.sales(rows)).problems, [])

    def test_gap_in_the_middle_is_reported(self):
        rows = [row for row in self.thirty_days() if row[0] != "2026-01-15"]
        problems = validate_inputs(self.products, self.sales(rows)).problems
        self.assertTrue(any("A on 2026-01-15" in p for p in problems), problems)

    def test_malformed_rows_name_the_row(self):
        rows = self.thirty_days()
        rows[4] = ["2026-01-05", "A", "2.5"]  # file row 6
        rows[9] = ["2026/01/10", "A", "1"]    # file row 11
        problems = validate_inputs(self.products, self.sales(rows)).problems
        self.assertTrue(any(p.startswith("historical_sales row 6: units_sold") for p in problems))
        self.assertTrue(any(p.startswith("historical_sales row 11: date") for p in problems))

    def test_short_row_and_missing_column(self):
        path = self.folder / "short.csv"
        path.write_text("date,product_id,units_sold\n2026-01-01,A\n", encoding="utf-8")
        problems = validate_inputs(self.products, path).problems
        self.assertTrue(any("fewer fields" in p for p in problems))

        path.write_text("date,product,units_sold\n", encoding="utf-8")
        problems = validate_inputs(self.products, path).problems
        self.assertTrue(any("missing column(s): product_id" in p for p in problems))

    def test_missing_file_is_a_problem_not_a_crash(self):
        problems = validate_inputs(self.folder / "nope.csv", SALES).problems
        self.assertEqual(len(problems), 1)
        self.assertIn("nope.csv", problems[0])

    def test_duplicate_product_and_empty_catalogue(self):
        products = write_csv(self.folder / "dupes.csv", PRODUCT_COLUMNS,
                             [["A", "x", "c", "1", "2", "3"], ["A", "y", "c", "1", "2", "3"]])
        problems = validate_inputs(products, SALES).problems
        self.assertTrue(any("row 3: duplicate product_id 'A'" in p for p in problems))

        empty = write_csv(self.folder / "empty.csv", PRODUCT_COLUMNS, [])
        self.assertTrue(any("no data rows" in p for p in validate_inputs(empty, SALES).problems))


if __name__ == "__main__":
    unittest.main()
