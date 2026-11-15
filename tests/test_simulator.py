import csv
import tempfile
import unittest
from pathlib import Path

from inventory_simulator.config import load_config
from inventory_simulator.database import connect, historical_summary, import_data
from inventory_simulator.simulation import FixedQuantityPolicy, OrderUpToPolicy, generate_demand, load_products


class SimulatorTests(unittest.TestCase):
    def test_policy_boundaries(self):
        fixed = FixedQuantityPolicy(20, 40)
        up_to = OrderUpToPolicy(20, 60)
        self.assertEqual(fixed.requested_order(19), 40)
        self.assertEqual(fixed.requested_order(20), 0)
        self.assertEqual(up_to.requested_order(19), 41)
        self.assertEqual(up_to.requested_order(20), 0)

    def test_seed_reproduces_demand(self):
        from inventory_simulator.simulation import Product
        products = [Product("A", "A", "cat", 1, 2, 0, 2.0), Product("B", "B", "cat", 1, 2, 0, 3.0)]
        self.assertTrue((generate_demand(products, 5, 81) == generate_demand(products, 5, 81)).all())

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            products = root / "products.csv"
            sales = root / "sales.csv"
            products.write_text("product_id,name,category,purchase_cost,selling_price,initial_stock\nA,Item,Cat,1,2,2\n", encoding="utf-8")
            with sales.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["date", "product_id", "units_sold"])
                for day in range(1, 31):
                    writer.writerow([f"2026-01-{day:02}", "A", day % 4])
            with connect(root / "db.sqlite") as connection:
                self.assertEqual(import_data(connection, products, sales), [])
                self.assertEqual(import_data(connection, products, sales), [])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM historical_sales").fetchone()[0], 30)

    def test_supplied_storage_configuration(self):
        project = Path(__file__).resolve().parents[1]
        settings = load_config(project / "inventory_student_sample_files/config/storage.toml")
        self.assertEqual(settings.capacity, 300)
        self.assertEqual(settings.extension, "storage")

    def test_historical_summary_matches_supplied_checks(self):
        project = Path(__file__).resolve().parents[1]
        settings = load_config(project / "inventory_student_sample_files/config/storage.toml")
        with connect(settings.database_path) as connection:
            errors = import_data(connection, settings.products_path, settings.sales_path, settings.capacity)
            self.assertEqual(errors, [])
            actual = historical_summary(connection)
        with (project / "inventory_student_sample_files/checks/expected_historical_by_product.csv").open(newline="", encoding="utf-8") as stream:
            expected = list(csv.DictReader(stream))
        for actual_row, expected_row in zip(actual, expected):
            self.assertEqual(actual_row["product_id"], expected_row["product_id"])
            self.assertEqual(actual_row["units_sold"], int(expected_row["units_sold"]))
            self.assertAlmostEqual(actual_row["mean_daily_units"], float(expected_row["mean_daily_units"]), places=8)
            for metric in ("revenue", "cost_of_goods_sold", "gross_profit"):
                self.assertAlmostEqual(actual_row[metric], float(expected_row[metric]), places=2)


if __name__ == "__main__":
    unittest.main()
