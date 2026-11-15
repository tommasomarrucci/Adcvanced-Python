# Five-minute presentation outline

## 0:00-0:45 — Problem and extension
Explain the stockout-versus-inventory-cost trade-off and the storage-capacity experiment.

## 0:45-2:00 — Architecture and design
Trace CSV validation into SQLite, SQL historical summaries, shared policy interface, and the NumPy demand array. Explain that identical demand isolates policy/allocation differences.

## 2:00-4:00 — Demonstration and results
Run `init`, `import`, `summary`, and `run`. Show the generated comparison CSV and report. Explain operating result, fulfilment, lost sales, ending inventory, and outstanding final-day orders using the actual generated results.

## 4:00-5:00 — Limitations and lessons
Discuss the no-stockout historical-sales assumption, stationary Poisson demand, fixed one-day lead time, and one seeded scenario. Explain one design choice and how the group tested it.
