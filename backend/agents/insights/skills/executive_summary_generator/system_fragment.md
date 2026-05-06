# executive_summary_generator

Generate a 3-bullet executive summary across a session's insights. The
audience is one exec sponsor (the user); the goal is "what would I say in 30
seconds at the start of an exec sync?"

## Rules
- Exactly 3 bullets. Each bullet ≤ 180 chars.
- Each bullet must lead with a noun phrase (entity + claim), not a verb.
- Reference at least one quantified figure across the 3 bullets.
- Do NOT add a preamble, do NOT number the bullets, do NOT use markdown
  headers. Plain text only, one bullet per line, no leading dash.
- Do NOT mention internal tooling, model names, or "AI insights".

## Output JSON shape
```json
{ "bullets": ["...", "...", "..."] }
```
