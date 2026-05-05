[skill: programmatic_eda — guidance for the next assistant turn]

You are now operating with `programmatic_eda` guidance. Use the
deterministic preprocessing JSON the tool just returned to interpret
the frame. The preprocessing already computed dtypes, null density,
distinct counts, and basic per-column stats.

Process:
1. Confirm grain. The frame represents one row per <grain>; if the
   `grain` is unclear, ask a follow-up internally before drawing
   conclusions.
2. Null profile. Columns with null density above 30% are flagged
   unreliable. Above 50% they are not usable for ranking.
3. Outliers. Treat values >3sigma from the mean as outliers; distinguish
   real signal (e.g., one hyperscaler dwarfing the rest) from data
   error (negative GW, future-dated permits) using business context.
4. Distributions. Use mean+median together; if `|skew_flag|=true`,
   the median is the right summary statistic, not the mean.
5. Correlations. |r|>0.8 is flagged as redundant — pick the column
   closer to the business question.
6. Output rules: return the `ProgrammaticEdaOutputs` schema; do NOT
   fabricate stats not present in the preprocessing JSON.

Common pitfalls (do not):
- Do not interpret zero-variance columns as "stable"; they are usually
  load-bearing constants you should drop from analysis.
- Do not treat high cardinality as a quality issue on ID columns.
- Do not impute missing values silently — flag them in `top_issues`.

This guidance applies to the NEXT assistant turn only.
