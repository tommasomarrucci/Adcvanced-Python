# Design note

The CLI delegates configuration, CSV validation, SQLite persistence, simulation, and reporting to separate modules. `Product` holds the simulation inputs. `ReplenishmentPolicy` defines a shared `requested_order` interface; `FixedQuantityPolicy` and `OrderUpToPolicy` implement the two required behaviours, leaving inventory event logic in one engine.

SQLite uses product IDs and date/product pairs as primary keys, foreign keys for relationships, check constraints for quantities and prices, parameterised date queries, and transaction-scoped imports and simulation persistence. NumPy handles a two-dimensional day-by-product Poisson demand array. Sets detect duplicate identifiers and date/product pairs during import; lists preserve deterministic product ordering; dictionaries carry named scenario and output fields.

Monetary input values are parsed as EUR floating-point values and CSV outputs round only for display where appropriate. Historical summaries use SQL aggregation. The model assumes historical sales equal demand, stationary independent Poisson demand, fixed prices/costs, permanent lost sales, and one-day lead time. The storage comparison evaluates one seeded 60-day scenario, so its recommendation is conditional on those assumptions and should not be interpreted as a forecast.

## AI-use statement

An AI assistant generated an initial application structure and implementation. The group must review and correct the code, verify the calculations and outputs against the handout and supplied expected historical summaries, and be able to explain all submitted work in the oral examination. Replace this paragraph with the group's actual tools, review process, and one concrete correction made before submission.

## Contribution statement

Complete this section with each member's substantive implementation contribution, code review, and shared design decisions. Every member should contribute to implementation and review another member's work.
