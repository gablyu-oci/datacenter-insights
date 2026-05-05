# insight_synthesis

Turn a verified hypothesis + supporting rows into a one-sentence headline +
short body. This is the skill that decides what an insight *says*.

## Rules
- Headline ≤ 120 chars; declarative; names entities + a quantity.
  GOOD: "Oracle's contracted renewable share (86%) is 3× hyperscaler median."
  BAD:  "Oracle is doing a lot of renewables." (no number, no comparison)
- Body ≤ 500 chars; one paragraph; cites the supporting numbers with units.
- Do NOT speculate beyond the rows you were given.
- Do NOT mention the model, the tool stack, or that you are an AI.
- If supporting rows are too thin (< 3 rows), set `confidence_signal=weak`
  and lead the body with the row count caveat.

## Output JSON shape (return ONLY this; no surrounding prose)
```json
{
  "headline": "...",
  "body": "...",
  "confidence_signal": "weak|moderate|strong"
}
```
