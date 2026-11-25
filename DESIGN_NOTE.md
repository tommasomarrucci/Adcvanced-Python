# Design note

## Architecture

Each module does one job, and only `cli.py` knows about the command line.

```
cli.py         parse arguments, call the workflow, print, choose the exit code
workflow.py    the steps of each command: validate -> import -> simulate -> save -> export
config.py      read the TOML file, check every section, key, type and value -> Settings
validation.py  read the CSV files and check them -> records + list of problems (no database)
database.py    SQLite schema, import, saving runs, and every SQL summary
policies.py    ReplenishmentPolicy and its two subclasses
simulation.py  Catalogue, Poisson demand, storage allocation and the daily engine (NumPy)
reporting.py   CSV writing, validation_report.txt and report.txt
money.py       euro <-> integer cents
```

Data flows one way: `config` -> `validation` -> `database` -> `simulation` ->
`database` -> `reporting`. The simulation never reads files or the database, so the
tests can give it a hand-made demand array and check the result by hand.

## The meaningful design decision: one demand array, whole-array simulation

`generate_demand` draws the full (60 days x 8 products) Poisson array once with
`np.random.default_rng(seed)`. Every policy and allocation rule runs on that same array,
so a difference in results can only come from the ordering decisions, not from luck.

The engine loops over days, because today's stock depends on yesterday's orders, but
each day handles all products at once with NumPy: `np.minimum(demand[day], stock)` for
sales and the policy's `np.where` mask for orders. Money is worked out after the loop on
whole arrays with broadcasting: `units_sold * price_cents` multiplies a (60, 8) array by
a vector of 8 prices. Totals per product and per scenario are then computed in SQL.

## Inheritance

`ReplenishmentPolicy` holds the threshold and the shared rule "order only when stock is
strictly below the threshold" (`needs_order`). Its `order_quantities` raises
`NotImplementedError`. The two subclasses call `super().__init__` and override only the
part that really differs, how much to order:

- `FixedQuantityPolicy`: `np.where(needs_order, quantity, 0)`
- `OrderUpToPolicy`: `np.where(needs_order, target - stock, 0)`

The engine calls `policy.order_quantities(stock)` and never checks which class it has,
so the daily logic is written once. The constructors check their own parameters, and
`config.py` turns those errors into configuration errors. `ConfigError` itself
inherits from `ValueError`.

## Database

| Table | Primary key | Notes |
|---|---|---|
| `products` | `product_id` | prices and costs in cents, `CHECK` > 0; stock `CHECK` >= 0 |
| `historical_sales` | (`sale_date`, `product_id`) | foreign key to products; the key makes duplicate imports impossible |
| `simulation_runs` | `run_id` | policy and its parameters, allocation rule, capacity, seed, days, RNG method, NumPy version, the full effective configuration as JSON |
| `daily_results` | (`run_id`, `day`, `product_id`) | foreign keys to both tables, `ON DELETE CASCADE` from runs; `CHECK (units_sold + lost_sales = demand)` and `CHECK (stock_end = stock_start - units_sold)` |

All values go through `?` or `:name` parameters. Imports and the saving of a whole
comparison each run in a single transaction (`with connection:`), so a failure leaves
nothing half-written. Connections are closed with `contextlib.closing`. The required
summaries are SQL queries: units and revenue by product, revenue by category (JOIN),
best sellers in a date range (parameterised `BETWEEN`), saved runs, and the shop- and
product-level results (`GROUP BY` over `daily_results`).

## Choice of Python types

- **Integer cents** for every amount: sums are exact, so a total never comes out as
  5517.699999999999. Input is converted with `Decimal`, which also rejects amounts like
  1.234. Euros appear only in output, always with two decimals.
- **Named tuples** (`ProductRecord`, `SaleRecord`, `Settings`) for fixed records: they
  are immutable and are already tuples, so `executemany` can insert them directly.
- **Sets** wherever uniqueness matters: seen product ids, (date, product) pairs, and
  missing or unknown config keys (`table.keys() - expected`).
- **Dictionaries** for keyed lookups: the first row of each (date, product) pair, the
  stored quantities when looking for conflicts, and the command name -> function table
  in the CLI.
- **Lists** keep product order fixed, so position i means the same product in every array.
- **NumPy arrays** for everything (days x products) in the simulation.

## Modelling assumptions

- Historical sales equal demand: the shop had no stockouts in the past.
- Mean daily demand per product is the average over the whole 90-day window (the same
  window for every product). Future demand is Poisson with that mean, independent across
  days and products. Poisson gives whole numbers >= 0 that vary around the average.
- Daily order: receive yesterday's orders, sell min(demand, stock), lose the rest for
  good, charge holding cost on end-of-day stock, then place orders for tomorrow morning.
- A fixed order cost is charged once per product with a positive order. Orders placed on
  the last day are charged and reported as outstanding, separate from on-hand stock.
- Final inventory value (final stock x purchase cost) is reported separately and never
  subtracted as cost of goods sold.
- Storage: one unit takes one storage unit. Initial stock above capacity is rejected.
  Before ordering, free space = capacity minus end-of-day stock, because all orders arrive
  together the next morning. Space goes to products in priority order, each getting up to
  its full request. Rules: `product_id_ascending` and `unit_margin_descending` (ties by
  product id).

## Limitations

- One seed and one 60-day path. The two best scenarios differ by EUR 4.52 (under 1%),
  so they are practically tied; more seeds would be needed to separate them.
- If there were stockouts in the past, the historical means underestimate demand.
- No trend, weekly pattern or seasonality, and no link between products.
- Historical revenue uses the current catalogue prices for the whole period.
- The greedy allocation never splits space in proportion to need; a product late in
  the priority order can get nothing on busy days.

## AI-use statement

> **Group: check this section and edit it so that it matches exactly what you did.**

We used ChatGPT to produce a first working version of the program, documentation and
presentation outline. We then compared it with the course material and the
specification, using Claude (Claude Code) to help review and restructure it. That review
found that NumPy was only used to draw random numbers while the simulation ran on Python
lists, that the per-product results were added up in Python instead of SQL, that
database connections were never closed, that the saved-runs summary was computed but
never shown, and that several required tests were missing.

Example of generated output we verified: after the simulation was rewritten to work on
whole arrays, we checked it in three ways. (1) A 4-day example worked out on paper
(operating result EUR 6.10 for fixed quantity, EUR 5.90 for order up to) is now a test.
(2) With the same seed, the new engine reproduces the old version's operating results
to the cent (EUR 2770.48, 2738.36, 2775.00 and 2710.84). (3) We deliberately broke the
code in four places (`<` changed to `<=`, orders never arriving, holding cost charged on
start-of-day stock, `INSERT OR IGNORE` changed to `INSERT OR REPLACE`) and confirmed that
the tests fail each time. Earlier, the group had corrected a generated defect where sales
were not carried forward into the next day's stock.

## Contribution statement

> **Group: fill this in with what each person actually wrote and reviewed.** Every
> member needs a substantive implementation part and a review of someone else's module.

| Member | Implemented | Reviewed |
|---|---|---|
| PIETRO NICOLAZZI | | |
| NICOLA RIZZUTO | | |
| MAIA TRUBIANO | | |
| TOMMASO MARRUCCI | | |
| HADRIEN RAYMOND JULIEN GIRAL--GHATTAS | | |

Shared design decisions: storage extension; integer cents; one shared demand array per
comparison; refuse conflicting re-imports rather than overwrite history; run ids that
are replaced on re-run instead of appended.
