"""The steps behind each command: validate, import, simulate, save and export.

These functions take settings and an open database connection and do the work.
They never read the command line or print, so tests can call them directly.
"""

import json
import sqlite3
from pathlib import Path
from typing import NamedTuple

import numpy as np

from . import database
from .config import Settings
from .money import format_eur
from .reporting import build_report, to_output_row, write_csv, write_validation_report
from .simulation import RNG_METHOD, Catalogue, StorageLimit, generate_demand, simulate
from .validation import validate_inputs


class InvalidInputError(Exception):
    """The input files failed validation. The problems are in validation_report.txt."""

    def __init__(self, problems: list[str], report_path: Path) -> None:
        super().__init__(f"{len(problems)} input problem(s), see {report_path}")
        self.problems = problems
        self.report_path = report_path


class ImportSummary(NamedTuple):
    products: int
    new_sales: int
    already_stored: int


class RunSummary(NamedTuple):
    run_ids: list[str]
    output_files: list[Path]


def import_inputs(connection: sqlite3.Connection, settings: Settings) -> ImportSummary:
    """Validate the configured CSV files and store them. Always writes a validation report.

    Raises InvalidInputError, without changing the database, if anything is wrong.
    """
    report_path = settings.output_dir / "validation_report.txt"
    inputs = validate_inputs(settings.products_path, settings.sales_path,
                             settings.storage_capacity)
    problems = inputs.problems
    if not problems:
        problems = database.find_conflicts(connection, inputs.sales)

    sources = [f"Configuration: {settings.config_path}",
               f"Products file: {settings.products_path}",
               f"Sales file:    {settings.sales_path}"]
    write_validation_report(report_path, sources, problems)
    if problems:
        raise InvalidInputError(problems, report_path)

    new_sales = database.import_records(connection, inputs.products, inputs.sales)
    return ImportSummary(len(inputs.products), new_sales, len(inputs.sales) - new_sales)


def export_historical_summary(connection: sqlite3.Connection, settings: Settings) -> Path:
    """Write historical_summary.csv: one row per product, per category and for the shop."""
    rows = [{"level": "product", **to_output_row(row)}
            for row in database.sales_by_product(connection)]
    rows += [{"level": "category", **to_output_row(row)}
             for row in database.sales_by_category(connection)]
    columns = ["level", "product_id", "name", "category", "products", "days", "units_sold",
               "mean_daily_units", "revenue_eur", "cogs_eur", "gross_profit_eur"]
    path = settings.output_dir / "historical_summary.csv"
    write_csv(path, rows, columns)  # columns a row does not have are left empty
    return path


def load_catalogue(connection: sqlite3.Connection) -> Catalogue:
    rows = database.load_catalogue_rows(connection)
    if not rows:
        raise ValueError("the database has no products with sales history; run import first")
    return Catalogue(
        product_ids=[row["product_id"] for row in rows],
        price_cents=[row["selling_price_cents"] for row in rows],
        cost_cents=[row["purchase_cost_cents"] for row in rows],
        initial_stock=[row["initial_stock"] for row in rows],
        mean_demand=[row["mean_demand"] for row in rows],
    )


def run_comparison(connection: sqlite3.Connection, settings: Settings) -> RunSummary:
    """Import, simulate every policy (and allocation rule), save, and write all outputs."""
    import_inputs(connection, settings)
    catalogue = load_catalogue(connection)

    # One demand array for every scenario, so differences come from the decisions only.
    demand = generate_demand(catalogue.mean_demand, settings.days, settings.seed)

    run_ids = []
    with connection:  # all runs of this comparison are saved together, or none
        for policy in settings.policies:
            for rule in settings.allocation_rules:
                storage = None
                if settings.extension == "storage":
                    storage = StorageLimit(settings.storage_capacity, rule)
                result = simulate(catalogue, demand, policy, settings.holding_cost_cents,
                                  settings.order_cost_cents, storage)
                run_id = f"{settings.scenario}-seed{settings.seed}-{policy.name}-{rule}"
                run = {
                    "run_id": run_id,
                    "scenario": settings.scenario,
                    "policy": policy.name,
                    "policy_parameters": json.dumps(policy.parameters()),
                    "allocation_rule": rule,
                    "storage_capacity": settings.storage_capacity,
                    "days": settings.days,
                    "seed": settings.seed,
                    "rng_method": RNG_METHOD,
                    "numpy_version": np.__version__,
                    "effective_config": settings.to_json(),
                }
                database.save_run(connection, run, catalogue.product_ids, result)
                run_ids.append(run_id)

    return RunSummary(run_ids, export_results(connection, settings))


def export_results(connection: sqlite3.Connection, settings: Settings) -> list[Path]:
    """Write the result CSV files and report.txt from what is stored in the database."""
    folder = settings.output_dir
    shop_rows = database.shop_results(connection, settings.scenario)
    product_rows = database.product_results(connection, settings.scenario)

    # Extension comparison: how far each scenario is behind the best one.
    comparison = []
    best = max(row["operating_result_cents"] for row in shop_rows)
    for row in shop_rows:
        output = to_output_row(row)
        output["gap_to_best_eur"] = format_eur(best - row["operating_result_cents"])
        comparison.append(output)

    tables = {
        "daily_simulation.csv": [to_output_row(row) for row in
                                 database.daily_results(connection, settings.scenario)],
        "policy_comparison.csv": comparison,
        "product_comparison.csv": [to_output_row(row) for row in product_rows],
    }
    paths = [export_historical_summary(connection, settings)]
    for name, rows in tables.items():
        write_csv(folder / name, rows)
        paths.append(folder / name)

    report = build_report(
        settings,
        window=database.history_window(connection),
        categories=database.sales_by_category(connection),
        shop_rows=shop_rows,
        product_rows=product_rows,
        saved=database.saved_runs(connection),
    )
    (folder / "report.txt").write_text(report, encoding="utf-8")
    paths += [folder / "report.txt", folder / "validation_report.txt"]
    return paths
