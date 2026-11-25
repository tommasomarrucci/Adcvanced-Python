"""Tests for the database, the import/run workflow and the command line."""

import csv
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from inventory_simulator import database, workflow
from inventory_simulator.cli import main, parse_arguments, UsageError
from inventory_simulator.config import load_config
from inventory_simulator.simulation import generate_demand, simulate
from inventory_simulator.validation import PRODUCT_COLUMNS, SALES_COLUMNS
from tests.support import (SAMPLES, SALES, VALIDATION, must_raise, read_csv, run_tests,
                           write_config, write_csv)


def read_output(settings, name: str) -> str:
    return (settings.output_dir / name).read_text(encoding="utf-8")


# --- imports -------------------------------------------------------------------------


def test_importing_twice_adds_nothing():
    with TemporaryDirectory() as name:
        settings = load_config(write_config(Path(name)))
        connection = database.connect(settings.database_path)
        try:
            first = workflow.import_inputs(connection, settings)
            total_sql = "SELECT SUM(units_sold) FROM historical_sales"
            totals = connection.execute(total_sql).fetchone()[0]
            second = workflow.import_inputs(connection, settings)

            assert (first.new_sales, first.already_stored) == (720, 0)
            assert (second.new_sales, second.already_stored) == (0, 720)
            assert database.count_rows(connection, "historical_sales") == 720
            assert connection.execute(total_sql).fetchone()[0] == totals
        finally:
            connection.close()


def test_conflicting_reimport_is_rejected_and_changes_nothing():
    with TemporaryDirectory() as name:
        folder = Path(name)
        settings = load_config(write_config(folder))
        connection = database.connect(settings.database_path)
        try:
            workflow.import_inputs(connection, settings)

            with SALES.open(encoding="utf-8") as stream:
                rows = list(csv.reader(stream))[1:]
            rows[0][2] = "99"  # P001 on 2026-01-01 was 9
            changed = write_csv(folder / "changed.csv", SALES_COLUMNS, rows)
            settings = load_config(write_config(folder, sales=changed.as_posix()))

            error = must_raise(workflow.InvalidInputError, workflow.import_inputs,
                               connection, settings)
            assert "stored with 9 units but the file says 99" in error.problems[0]
            stored = connection.execute(
                "SELECT units_sold FROM historical_sales "
                "WHERE sale_date = '2026-01-01' AND product_id = 'P001'").fetchone()
            assert stored[0] == 9
        finally:
            connection.close()


def test_invalid_input_writes_report_and_imports_nothing():
    with TemporaryDirectory() as name:
        bad = (VALIDATION / "sales_missing_day.csv").as_posix()
        settings = load_config(write_config(Path(name), sales=bad))
        connection = database.connect(settings.database_path)
        try:
            must_raise(workflow.InvalidInputError, workflow.import_inputs, connection, settings)
            assert database.count_rows(connection, "historical_sales") == 0
        finally:
            connection.close()
        report = read_output(settings, "validation_report.txt")
    assert report.startswith("VALIDATION FAILED")
    assert "P001 on 2026-01-01" in report


def test_schema_constraints_reject_bad_rows():
    with TemporaryDirectory() as name:
        settings = load_config(write_config(Path(name)))
        connection = database.connect(settings.database_path)
        try:
            # Unknown product: the foreign key refuses it.
            must_raise(sqlite3.IntegrityError, connection.execute,
                       "INSERT INTO historical_sales VALUES ('2026-01-01', 'NOPE', 1)")
            # Purchase cost 0: the CHECK constraint refuses it.
            must_raise(sqlite3.IntegrityError, connection.execute,
                       "INSERT INTO products VALUES ('X', 'x', 'c', 0, 100, 1)")
        finally:
            connection.close()


# --- SQL summaries -------------------------------------------------------------------


def test_sql_summaries():
    with TemporaryDirectory() as name:
        settings = load_config(write_config(Path(name)))
        connection = database.connect(settings.database_path)
        try:
            workflow.import_inputs(connection, settings)
            check_by_product_matches_the_supplied_checks(connection)
            check_category_totals_add_up_to_product_totals(connection)
            check_best_sellers_window(connection)
        finally:
            connection.close()


