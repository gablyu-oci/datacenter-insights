# business_metrics_calculator

Compute well-known competitive-intel metrics deterministically from raw rows.
Closed registry of metric names; no free-form math. Use this when an insight
needs a canonical number (GW totals, renewable share, gap-vs-implied,
deals/quarter), not a one-off calculation.

## Registered metrics
- `gw_total` — sum of `contracted_gw` (or `gw`) over rows. Unit: GW.
- `contracted_renewable_share` — share of renewable contracted GW vs total
  contracted GW. Unit: pct (0..1).
- `gap_vs_implied` — sum(`contracted_gw`) − sum(`implied_gw`); positive
  means contracted exceeds implied demand. Unit: GW.
- `deals_per_quarter` — count of rows grouped by `quarter` (YYYYQn). Returns
  the breakdown plus a single value = mean per active quarter. Unit: count.

## Inputs
- `metric_name`: one of the registered metrics above
- `rows`: input row set
- `filters` (optional): per-column equality predicate (string or list)
  applied before computation.

## Outputs
- `value`: scalar
- `unit`: `"GW" | "MW" | "USD" | "count" | "pct"`
- `breakdown`: optional ordered list of `{key, value}` (e.g. per-quarter
  for `deals_per_quarter`)
- `inputs_seen`: int — how many rows survived filtering and contributed
- `notes`: caveats applied (e.g. ignored non-numeric values)

## Rules
- Reject unknown metric names with `unknown_metric` error.
- All numeric coercion via float(); booleans excluded.
- Empty input ⇒ value=0.0 and a note.
