"""Command-line interface."""

import argparse
import csv
from pathlib import Path
import sys
import tomllib

from .config import load_config
from .database import best_sellers, category_revenue, connect, historical_summary, import_data, saved_runs
from .reporting import write_csv, write_report
from .simulation import simulate


def _write_validation(path: Path, errors: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VALIDATION FAILED\n" + "\n".join(errors) + "\n" if errors else "VALIDATION PASSED\nNo input problems found.\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inventory-sim", description="Inventory and profitability simulator")
    parser.add_argument("--config", default="inventory_student_sample_files/config/storage.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create the SQLite database")
    subparsers.add_parser("import", help="validate and import configured CSV data")
    subparsers.add_parser("summary", help="export historical sales summaries")
    subparsers.add_parser("run", help="run policy and selected-extension comparisons")
    query_parser = subparsers.add_parser("best-sellers", help="query best sellers in a date window")
    query_parser.add_argument("start")
    query_parser.add_argument("end")
    args = parser.parse_args(argv)
    try:
        settings = load_config(args.config)
        with connect(settings.database_path) as connection:
            if args.command == "init":
                print(f"Database ready: {settings.database_path}")
            elif args.command == "import":
                errors = import_data(connection, settings.products_path, settings.sales_path,
                    settings.capacity if settings.extension == "storage" else None)
                _write_validation(settings.output_path / "validation_report.txt", errors)
                if errors:
                    print("Validation failed; see validation_report.txt", file=sys.stderr)
                    return 2
                print(f"Imported {connection.execute('SELECT COUNT(*) FROM products').fetchone()[0]} products and "
                    f"{connection.execute('SELECT COUNT(*) FROM historical_sales').fetchone()[0]} sales records")
            elif args.command == "summary":
                summaries = [dict(row) for row in historical_summary(connection)]
                write_csv(settings.output_path / "historical_summary.csv", summaries)
                print("Historical summary exported")
                for row in category_revenue(connection):
                    print(f"{row['category']}: EUR {row['revenue']:.2f}")
            elif args.command == "best-sellers":
                for row in best_sellers(connection, args.start, args.end):
                    print(f"{row['product_id']} {row['name']}: {row['units_sold']}")
            elif args.command == "run":
                if connection.execute("SELECT COUNT(*) FROM historical_sales").fetchone()[0] == 0:
                    raise ValueError("Import valid data before running simulations")
                daily, aggregates = simulate(connection, settings)
                by_product: dict[tuple[str, str, str], dict] = {}
                for row in daily:
                    key = (row["run_id"], row["policy"], row["allocation_rule"], row["product_id"])
                    item = by_product.setdefault(key, {"run_id": row["run_id"], "policy": row["policy"],
                        "allocation_rule": row["allocation_rule"], "product_id": row["product_id"],
                        "revenue": 0.0, "cogs": 0.0, "gross_profit": 0.0, "holding_cost": 0.0,
                        "ordering_cost": 0.0, "operating_result": 0.0, "units_sold": 0,
                        "lost_sales": 0, "demand": 0, "final_stock": 0, "outstanding_orders": 0})
                    for metric in ("revenue", "cogs", "gross_profit", "holding_cost", "ordering_cost", "operating_result", "units_sold", "lost_sales", "demand"):
                        item[metric] += row[metric]
                    item["final_stock"] = row["stock_end"]
                    item["outstanding_orders"] = row["order_quantity"]
                product_rows = list(by_product.values())
                for item in product_rows:
                    item["fulfilment_rate"] = item["units_sold"] / item["demand"] if item["demand"] else "N/A"
                    item["final_inventory_value"] = item["final_stock"] * connection.execute(
                        "SELECT purchase_cost FROM products WHERE product_id=?", (item["product_id"],)).fetchone()[0]
                write_csv(settings.output_path / "daily_simulation.csv", daily)
                write_csv(settings.output_path / "policy_comparison.csv", aggregates)
                write_csv(settings.output_path / "product_comparison.csv", product_rows)
                write_report(settings.output_path / "report.txt", aggregates, settings.config_path, settings.extension)
                print(f"Completed {len(aggregates)} scenarios; outputs: {settings.output_path}")
            # The query is also part of the SQL deliverable and is surfaced on summary.
            _ = saved_runs(connection)
        return 0
    except (OSError, KeyError, TypeError, ValueError) as exc:
        try:
            config_path = Path(args.config).expanduser().resolve()
            with config_path.open("rb") as stream:
                raw_config = tomllib.load(stream)
            output_dir = (config_path.parent / raw_config["files"]["output_directory"]).resolve()
            _write_validation(output_dir / "validation_report.txt", [str(exc)])
        except (OSError, KeyError, TypeError, ValueError):
            pass
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
