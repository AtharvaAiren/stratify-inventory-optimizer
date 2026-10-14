# Inventory Rewired

**A reproducible inventory-policy comparison for the Stratify retail case.**

The case has three stores, ten SKUs and daily demand histories. This implementation compares a static reorder policy with adaptive, weekday-aware replenishment over the original 21-day horizon. Both run through the same dated inventory ledger.

[Portfolio](https://github.com/AtharvaAiren) · [Source](inventory/model.py) · [Case report](reports/case-study/report.html) · [Tests](tests/test_inventory.py) · [Original submission](https://github.com/AtharvaAiren/stratify-inventory-rewired)

## Run it

Python 3.12 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m inventory --start 2024-03-20 --days 21 --output reports/case-study
python -m pytest
```

Open `reports/case-study/report.html` in a browser. The run also produces a daily ledger, store–SKU KPIs and a JSON summary with input hashes and cost assumptions. Outputs are overwritten only in the specified output directory.

## How decisions are made

1. Expire old lots and receive orders whose lead time has elapsed.
2. Fit demand estimates using dates **strictly before** the decision day.
3. Calculate the reorder point from expected lead-time demand and safety stock.
4. Compare stock plus outstanding orders with the reorder point; size a new order toward the target inventory position.
5. Serve the day's demand by first-expiring-first-out allocation and record lost sales.

The static policy fixes the initial demand mean, variation and replenishment cycle. The adaptive policy updates a rolling history, shrinks weekday estimates toward the global mean, and orders toward lead-time-plus-review-period coverage. Both cap orders by forecast demand over the new lot's usable life.

## What changed from the original implementation

| Original | Rebuilt implementation |
| --- | --- |
| Machine-specific workbook paths | CLI paths and bundled case inputs |
| Hard-coded weekday forecasts | Forecasts fitted from available history |
| One outstanding-order flag | Explicit dated order pipeline |
| Shelf life used only for order sizing | Lot expiry and FEFO consumption |
| Shared turnover denominator | Each policy's own average inventory |
| Spreadsheet outputs alone | Reconciled ledger, report, configuration and source hashes |

The tests check conservation, lead-time arrival, expiry, missing-data rejection, determinism and independence from future demand.

## Case results and assumptions

The checked March 20 replay achieves the same **97.98% fill rate** for both policies. The adaptive policy reduces estimated holding cost from **2,221.28 to 2,084.81**, while increasing ordering cost from **680 to 860** under the default assumptions. It does not establish an overall cost improvement; the report exposes that tradeoff.

- `data/` contains the supplied fictional retail case. `Demand` and date-specific opening stock come from the original prepared store–SKU workbook; SKU costs, lead times, shelf life and service levels come from the supplied master workbook.
- At the start, opening stock is assumed fresh and no prior orders are pending: batch ages and a store-level opening pipeline are unavailable.
- Holding cost uses a daily rate of 0.05% of inventory value; ordering costs 20 per order. Lost sales are valued at unit cost, not assumed selling prices or profits.
- The 21-day case has long shelf lives; expiry handling is exercised separately by the short-shelf-life tests.
- No purchase order is allocated to a store without a store identifier, and missing dates are rejected rather than treated as zero demand.

Change cost and policy assumptions through the typed `Config` object in `inventory/model.py`. A different date/horizon can be supplied through the CLI. The weekday estimator is transparent and does not claim to implement Holt–Winters.

## Repository map

```text
inventory/model.py    Forecasts, dated simulation, loading and KPIs
inventory/__main__.py CLI and HTML/CSV reporting
data/                Supplied case workbooks
reports/case-study/  Checked replay outputs
tests/               Numerical and temporal-integrity checks
```

This 2026 reimplementation follows Atharva Airen's original 2025 Stratify direction and was built with Codex assistance. It is not represented as the original competition submission or as a competition award.
