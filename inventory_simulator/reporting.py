"""Writing CSV files and the two text reports (validation and results)."""

import csv
from pathlib import Path
from typing import Mapping

from .config import Settings
from .money import format_eur


def to_output_row(row: Mapping) -> dict[str, object]:
    """Prepare a database row for CSV output.

    Columns ending in _cents become _eur columns with two decimals, and a missing
    value (fulfilment rate with zero demand) is written as "n/a".
    """
    output: dict[str, object] = {}
    for key in row.keys():
        value = row[key]
        if key.endswith("_cents"):
            output[key.removesuffix("_cents") + "_eur"] = format_eur(value)
        elif value is None:
            output[key] = "n/a"
        else:
            output[key] = value
    return output


def write_csv(
    path: Path, rows: list[dict[str, object]], columns: list[str] | None = None
) -> None:
    """Write rows to a UTF-8 CSV file, replacing it.

    By default the columns are the keys of the first row.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        if not rows:
            return
        writer = csv.DictWriter(stream, fieldnames=columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_validation_report(
    path: Path, sources: list[str], problems: list[str], data_checked: bool = True
) -> None:
    """Write validation_report.txt: PASSED or FAILED, what was checked, every problem."""
    lines = ["VALIDATION " + ("FAILED" if problems else "PASSED"), ""]
    lines += sources
    if data_checked:
        lines += [
            "",
            "Checks: required columns; unique, non-empty product ids; positive costs and",
            "prices with at most two decimals; non-negative integer stock and units;",
            "YYYY-MM-DD dates; known products; one row per product and day; a complete,",
            "consecutive history of at least 30 days; no conflicts with sales already stored;",
            "initial stock within storage capacity (storage extension only).",
        ]
    lines.append("")
    if problems:
        lines.append(f"{len(problems)} problem(s) found. Nothing was imported or simulated.")
        lines += [f"- {problem}" for problem in problems]
    else:
        lines.append("No problems found.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _eur(cents: int) -> str:
    return f"EUR {format_eur(cents)}"


def build_report(
    settings: Settings,
    window: Mapping,
    categories: list[Mapping],
    shop_rows: list[Mapping],
    product_rows: list[Mapping],
    saved: list[Mapping],
) -> str:
    """Return the text of report.txt."""
    storage = settings.extension == "storage"
    lines = [
        "INVENTORY AND PROFITABILITY SIMULATOR - RESULTS",
        "",
        f"Configuration: {settings.config_path.name} (scenario '{settings.scenario}')",
        f"Extension: {'storage capacity' if storage else 'none (core only)'}",
        f"Horizon: {settings.days} days, seed {settings.seed}, "
        f"holding cost {_eur(settings.holding_cost_cents)} per unit per day, "
        f"order cost {_eur(settings.order_cost_cents)} per product order",
        "Policies: " + ", ".join(str(policy) for policy in settings.policies),
    ]
    if storage:
        lines.append(f"Storage: {settings.storage_capacity} units in total, allocation rules "
                     + " and ".join(settings.allocation_rules))

    lines += ["", "1. HISTORICAL DATA",
              f"{window['days']} days ({window['first_day']} to {window['last_day']}), "
              f"{window['products']} products. Revenue by category:"]
    for row in categories:
        lines.append(f"   {row['category']:<12} {_eur(row['revenue_cents']):>14}"
                     f"   ({row['units_sold']} units)")

    lines += ["", "2. POLICY COMPARISON (whole shop, same demand array for every row)", ""]
    header = (f"{'policy':<15} {'allocation':<23} {'operating':>10} {'revenue':>9} "
              f"{'holding':>8} {'ordering':>8} {'lost':>5} {'fulfil':>7} {'stock':>6} "
              f"{'on order':>8}")
    lines += [header, "-" * len(header)]
    for row in shop_rows:
        lines.append(
            f"{row['policy']:<15} {row['allocation_rule']:<23} "
            f"{format_eur(row['operating_result_cents']):>10} "
            f"{format_eur(row['revenue_cents']):>9} "
            f"{format_eur(row['holding_cost_cents']):>8} "
            f"{format_eur(row['ordering_cost_cents']):>8} "
            f"{row['lost_sales']:>5} {_rate(row['fulfilment_rate']):>7} "
            f"{row['final_stock']:>6} {row['outstanding_orders']:>8}"
        )
    lines += ["", "Operating result = revenue - cost of goods sold - holding - ordering costs.",
              "'stock' is final on-hand stock; 'on order' are units ordered on the last day,",
              "already charged but not yet received. Final inventory value is in",
              "policy_comparison.csv and is not deducted as cost of goods sold."]

    if storage:
        lines += ["", "3. STORAGE EXTENSION: ALLOCATION RULES"]
        lines += _storage_comparison(shop_rows, product_rows)

    policies = {policy.name: policy for policy in settings.policies}
    lines += ["", "4. RECOMMENDATION"] + _recommendation(shop_rows, policies)

    lines += [
        "",
        "5. ASSUMPTIONS",
        "- Historical sales are treated as demand: the shop had no stockouts in the past.",
        "- Each product's daily demand is Poisson with its historical daily mean, drawn",
        "  independently for every day and product (NumPy default_rng with the seed above).",
        "- Prices and purchase costs are fixed. Orders arrive the next morning (one-day lead time).",
        "- Unmet demand is lost for good; customers do not come back the next day.",
        "",
        "6. LIMITATIONS",
        "- The comparison uses one 60-day demand path from one seed. Small gaps between",
        "  scenarios can change sign with another seed; we do not measure that uncertainty.",
        "- If past stockouts did happen, historical sales understate demand and the policies",
        "  look better than they would be.",
        "- Poisson demand with a constant mean has no trend, weekly pattern or seasonality,",
        "  and treats products as independent.",
        "- Historical revenue uses today's catalogue prices for the whole history.",
        "",
        "7. SAVED RUNS IN THE DATABASE (all configurations)",
    ]
    for row in saved:
        lines.append(f"   {row['run_id']:<55} {_eur(row['operating_result_cents']):>14}  "
                     f"lost {row['lost_sales']}")
    lines += ["", "Running the same command again replaces these runs (same run_id) and",
              "overwrites the files in the output folder; it never appends duplicates."]
    return "\n".join(lines) + "\n"


def _storage_comparison(shop_rows: list[Mapping], product_rows: list[Mapping]) -> list[str]:
    lines = []
    margin_rule_lost_more = True
    policies = sorted({row["policy"] for row in shop_rows})
    for policy in policies:
        runs = [row for row in shop_rows if row["policy"] == policy]
        lines.append(f"{policy}:")
        for row in runs:
            worst = max(
                (p for p in product_rows if p["run_id"] == row["run_id"]),
                key=lambda p: p["lost_sales"],
            )
            lines.append(
                f"   {row['allocation_rule']:<23} operating {_eur(row['operating_result_cents'])}, "
                f"lost {row['lost_sales']} units (most: {worst['product_id']}, "
                f"{worst['lost_sales']})"
            )
        best = max(runs, key=lambda row: row["operating_result_cents"])
        worst_run = min(runs, key=lambda row: row["operating_result_cents"])
        gap = best["operating_result_cents"] - worst_run["operating_result_cents"]
        lines.append(f"   -> {best['allocation_rule']} is better by {_eur(gap)}.")
        lost = {row["allocation_rule"]: row["lost_sales"] for row in runs}
        if lost.get("unit_margin_descending", 0) <= lost.get("product_id_ascending", 0):
            margin_rule_lost_more = False
    if margin_rule_lost_more:
        lines += [
            "Giving space to the highest unit margin first favours expensive, slow-moving",
            "products. When space is short, the cheap high-volume products lose sales instead,",
            "and their many small margins add up to more than the few large ones.",
        ]
    return lines


def _recommendation(shop_rows: list[Mapping], policies: dict) -> list[str]:
    ranked = sorted(shop_rows, key=lambda row: row["operating_result_cents"], reverse=True)
    best = ranked[0]
    lines = [
        f"Use {policies[best['policy']]}"
        + ("" if best["allocation_rule"] == "unlimited"
           else f" with the {best['allocation_rule']} rule") + ".",
        f"It had the highest operating result, {_eur(best['operating_result_cents'])}, "
        f"with {_rate(best['fulfilment_rate'])} of demand served and "
        f"{best['lost_sales']} units lost.",
    ]
    if len(ranked) > 1:
        runner_up = ranked[1]
        gap = best["operating_result_cents"] - runner_up["operating_result_cents"]
        lines.append(
            f"The next best, {runner_up['policy']} / {runner_up['allocation_rule']}, "
            f"made {_eur(gap)} less."
        )
        if gap < 0.01 * abs(best["operating_result_cents"]):
            lines.append(
                "That gap is under 1% of the operating result, so on one seed the two are "
                "practically tied; we would test more seeds before choosing between them."
            )
    lines.append("This is a result for this simulated demand, not a forecast.")
    return lines
