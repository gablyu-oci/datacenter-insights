# impact_quantification

Convert a qualitative claim into a quantitative magnitude with a defensible
range, grounded *only* in the supporting rows you were given.

## Rules
- `impact_value` is the central estimate.
- `range_lo` ≤ `impact_value` ≤ `range_hi`.
- Use the supplied `unit` verbatim as `impact_unit`.
- `basis` (≤ 600 chars) names the columns / calculations behind the
  estimate (e.g. "sum of `contracted_gw` across rows where `vendor='nvidia'`").
- If the rows do not support a numeric estimate, return `impact_value=0`
  with `range_lo=range_hi=0` and a `basis` explaining the gap. Do NOT
  invent a number.
- Do NOT extrapolate beyond the rows.

## Output JSON shape (return ONLY this; no surrounding prose)
```json
{
  "impact_value": 0.0,
  "impact_unit": "GW",
  "range_lo": 0.0,
  "range_hi": 0.0,
  "basis": "..."
}
```