def check_by_product_matches_the_supplied_checks(connection):
    expected = read_csv(SAMPLES / "checks" / "expected_historical_by_product.csv")
    actual = database.sales_by_product(connection)
    assert len(actual) == len(expected)
    for row, check in zip(actual, expected):
        assert row["product_id"] == check["product_id"]
        assert row["days"] == int(check["days"])
        assert row["units_sold"] == int(check["units_sold"])
        assert abs(row["mean_daily_units"] - float(check["mean_daily_units"])) <= 1e-8
        assert row["revenue_cents"] == round(float(check["revenue"]) * 100)
        assert row["cogs_cents"] == round(float(check["cost_of_goods_sold"]) * 100)
        assert row["gross_profit_cents"] == round(float(check["gross_profit"]) * 100)


def check_category_totals_add_up_to_product_totals(connection):
    by_category = database.sales_by_category(connection)
    by_product = database.sales_by_product(connection)
    assert sum(r["revenue_cents"] for r in by_category) == \
        sum(r["revenue_cents"] for r in by_product)
    assert by_category[0]["category"] == "Stationery"  # highest revenue first


def check_best_sellers_window(connection):
    rows = database.best_sellers(connection, "2026-01-01", "2026-01-01", limit=3)
    # From the sample file: P002 sold 16, P001 9, P003 7 on the first day.
    assert [(r["product_id"], r["units_sold"]) for r in rows] == \
        [("P002", 16), ("P001", 9), ("P003", 7)]
    assert database.best_sellers(connection, "2030-01-01", "2030-12-31") == []


# --- full runs -----------------------------------------------------------------------

OUTPUT_FILES = ("historical_summary.csv", "daily_simulation.csv", "policy_comparison.csv",
                "product_comparison.csv", "validation_report.txt", "report.txt")


def test_full_run_writes_every_output_and_is_reproducible():
    with TemporaryDirectory() as name:
        config = write_config(Path(name))
        assert main(["--config", str(config), "run"]) == 0
        settings = load_config(config)
        for output in OUTPUT_FILES:
            assert (settings.output_dir / output).exists(), output
        first_daily = read_output(settings, "daily_simulation.csv")
        first_report = read_output(settings, "report.txt")

        assert main(["--config", str(config), "run"]) == 0
        assert read_output(settings, "daily_simulation.csv") == first_daily
        assert read_output(settings, "report.txt") == first_report

        connection = database.connect(settings.database_path)
        try:
            assert database.count_rows(connection, "simulation_runs") == 4
            assert database.count_rows(connection, "daily_results") == 4 * 60 * 8
            stored = connection.execute(
                "SELECT seed, effective_config FROM simulation_runs").fetchone()
        finally:
            connection.close()
    assert stored["seed"] == 2026
    assert "'seed': 2026" in stored["effective_config"]


def test_every_policy_sees_the_same_demand():
    with TemporaryDirectory() as name:
        config = write_config(Path(name))
        main(["--config", str(config), "run"])
        settings = load_config(config)
        connection = database.connect(settings.database_path)
        try:
            # Pairs (day, product) whose demand differs between runs: there must be none.
            different = connection.execute(
                "SELECT COUNT(*) FROM (SELECT day, product_id FROM daily_results "
                "GROUP BY day, product_id HAVING COUNT(DISTINCT demand) > 1)").fetchone()[0]
        finally:
            connection.close()
    assert different == 0


def test_sql_totals_match_the_numpy_engine():
    with TemporaryDirectory() as name:
        settings = load_config(write_config(Path(name), extension=""))
        connection = database.connect(settings.database_path)
        try:
            workflow.run_comparison(connection, settings)
            catalogue = workflow.load_catalogue(connection)
            demand = generate_demand(catalogue.mean_demand, settings.days, settings.seed)
            rows = database.shop_results(connection, "test")
            for policy, row in zip(settings.policies, rows):
                result = simulate(catalogue, demand, policy, settings.holding_cost_cents,
                                  settings.order_cost_cents)
                assert row["policy"] == policy.name
                assert row["operating_result_cents"] == result.total_operating_result_cents()
                assert row["final_stock"] == int(result.stock_end[-1].sum())
                assert row["outstanding_orders"] == int(result.orders[-1].sum())
        finally:
            connection.close()


