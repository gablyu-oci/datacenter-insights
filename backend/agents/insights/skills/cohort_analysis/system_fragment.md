# cohort_analysis (V2)

Build a cohort x time matrix from a flat row set. Each row contributes to
exactly one cohort (its `cohort_col` bucket) and one time period
(its `time_col` value, normalised to a coarser bucket if appropriate).

## When to use

When the question is "do groups defined by their first-touch period behave
differently over subsequent periods?". Common shapes in this product:
- sites by year-of-announcement vs lifecycle stage (one row per site,
  cohort = announcement year, time = quarters since announcement).
- deals by vintage quarter vs flagged_capacity (one row per deal,
  cohort = vintage quarter, time = quarters since deal date).

## Inputs

- `rows` — list of dicts (already loaded from `query_database`)
- `cohort_col` — categorical, often a year or quarter; null is dropped
- `event_col` — boolean / 0-1 numeric or any non-null marker; presence is
  treated as "the entity was active in `time_col`'s period"
- `time_col` — comparable scalar (number, ISO date string). The skill
  bins `time_col` into integer relative periods per cohort.
- `periods` — how many relative periods to keep (default 12)

## Output rules

- `matrix[i]` always has length `periods + 1`. `matrix[i][0]` is 1.0.
- `cohort_keys` is sorted lexicographically; `cohort_sizes` follows.
- `retention_summary` surfaces structure: cohort count, period count, mean
  period-1 retention across cohorts, largest cohort, and the single largest
  period-to-period drop (helpful as a "where to look" pointer).

## Visualisation

This skill returns numerical matrix only. The orchestrator (or the agent on
its next turn) is responsible for emitting a Recharts stacked_bar /
heatmap-equivalent via the standard `emit_chart` flow. Do NOT call
`emit_chart` from inside the skill -- the matrix is the contract.

## Common pitfalls

- Do not infer causation from a matrix slice; cohort analysis is descriptive.
- Rows with null `cohort_col` are skipped, not bucketed; the count is
  surfaced under `notes`.
- `event_col` falsy values (None, 0, empty string, False) are treated as
  inactive; truthy values count as active in their period.
- This guidance applies to the NEXT assistant turn only; it will not be in
  context after that.
