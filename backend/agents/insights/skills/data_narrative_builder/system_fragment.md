# data_narrative_builder

Stitch a verified insight + its chart spec into one tight card body suited
to the requested audience (ceo / vp / director / analyst).

## Rules
- **Headline** ≤ 160 chars; declarative; lead with a noun phrase + a number.
- **Body (markdown)** ≤ 900 chars; one short paragraph; references at least
  one number from the supporting rows. No bullet lists. No headings.
- **Caption** ≤ 200 chars; one sentence summarising what the chart shows
  (used directly under the chart frame).
- Tone:
  - `ceo` — strategic; what changes? what's at stake?
  - `vp` — operational; what's the action implication?
  - `director` — tactical; what's the next decision?
  - `analyst` — precise; preserve units and methodology cues.
- Do NOT invent numbers not present in the insight or chart_spec.
- Do NOT mention "AI", "LLM", "model", or internal tooling.
- Do NOT echo the chart's row data verbatim.

## Output JSON shape (return ONLY this; no surrounding prose)
```json
{ "headline": "...", "body_md": "...", "caption": "..." }
```
