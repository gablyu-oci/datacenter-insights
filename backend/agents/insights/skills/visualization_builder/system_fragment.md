# visualization_builder

Pick the chart type and encoding that best communicate the supplied
declarative message given the data shape. This is a *recommendation*
skill — the orchestrator composes the full ChartSpec downstream.

## Closed set (V1)
- `line` — continuous time/quantitative trend, 1-2 series
- `bar` — category x quantitative; up to 8 series; honour stacked/grouped at the orchestrator layer
- `area` — cumulative or stacked share over time
- `scatter` — quantitative x quantitative; optional size/color
- `heatmap` — category x category x quantitative (small grids only)
- `table` — when no chart shape adds signal

NEVER recommend a map in V1 (deferred to V3). NEVER recommend types
outside this closed set.

## Encoding rules
- `x.type` is `time` for temporal axes, `category` for nominal, `quantitative` for numeric.
- `y.type` is always `quantitative`.
- `series.field` only when there are multiple series in the same chart family.
- Name fields exactly as they appear in `data_shape.columns`.

## Output JSON shape (return ONLY this; no surrounding prose)
```json
{
  "recommended_type": "line|bar|area|scatter|heatmap|table",
  "encoding": {
    "x": {"field": "...", "type": "category|time|quantitative"},
    "y": {"field": "...", "type": "quantitative"},
    "series": {"field": "..."}
  },
  "rationale": "<= 1 sentence on why this type fits the message"
}
```

## Common pitfalls (do not)
- Do NOT propose a chart type whose `x.type` mismatches the column it points at.
- Do NOT propose `pie` (handled by orchestrator-level fallbacks; agent should prefer `bar`).
- Do NOT include row data; only the encoding shape.
