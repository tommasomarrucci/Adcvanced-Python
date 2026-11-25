import csv
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from inventory_simulator import database, workflow
from inventory_simulator.cli import main
from inventory_simulator.config import load_config
from inventory_simulator.simulation import generate_demand, simulate
from inventory_simulator.validation import PRODUCT_COLUMNS, SALES_COLUMNS

from support import SAMPLES, SALES, VALIDATION, write_config, write_csv


class TempFolderTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def open_db(self, settings):
        connection = database.connect(settings.database_path)
        self.addCleanup(connection.close)
        return connection


class ImportTests(TempFolderTestCase):
    def test_importing_twice_adds_nothing(self):
        settings = load_config(write_config(self.folder))
        connection = self.open_db(settings)
        first = workflow.import_inputs(connection, settings)
        totals = connection.execute("SELECT SUM(units_sold) FROM historical_sales").fetchone()[0]
        second = workflow.import_inputs(connection, settings)

        self.assertEqual((first.new_sales, first.already_stored), (720, 0))
        self.assertEqual((second.new_sales, second.already_stored), (0, 720))
        self.assertEqual(database.count_rows(connection, "historical_sales"), 720)
        self.assertEqual(
            connection.execute("SELECT SUM(units_sold) FROM historical_sales").fetchone()[0], totals)

    def test_conflicting_reimport_is_rejected_and_changes_nothing(self):
        settings = load_config(write_config(self.folder))
        connection = self.open_db(settings)
        workflow.import_inputs(connection, settings)

        with SALES.open(encoding="utf-8") as stream:
            rows = list(csv.reader(stream))[1:]
        rows[0][2] = "99"  # P001 on 2026-01-01 was 9
        changed = write_csv(self.folder / "changed.csv", SALES_COLUMNS, rows)
        settings = load_config(write_config(self.folder, sales=changed.as_posix()))

        with self.assertRaises(workflow.InvalidInputError) as caught:
            workflow.import_inputs(connection, settings)
        self.assertIn("stored with 9 units but the file says 99", caught.exception.problems[0])
        stored = connection.execute("SELECT units_sold FROM historical_sales WHERE "
                                    "sale_date = '2026-01-01' AND product_id = 'P001'").fetchone()
        self.assertEqual(stored[0], 9)

    def test_invalid_input_writes_report_and_imports_nothing(self):
        bad = (VALIDATION / "sales_missing_day.csv").as_posix()
        settings = load_config(write_config(self.folder, sales=bad))
        connection = self.open_db(settings)
        with self.assertRaises(workflow.InvalidInputError):
            workflow.import_inputs(connection, settings)
        self.assertEqual(database.count_rows(connection, "historical_sales"), 0)
        report = (settings.output_dir / "validation_report.txt").read_text(encoding="utf-8")
        self.assertTrue(report.startswith("VALIDATION FAILED"))
        self.assertIn("P001 on 2026-01-01", report)

    def test_schema_constraints_reject_bad_rows(self):
        settings = load_config(write_config(self.folder))
        connection = self.open_db(settings)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO historical_sales VALUES ('2026-01-01', 'NOPE', 1)")
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO products VALUES ('X', 'x', 'c', 0, 100, 1)")


class SqlSummaryTests(TempFolderTestCase):
    def setUp(self):
        super().setUp()
        self.settings = load_config(write_config(self.folder))
        self.connection = self.open_db(self.settings)
        workflow.import_inputs(self.connection, self.settings)

    def test_by_product_matches_the_supplied_checks(self):
        with (SAMPLES / "checks" / "expected_historical_by_product.csv").open(encoding="utf-8") as f:
            expected = list(csv.DictReader(f))
        actual = database.sales_by_product(self.connection)
        self.assertEqual(len(actual), len(expected))
        for row, check in zip(actual, expected):
            self.assertEqual(row["product_id"], check["product_id"])
            self.assertEqual(row["days"], int(check["days"]))
            self.assertEqual(row["units_sold"], int(check["units_sold"]))
            self.assertAlmostEqual(row["mean_daily_units"], float(check["mean_daily_units"]),
                                   delta=1e-8)
            self.assertEqual(row["revenue_cents"], round(float(check["revenue"]) * 100))
            self.assertEqual(row["cogs_cents"], round(float(check["cost_of_goods_sold"]) * 100))
            self.assertEqual(row["gross_profit_cents"], round(float(check["gross_profit"]) * 100))

    def test_category_totals_add_up_to_product_totals(self):
        by_category = database.sales_by_category(self.connection)
        by_product = database.sales_by_product(self.connection)
        self.assertEqual(sum(r["revenue_cents"] for r in by_category),
                         sum(r["revenue_cents"] for r in by_product))
        self.assertEqual(by_category[0]["category"], "Stationery")  # highest revenue first

    def test_best_sellers_window(self):
        rows = database.best_sellers(self.connection, "2026-01-01", "2026-01-01", limit=3)
        # From the sample file: P002 sold 16, P001 9, P003 7 on the first day.
        self.assertEqual([(r["product_id"], r["units_sold"]) for r in rows],
                         [("P002", 16), ("P001", 9), ("P003", 7)])
        self.assertEqual(database.best_sellers(self.connection, "2030-01-01", "2030-12-31"), [])


