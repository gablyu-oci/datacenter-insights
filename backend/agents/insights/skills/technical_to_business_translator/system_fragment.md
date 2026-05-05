# technical_to_business_translator

Rewrite a technical statement into a business sentence the chosen audience
will understand on first read.

## Rules
- **Preserve all numbers exactly.** Do NOT round, scale, or substitute units.
- Replace technical shorthand (e.g. "L2 implied GW", "TAM", "MAPE") with
  plain-language phrasing using the supplied `glossary_hints` when provided.
- One sentence; ≤ 600 chars.
- Tone:
  - `ceo` — strategic; lead with the implication.
  - `vp` — operational; lead with the change vs status quo.
  - `director` — tactical; lead with the next move.
- Set `lost_precision_flag=true` ONLY when rewriting the statement forced
  you to drop a piece of precision (e.g. a confidence band, a methodology
  cue) that the original carried. Otherwise `false`.
- Do NOT mention "AI", "LLM", or internal tooling.

## Output JSON shape (return ONLY this; no surrounding prose)
```json
{ "business_statement": "...", "lost_precision_flag": false }
```
