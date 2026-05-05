[skill: time_series_analysis — guidance for the next assistant turn]

You are now operating with `time_series_analysis` guidance. The
preprocessing JSON contains trend direction, seasonality assessment,
and anomaly indices computed via z-score (default threshold 3sigma).

Process:
1. State trend direction (up/down/flat) and how confident you are.
2. State seasonality if detected; otherwise say "no clear seasonality".
3. Reference anomaly indices by their date, not numeric position.
4. Do NOT forecast unless explicitly asked — V1 PRD non-goal.

Common pitfalls (do not):
- Do not chase noise: 1–2 anomalies in a 30-point series is not a trend.
- Do not interpret a level shift as seasonality.

This guidance applies to the NEXT assistant turn only.
