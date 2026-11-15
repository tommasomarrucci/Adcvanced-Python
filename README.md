# Inventory and Profitability Simulator

Python 3.11+ CLI application for analysing historical sales and simulating inventory replenishment. The submitted extension is the storage capacity experiment. It compares product-ID order with descending unit-margin order; both policies receive the same seeded demand array.

## Setup and commands

Install NumPy in a virtual environment (tested target: NumPy 2.x):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install numpy
```

Run commands from the project root. Configuration paths are resolved relative to the TOML file.

```sh
python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml init
python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml import
python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml summary
python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml run
python -m inventory_simulator --config inventory_student_sample_files/config/storage.toml best-sellers 2026-01-01 2026-03-31
```

`import` validates the catalogue and a complete, consecutive sales history before committing. Repeated imports insert no duplicate sales. If an existing product ID is imported again, its catalogue fields are updated; existing sales with the same date/product key are retained. A failed validation is written to `results/storage/validation_report.txt` and prevents the import. `run` replaces the database records for the same scenario IDs and overwrites the output CSVs and report.

Use `core.toml` for the unlimited-storage core comparison. The supplied `promotion.toml` and `policy_tuning.toml` are examples for alternative extensions; this delivered program validates that only core or storage is selected.

## Inputs and outputs

The supplied catalogue uses `product_id,name,category,purchase_cost,selling_price,initial_stock`. Sales use `date,product_id,units_sold`; dates are ISO `YYYY-MM-DD`, money is EUR, and quantities are non-negative integers. Costs and prices are positive. The sample covers 90 consecutive days and 8 products.

The configured output directory receives `historical_summary.csv`, `daily_simulation.csv`, shop-level `policy_comparison.csv`, `product_comparison.csv`, `validation_report.txt`, and `report.txt`. SQLite stores products, historical records, simulation runs, and daily results. The SQL summary commands include sales/revenue by product, category revenue via a join, date-window best sellers, and saved simulation runs.

## Model conventions

The historical window supplies each product's mean daily demand. NumPy's `default_rng(seed)` generates a day-by-product Poisson array once; the same array is reused for every policy and allocation rule. Sales are the minimum of demand and available stock, unmet demand is permanently lost, and holding cost applies to end-of-day stock. A one-day replenishment lead time means orders placed after a day arrive at the next day's start. The final day's order cost is included and its quantity is reported as outstanding, separately from on-hand inventory. Final inventory value is reported separately and is not deducted as cost of goods sold.

Storage capacity is checked against initial stock and before each order. Remaining capacity is allocated product by product, up to requested quantity. Unit margin is selling price less purchase cost; ties use ascending product ID. The two allocation rules are `product_id_ascending` and `unit_margin_descending`.

Run the automated checks with `python -m unittest discover -s tests`.