def test_core_config_runs_without_allocation_rules():
    with TemporaryDirectory() as name:
        config = write_config(Path(name), extension="")
        assert main(["--config", str(config), "run"]) == 0
        rows = read_csv(load_config(config).output_dir / "policy_comparison.csv")
    assert [r["allocation_rule"] for r in rows] == ["unlimited", "unlimited"]


def test_product_without_demand_has_no_fulfilment_rate():
    with TemporaryDirectory() as name:
        folder = Path(name)
        products = write_csv(folder / "p.csv", PRODUCT_COLUMNS,
                             [["A", "Busy", "C", "1.00", "2.00", "10"],
                              ["B", "Idle", "C", "1.00", "2.00", "0"]])
        sales_rows = []
        for day in range(1, 31):
            sales_rows.append([f"2026-01-{day:02d}", "A", 3])
            sales_rows.append([f"2026-01-{day:02d}", "B", 0])
        sales = write_csv(folder / "s.csv", SALES_COLUMNS, sales_rows)
        config = write_config(folder, products=products.as_posix(), sales=sales.as_posix(),
                              extension="", fixed_threshold=0, up_to_threshold=0,
                              up_to_target=0)
        assert main(["--config", str(config), "run"]) == 0
        rows = read_csv(load_config(config).output_dir / "product_comparison.csv")
    idle = [r for r in rows if r["product_id"] == "B"]
    assert {r["fulfilment_rate"] for r in idle} == {"n/a"}
    assert {r["operating_result_eur"] for r in idle} == {"0.00"}


def test_invalid_input_stops_the_run():
    with TemporaryDirectory() as name:
        bad = (VALIDATION / "sales_duplicate_pair.csv").as_posix()
        config = write_config(Path(name), sales=bad)
        assert main(["--config", str(config), "run"]) == 1
        settings = load_config(config)
        assert not (settings.output_dir / "report.txt").exists()
        assert "VALIDATION FAILED" in read_output(settings, "validation_report.txt")


def test_invalid_config_exit_code():
    assert main(["--config", str(VALIDATION / "invalid_config.toml"), "run"]) == 2


# --- command line --------------------------------------------------------------------


def test_command_line_words_become_a_dictionary():
    words = ["--config", "a.toml", "best-sellers", "2026-01-01", "2026-01-31", "--limit", "3"]
    assert parse_arguments(words) == {"config": "a.toml", "command": "best-sellers",
                                      "limit": 3, "start": "2026-01-01", "end": "2026-01-31"}
    # The order of the words does not matter for --config.
    assert parse_arguments(["run", "--config", "a.toml"])["command"] == "run"


def test_bad_command_lines():
    bad_lines = [
        ["run"],                                    # no --config
        ["--config"],                               # --config without a file
        ["--config", "a.toml"],                     # no command
        ["--config", "a.toml", "fly"],              # unknown command
        ["--config", "a.toml", "run", "extra"],     # run takes no arguments
        ["--config", "a.toml", "best-sellers", "2026-01-01"],          # END missing
        ["--config", "a.toml", "best-sellers", "a", "b", "--limit", "x"],
        ["--config", "a.toml", "run", "--limit", "3"],  # --limit only for best-sellers
    ]
    for words in bad_lines:
        must_raise(UsageError, parse_arguments, words)
    assert main(["--config", "a.toml", "fly"]) == 2


TESTS = [
    test_importing_twice_adds_nothing,
    test_conflicting_reimport_is_rejected_and_changes_nothing,
    test_invalid_input_writes_report_and_imports_nothing,
    test_schema_constraints_reject_bad_rows,
    test_sql_summaries,
    test_full_run_writes_every_output_and_is_reproducible,
    test_every_policy_sees_the_same_demand,
    test_sql_totals_match_the_numpy_engine,
    test_core_config_runs_without_allocation_rules,
    test_product_without_demand_has_no_fulfilment_rate,
    test_invalid_input_stops_the_run,
    test_invalid_config_exit_code,
    test_command_line_words_become_a_dictionary,
    test_bad_command_lines,
]

if __name__ == "__main__":
    run_tests(TESTS)
