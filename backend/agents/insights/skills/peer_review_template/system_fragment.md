# peer_review_template (V2)

Defensive self-review of one candidate insight. You return strict JSON only.

## Rubric (PRD §5.1)

Score the candidate against four boolean criteria:
- `specific`: names entities (companies, states, sites, vendors) AND a quantity.
- `supported`: at least one row of evidence is implied by the chart_spec or
  citations; if neither shows quantitative backing, this is `false`.
- `non_trivial`: not directly visible as a tile on any of the 9 existing
  product tabs (Power, Permits, Triangulation, Companies, etc.). A claim
  like "Amazon has the most contracted GW" is trivial; "Amazon's top 5
  deals are all nuclear" is not.
- `material`: if true, this would change a strategy decision.

## Verdicts

- `pass`: 4 of 4 booleans true; ≥1 citation with agree/disagree (not just
  context) -- if citations were supplied at all.
- `revise`: 3 of 4 booleans true OR citations exist but are all context-only.
- `reject`: ≤2 of 4 booleans true.

## Output schema (JSON only, no prose, no markdown fence)

```
{
  "verdict": "pass" | "revise" | "reject",
  "checklist": {
    "specific": bool,
    "supported": bool,
    "non_trivial": bool,
    "material": bool
  },
  "suggestions": [string, ...]   // 0-5 short suggestions; empty list if pass
}
```

## Pitfalls

- Do not invent missing facts. Score `supported = false` when uncertain.
- Suggestions must be concrete (e.g., "name the state", "add the magnitude
  in GW"); never generic ("be more specific").
- This guidance applies to the NEXT assistant turn only.
