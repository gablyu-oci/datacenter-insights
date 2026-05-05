# segmentation_analysis

Cut a row set by a categorical field and report per-segment metrics + outlier
segments. Use this when the question is "how does X vary by Y?" — by
hyperscaler, by state, by deal_type (nuclear vs renewable), by lifecycle
stage. Pure descriptive analytics; no causal claims.

## Inputs
- `rows`: list of dicts (≤ 10000)
- `group_by`: column name to segment on (categorical)
- `metric_field`: numeric column to aggregate (sum/avg) or `null` if `agg=count`
- `agg`: one of `"sum"`, `"avg"`, `"count"`
- `min_segment_size`: drop segments with fewer rows (default 1)

## Outputs
- `segments`: list of `{name, n_rows, value, share_of_total}` sorted by value desc
- `outlier_segments`: subset where the per-segment value is more than
  ±2 stdev from the cross-segment mean (z>|2|). Flagged with `z_score`.
- `total_value`: scalar; total sum of the metric (or total row count for `count`)
- `notes`: string list of any caveats applied (dropped segments etc.)

## Rules
- Skip rows where `group_by` is null.
- For `agg=avg`, weight is unweighted mean per segment; the `total_value`
  is the simple weighted sum / total count, NOT the mean of segment means.
- If `metric_field` is missing on a row, ignore that row for `sum`/`avg`.
- Cap output to top 50 segments by `n_rows` (drop tail to "other" group).
