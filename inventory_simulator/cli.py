"""Command-line interface. Reads the arguments, calls the workflow and prints results.

Exit codes: 0 success, 1 invalid input or runtime error, 2 invalid configuration or
a command line that cannot be understood.
"""

import sqlite3
import sys

from . import database, workflow
from .config import ConfigError, Settings, load_config, output_dir_if_known
from .money import format_eur
from .reporting import write_validation_report
from .validation import parse_iso_date


def cmd_init(connection: sqlite3.Connection, settings: Settings, arguments: dict) -> None:
    # connect() has already created any missing tables.
    print(f"Database ready: {settings.database_path}")
    for table in ("products", "historical_sales", "simulation_runs", "daily_results"):
        print(f"  {table}: {database.count_rows(connection, table)} rows")


def cmd_import(connection: sqlite3.Connection, settings: Settings, arguments: dict) -> None:
    summary = workflow.import_inputs(connection, settings)
    print(f"Validation passed. Imported {summary.products} products; "
          f"{summary.new_sales} new sales rows, {summary.already_stored} already stored.")


def cmd_summary(connection: sqlite3.Connection, settings: Settings, arguments: dict) -> None:
    path = workflow.export_historical_summary(connection, settings)
    window = database.history_window(connection)
    print(f"History: {window['days']} days, {window['first_day']} to {window['last_day']}")
    print("Revenue by category:")
    for row in database.sales_by_category(connection):
        print(f"  {row['category']:<12} EUR {format_eur(row['revenue_cents']):>10}")
    print(f"Written: {path}")


def cmd_best_sellers(connection: sqlite3.Connection, settings: Settings, arguments: dict) -> None:
    first, last = parse_iso_date(arguments["start"]), parse_iso_date(arguments["end"])
    if first > last:
        raise ValueError("the start date must not be after the end date")
    if arguments["limit"] <= 0:
        raise ValueError("--limit must be positive")
    rows = database.best_sellers(connection, first.isoformat(), last.isoformat(),
                                 arguments["limit"])
    print(f"Best sellers from {first} to {last}:")
    for rank, row in enumerate(rows, start=1):
        print(f"  {rank}. {row['product_id']} {row['name']:<16} {row['units_sold']:>6} units"
              f"   EUR {format_eur(row['revenue_cents'])}")
    if not rows:
        print("  no sales in this period")


def cmd_run(connection: sqlite3.Connection, settings: Settings, arguments: dict) -> None:
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


def cmd_runs(connection: sqlite3.Connection, settings: Settings, arguments: dict) -> None:
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

USAGE = """usage: python -m inventory_simulator --config FILE COMMAND

commands:
  init                               create the SQLite database and its tables
  import                             validate the CSV files and store them
  summary                            write historical_summary.csv (SQL summaries)
  best-sellers START END [--limit N] best-selling products between two dates
                                     (YYYY-MM-DD, both included; N is 5 by default)
  run                                validate, import, simulate and write every output file
  runs                               list the simulation runs saved in the database
"""


class UsageError(Exception):
    """The command line is incomplete or has words we do not understand."""


def take_option(words: list[str], option: str) -> str | None:
    """Remove `option` and the word after it from `words` and return that word.

    Returns None if the option is not there. take_option(["--config", "a.toml", "run"],
    "--config") returns "a.toml" and leaves ["run"] in the list.
    """
    if option not in words:
        return None
    position = words.index(option)
    if position + 1 >= len(words):
        raise UsageError(f"{option} must be followed by a value")
    value = words[position + 1]
    del words[position:position + 2]
    return value


def parse_arguments(argv: list[str]) -> dict:
    """Turn the list of command-line words into a dictionary.

    ["--config", "storage.toml", "best-sellers", "2026-01-01", "2026-01-31", "--limit", "3"]
    becomes {"config": "storage.toml", "command": "best-sellers", "limit": 3,
             "start": "2026-01-01", "end": "2026-01-31"}.
    """
    words = list(argv)  # a copy, so the caller's list is not changed

    config = take_option(words, "--config")
    if config is None:
        raise UsageError("--config FILE is required")

    limit_text = take_option(words, "--limit")
    limit = 5
    if limit_text is not None:
        try:
            limit = int(limit_text)
        except ValueError:
            raise UsageError(f"--limit must be a whole number, got {limit_text!r}")

    if not words:
        raise UsageError("a command is missing")
    command, extra = words[0], words[1:]
    if command not in COMMANDS:
        raise UsageError(f"unknown command {command!r}")

    arguments = {"config": config, "command": command, "limit": limit}
    if command == "best-sellers":
        if len(extra) != 2:
            raise UsageError("best-sellers needs a START and an END date")
        arguments["start"], arguments["end"] = extra
    else:
        if limit_text is not None:
            raise UsageError("--limit can only be used with best-sellers")
        if extra:
            raise UsageError(f"{command} takes no other arguments, got {extra}")
    return arguments


def main(argv: list[str] | None = None) -> int:
    """Run one command and return the exit code.

    argv is the list of words after the program name. When it is not given we take it
    from sys.argv, which is that same list for the real command line; the tests pass
    their own list instead.
    """
    if argv is None:
        argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0

    try:
        arguments = parse_arguments(argv)
    except UsageError as error:
        print(f"Error: {error}")
        print(USAGE)
        return 2

    try:
        settings = load_config(arguments["config"])
    except ConfigError as error:
        print(f"Invalid configuration: {error}")
        output_dir = output_dir_if_known(arguments["config"])
        if output_dir is not None:
            report = output_dir / "validation_report.txt"
            write_validation_report(report, [f"Configuration: {arguments['config']}"],
                                    [f"configuration: {error}"], data_checked=False)
            print(f"See {report}")
        return 2

    connection = None
    try:
        connection = database.connect(settings.database_path)
        run_command = COMMANDS[arguments["command"]]
        run_command(connection, settings, arguments)
    except workflow.InvalidInputError as error:
        print(f"Validation failed: {error}")
        for problem in error.problems[:5]:
            print(f"  - {problem}")
        return 1
    except ValueError as error:
        print(f"Error: {error}")
        return 1
    except (sqlite3.Error, OSError) as error:
        print(f"Error while reading or writing files or the database: {error}")
        return 1
    finally:
        # Runs after a return too, so the database is always closed.
        if connection is not None:
            connection.close()
    return 0