class RunTests(TempFolderTestCase):
    def read(self, settings, name):
        return (settings.output_dir / name).read_text(encoding="utf-8")

    def test_full_run_writes_every_output_and_is_reproducible(self):
        config = write_config(self.folder)
        self.assertEqual(main(["--config", str(config), "run"]), 0)
        settings = load_config(config)
        for name in ("historical_summary.csv", "daily_simulation.csv", "policy_comparison.csv",
                     "product_comparison.csv", "validation_report.txt", "report.txt"):
            self.assertTrue((settings.output_dir / name).exists(), name)
        first_daily = self.read(settings, "daily_simulation.csv")
        first_report = self.read(settings, "report.txt")

        self.assertEqual(main(["--config", str(config), "run"]), 0)
        self.assertEqual(self.read(settings, "daily_simulation.csv"), first_daily)
        self.assertEqual(self.read(settings, "report.txt"), first_report)

        with closing(database.connect(settings.database_path)) as connection:
            self.assertEqual(database.count_rows(connection, "simulation_runs"), 4)
            self.assertEqual(database.count_rows(connection, "daily_results"), 4 * 60 * 8)
            stored = connection.execute("SELECT seed, effective_config FROM simulation_runs").fetchone()
        self.assertEqual(stored["seed"], 2026)
        self.assertEqual(json.loads(stored["effective_config"])["seed"], 2026)

    def test_every_policy_sees_the_same_demand(self):
        config = write_config(self.folder)
        main(["--config", str(config), "run"])
        settings = load_config(config)
        with closing(database.connect(settings.database_path)) as connection:
            distinct = connection.execute(
                "SELECT COUNT(*) FROM (SELECT day, product_id FROM daily_results "
                "GROUP BY day, product_id HAVING COUNT(DISTINCT demand) > 1)").fetchone()[0]
        self.assertEqual(distinct, 0)

    def test_sql_totals_match_the_numpy_engine(self):
        config = write_config(self.folder, extension="")
        settings = load_config(config)
        connection = self.open_db(settings)
        workflow.run_comparison(connection, settings)
        catalogue = workflow.load_catalogue(connection)
        demand = generate_demand(catalogue.mean_demand, settings.days, settings.seed)
        for policy, row in zip(settings.policies, database.shop_results(connection, "test")):
            result = simulate(catalogue, demand, policy, settings.holding_cost_cents,
                              settings.order_cost_cents)
            self.assertEqual(row["policy"], policy.name)
            self.assertEqual(row["operating_result_cents"], result.total_operating_result_cents())
            self.assertEqual(row["final_stock"], int(result.stock_end[-1].sum()))
            self.assertEqual(row["outstanding_orders"], int(result.orders[-1].sum()))

    def test_core_config_runs_without_allocation_rules(self):
        config = write_config(self.folder, extension="")
        self.assertEqual(main(["--config", str(config), "run"]), 0)
        rows = list(csv.DictReader(
            (load_config(config).output_dir / "policy_comparison.csv").open(encoding="utf-8")))
        self.assertEqual([r["allocation_rule"] for r in rows], ["unlimited", "unlimited"])

    def test_product_without_demand_has_no_fulfilment_rate(self):
        products = write_csv(self.folder / "p.csv", PRODUCT_COLUMNS,
                             [["A", "Busy", "C", "1.00", "2.00", "10"],
                              ["B", "Idle", "C", "1.00", "2.00", "0"]])
        sales = write_csv(self.folder / "s.csv", SALES_COLUMNS,
                          [[f"2026-01-{d:02d}", p, 3 if p == "A" else 0]
                           for d in range(1, 31) for p in "AB"])
        config = write_config(self.folder, products=products.as_posix(), sales=sales.as_posix(),
                              extension="", fixed_threshold=0, up_to_threshold=0, up_to_target=0)
        self.assertEqual(main(["--config", str(config), "run"]), 0)
        rows = list(csv.DictReader(
            (load_config(config).output_dir / "product_comparison.csv").open(encoding="utf-8")))
        idle = [r for r in rows if r["product_id"] == "B"]
        self.assertEqual({r["fulfilment_rate"] for r in idle}, {"n/a"})
        self.assertEqual({r["operating_result_eur"] for r in idle}, {"0.00"})

    def test_invalid_input_stops_the_run(self):
        bad = (VALIDATION / "sales_duplicate_pair.csv").as_posix()
        config = write_config(self.folder, sales=bad)
        self.assertEqual(main(["--config", str(config), "run"]), 1)
        settings = load_config(config)
        self.assertFalse((settings.output_dir / "report.txt").exists())
        self.assertIn("VALIDATION FAILED", self.read(settings, "validation_report.txt"))

    def test_invalid_config_exit_code(self):
        self.assertEqual(main(["--config", str(VALIDATION / "invalid_config.toml"), "run"]), 2)


if __name__ == "__main__":
    unittest.main()
