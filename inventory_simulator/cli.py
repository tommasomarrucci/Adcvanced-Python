"""Command-line interface. Parses arguments, calls the workflow and prints results.

Exit codes: 0 success, 1 invalid input or runtime error, 2 invalid configuration.
"""

import argparse
import sqlite3
import sys
from contextlib import closing

from . import database, workflow
from .config import ConfigError, Settings, load_config, output_dir_if_known
from .money import format_eur
from .reporting import write_validation_report
from .validation import parse_iso_date


def cmd_init(connection: sqlite3.Connection, settings: Settings, args) -> None:
    # connect() has already created any missing tables.
    print(f"Database ready: {settings.database_path}")
    for table in ("products", "historical_sales", "simulation_runs", "daily_results"):
        print(f"  {table}: {database.count_rows(connection, table)} rows")


def cmd_import(connection: sqlite3.Connection, settings: Settings, args) -> None:
    summary = workflow.import_inputs(connection, settings)
    print(f"Validation passed. Imported {summary.products} products; "
          f"{summary.new_sales} new sales rows, {summary.already_stored} already stored.")


def cmd_summary(connection: sqlite3.Connection, settings: Settings, args) -> None:
    path = workflow.export_historical_summary(connection, settings)
    window = database.history_window(connection)
    print(f"History: {window['days']} days, {window['first_day']} to {window['last_day']}")
    print("Revenue by category:")
    for row in database.sales_by_category(connection):
        print(f"  {row['category']:<12} EUR {format_eur(row['revenue_cents']):>10}")
    print(f"Written: {path}")


def cmd_best_sellers(connection: sqlite3.Connection, settings: Settings, args) -> None:
    first, last = parse_iso_date(args.start), parse_iso_date(args.end)
    if first > last:
        raise ValueError("the start date must not be after the end date")
    if args.limit <= 0:
        raise ValueError("--limit must be positive")
    rows = database.best_sellers(connection, first.isoformat(), last.isoformat(), args.limit)
    print(f"Best sellers from {first} to {last}:")
    for rank, row in enumerate(rows, start=1):
        print(f"  {rank}. {row['product_id']} {row['name']:<16} {row['units_sold']:>6} units"
              f"   EUR {format_eur(row['revenue_cents'])}")
    if not rows:
        print("  no sales in this period")


def cmd_run(connection: sqlite3.Connection, settings: Settings, args) -> None:
    summary = workflow.run_comparison(connection, settings)
    print(f"Simulated {len(summary.run_ids)} scenario(s) over {settings.days} days "
          f"(seed {settings.seed}).")
    for row in database.shop_results(connection, settings.scenario):
        print(f"  {row['policy']:<15} {row['allocation_rule']:<23} "
              f"operating result EUR {format_eur(row['operating_result_cents']):>9}, "
              f"lost {row['lost_sales']} units")
    print("Outputs:")
    for path in summary.output_files:
        print(f"  {path}")


def cmd_runs(connection: sqlite3.Connection, settings: Settings, args) -> None:
    rows = database.saved_runs(connection)
    if not rows:
        print("No simulation runs saved yet.")
    for row in rows:
        print(f"{row['run_id']:<55} {row['days']:>3} days  "
              f"EUR {format_eur(row['operating_result_cents']):>9}  "
              f"lost {row['lost_sales']:>4}  saved {row['created_at']}")


COMMANDS = {
    "init": cmd_init,
    "import": cmd_import,
    "summary": cmd_summary,
    "best-sellers": cmd_best_sellers,
    "run": cmd_run,
    "runs": cmd_runs,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m inventory_simulator",
        description="Inventory and profitability simulator for a small shop.",
    )
    parser.add_argument("--config", required=True, help="path to the TOML configuration file")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create the SQLite database and its tables")
    commands.add_parser("import", help="validate the CSV files and store them")
    commands.add_parser("summary", help="write historical_summary.csv (SQL summaries)")
    best = commands.add_parser("best-sellers", help="best-selling products between two dates")
    best.add_argument("start", help="first day, YYYY-MM-DD")
    best.add_argument("end", help="last day, YYYY-MM-DD (included)")
    best.add_argument("--limit", type=int, default=5, help="how many products (default 5)")
    commands.add_parser("run", help="validate, import, simulate and write every output file")
    commands.add_parser("runs", help="list the simulation runs saved in the database")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = load_config(args.config)
    except ConfigError as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        output_dir = output_dir_if_known(args.config)
        if output_dir is not None:
            report = output_dir / "validation_report.txt"
            write_validation_report(report, [f"Configuration: {args.config}"],
                                    [f"configuration: {error}"], data_checked=False)
            print(f"See {report}", file=sys.stderr)
        return 2

    try:
        with closing(database.connect(settings.database_path)) as connection:
            COMMANDS[args.command](connection, settings, args)
    except workflow.InvalidInputError as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        for problem in error.problems[:5]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (sqlite3.Error, OSError) as error:
        print(f"Error while reading or writing files or the database: {error}", file=sys.stderr)
        return 1
    return 0
