# Design note

The CLI delegates configuration, CSV validation, SQLite persistence, simulation, and reporting to separate modules. `Product` holds the simulation inputs. `ReplenishmentPolicy` defines a shared `requested_order` interface; `FixedQuantityPolicy` and `OrderUpToPolicy` implement the two required behaviours, leaving inventory event logic in one engine.

SQLite uses product IDs and date/product pairs as primary keys, foreign keys for relationships, check constraints for quantities and prices, parameterised date queries, and transaction-scoped imports and simulation persistence. NumPy handles a two-dimensional day-by-product Poisson demand array. Sets detect duplicate identifiers and date/product pairs during import; lists preserve deterministic product ordering; dictionaries carry named scenario and output fields.

Monetary input values are parsed as EUR floating-point values and CSV outputs round only for display where appropriate. Historical summaries use SQL aggregation. The model assumes historical sales equal demand, stationary independent Poisson demand, fixed prices/costs, permanent lost sales, and one-day lead time. The storage comparison evaluates one seeded 60-day scenario, so its recommendation is conditional on those assumptions and should not be interpreted as a forecast.

## AI-use statement

ChatGPT assisted with the application structure, implementation, documentation, and presentation outline. The generated code was run against the supplied data and checked with seven automated tests, including the provided expected historical summaries and invalid-input samples. During execution, the group corrected a simulation defect where sales were not carried forward into the next day's stock, and fixed repeat-run persistence to delete daily records before their parent run. The group should edit this statement to match its actual review and use of AI, and be prepared to explain and independently verify the submitted code.

## Contribution statement

| Member | Substantive implementation contribution | Review performed |
|---|---|---|
| PIETRO NICOLAZZI | To be completed by the group | To be completed by the group |
| NICOLA RIZZUTO | To be completed by the group | To be completed by the group |
| MAIA TRUBIANO | To be completed by the group | To be completed by the group |
| TOMMASO MARRUCCI | To be completed by the group | To be completed by the group |
| HADRIEN RAYMOND JULIEN GIRAL--GHATTAS | To be completed by the group | To be completed by the group |

Add shared design decisions below, and replace each placeholder with work that the named member actually completed. Do not claim contributions that did not occur. Every member should contribute to implementation and review another member's work.
