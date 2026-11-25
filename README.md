# Inventory and Profitability Simulator

A command-line program for a small fictional shop. It checks and imports the product
catalogue and 90 days of sales into SQLite, summarises the history with SQL, simulates
60 days of future demand with NumPy and compares two replenishment policies.

Our extension is **B, storage constraint**: total stock is limited to 300 units, and we
compare two rules for sharing the free space between product orders.

## Requirements

- Python 3.11 or newer (we use `tomllib`). Tested with Python 3.14.7.
- NumPy (tested with 2.5.4; anything from 1.26 works). Everything else is the standard library.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Reproducing the submitted results

Run from the project folder. The configuration file decides every path and parameter;
relative paths inside it are resolved from the folder the TOML file is in.

```sh
CONFIG=inventory_student_sample_files/config/storage.toml

python -m inventory_simulator --config $CONFIG init      # create the database tables
python -m inventory_simulator --config $CONFIG import    # validate + import the CSV files
python -m inventory_simulator --config $CONFIG summary   # historical SQL summaries
python -m inventory_simulator --config $CONFIG best-sellers 2026-01-01 2026-01-31
python -m inventory_simulator --config $CONFIG run       # simulate and write all outputs
python -m inventory_simulator --config $CONFIG runs      # list saved simulation runs
```

`run` on its own is enough: it validates and imports the data again (which is safe,
see below) before simulating. The results land in
`inventory_student_sample_files/results/storage/` and the database in
`inventory_student_sample_files/working/inventory.sqlite`. With the same files,
configuration and seed, the numbers are identical on every run.

For the core comparison without the storage limit use `config/core.toml`. The
`promotion.toml` and `policy_tuning.toml` files belong to the extensions we did not
choose; the program rejects them with a clear message.

Exit codes: 0 success, 1 invalid input data or a file/database error, 2 invalid configuration
or a command line that cannot be understood. `--help` lists the commands.

## Commands

| Command | What it does |
|---|---|
| `init` | Creates the database file and its four tables if they do not exist. |
| `import` | Validates both CSV files, writes `validation_report.txt`, and imports them only if there are no problems. |
| `summary` | Writes `historical_summary.csv` (per product and per category) and prints revenue by category. |
| `best-sellers START END [--limit N]` | Products ranked by units sold between two dates, both included. |
| `run` | Import, simulate every policy and allocation rule on the same demand, save to SQLite, write every output file. |
| `runs` | Summary of every simulation run saved in the database. |

## Input files

All CSV files are UTF-8 with a header row; dates are `YYYY-MM-DD`.

`products.csv`: `product_id,name,category,purchase_cost,selling_price,initial_stock`
- `product_id` is text and unique. Costs and prices are positive euro amounts with at
  most two decimals and no currency symbol. `initial_stock` is a whole number >= 0 and
  means stock at the start of the *simulation*.

`historical_sales.csv`: `date,product_id,units_sold`
- One row for every product on every day, zeros included, for at least 30 consecutive
  days. A missing row is an error, not a zero. `units_sold` is a whole number >= 0.

Invalid data stops the import and the simulation. Every problem goes into
`validation_report.txt` with the file and row number. The `validation/` folder holds the
supplied broken examples; the tests check that each one is rejected for the right reason.

## Repeated imports and runs

- Importing the same files again adds nothing: a sales row already stored with the same
  value is skipped. Products already in the database are updated to the values in the file.
- If a sales row is already stored with a **different** quantity, the import is refused
  and the conflict is listed in the validation report. History is not overwritten
  silently; delete the database file to start again from different data.
- Every run has a readable id, for example
  `storage-seed2026-order_up_to-unit_margin_descending`. Running again with the same
  configuration and seed **replaces** those runs in the database and **overwrites** the
  output files. Changing the seed or using another config file creates new runs.

## Output files

| File | Content |
|---|---|
| `historical_summary.csv` | Units, mean daily units, revenue, cost of goods sold and gross profit per product, plus per category. |
| `daily_simulation.csv` | One row per run, day and product: stock at start and end, demand, sales, lost sales, order, and money. |
| `policy_comparison.csv` | One row per policy and allocation rule for the whole shop, with fulfilment rate, final stock, final inventory value, outstanding orders and the gap to the best scenario. |
| `product_comparison.csv` | The same measures per product. |
| `validation_report.txt` | PASSED or FAILED, the checks performed, and every problem found. |
| `report.txt` | Policy and storage-rule comparison, recommendation, assumptions and limitations. |

Money columns end in `_eur` and have exactly two decimals. Fulfilment rate is
units sold / demand, rounded to 4 decimals, and `n/a` when demand is zero.
Mean daily units are rounded to 8 decimals.

## Tests

```sh
python -m tests.run_tests
```

Each test is a plain function that uses `assert`, as in the course exercises; the
script runs them all and prints `ok` or `FAIL` for each. A single file can be run on its
own too, for example `python -m tests.test_simulation`.

58 tests: a 4-day example calculated by hand, stock conservation, non-negative stock,
the next-morning arrival of orders, storage capacity on every day and at its boundary,
reproducibility, every invalid sample file, invalid configurations, repeated and
conflicting imports, a product with no demand, and agreement between the SQL totals and
the NumPy engine, and the parsing of the command line. The tests use temporary folders and
never touch the submitted database.
