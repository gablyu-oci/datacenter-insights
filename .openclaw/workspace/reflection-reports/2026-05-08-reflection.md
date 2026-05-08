1) Executive summary
- Biggest improvement: I tightened evidence discipline by grounding more of my analysis in local docs, schema notes, and prior successful tool behavior instead of trying to reason past tool friction.
- Biggest failure pattern: I still lose time when I treat tool-contract errors like data problems. The recurring risk is improvising placeholder IDs or incomplete structured payloads instead of re-checking the contract first.
- Product understanding improved in useful ways: cron isolated jobs are fresh-session runs; `query_database` is AST-gated, read-only, single-statement, capped at 10k rows with a 5s timeout; and several schema gotchas materially change what claims are safe.
- Communication improved when I used answer-first, executive-style structure: conclusion first, grouped support second, implication third.
- Durable lesson updated to memory: tool-validation failures are a hard stop for contract review, not a cue to guess.

2) Product/data learned
- From `SCHEMA.md`:
  - `query_database` only allows one `SELECT`-root statement, enforces read-only access, auto-clamps `LIMIT` to 10,000, and runs with a 5-second timeout.
  - `generator_permits.parent_company` is not a real column; parent rollups must join via `resolved_company_id -> companies`.
  - `events.event_date` can contain future junk values, so “recent” event work should clamp to `<= CURRENT_DATE`.
  - Many lifecycle fields in `sites` are stored as `varchar`, not proper dates.
  - `sites.power_capacity_mw` is the canonical site MW field.
  - `sites.provider_name = 'Company Not Disclosed'` should be excluded from operator rankings.
  - Some tables that look useful are effectively empty/stale (`anomalies`, `agent_tool_call`, `skill_invocation`, `skill_reference`, `transcript_metrics`), so I should not imply active coverage there.
- From `AI_INSIGHTS_PLAYBOOK.md` and preflight docs:
  - The required analytical sequence is question -> hypothesis -> MECE structure -> evidence pull -> alternative explanations -> quantification -> OCI implication -> confidence split.
  - The anti-hallucination standard is explicit: no invented MW, $, dates, row IDs, sources, or implied database support.
  - Inference is encouraged for analytical interpretation, but never for SQL identifiers.
- From workspace query/schema discipline docs:
  - `SCHEMA.md` and `QUERIES.md` should be treated as first stops before custom SQL.
  - If a needed column is not documented, the correct move is to narrow the claim, use a different supported field, or switch source type—not guess.
- From OpenClaw docs:
  - Cron jobs persist in Gateway state; isolated cron runs use fresh sessions and are best for background reports like this one.
  - The workspace is the default cwd but not a hard sandbox unless sandboxing is enabled.
  - `memory_search` is hybrid retrieval and still useful even when embeddings are degraded.

3) Mistakes corrected or near-errors
- Mistake: I previously used invalid/guessed `insight_id` values with OCI Insights tools.
  - Supported by yesterday’s reflection archive and prior transcript patterns.
  - Correction now reinforced: use the documented contract or prior successful pattern only; if unavailable, report the blocker plainly.
- Mistake: I previously called `oci-insights__propose_qa_chart` without a complete payload.
  - Correction: treat schema-bound tools like APIs with required fields, not shorthand prompts.
- Near-error today: web research was allowed, but the configured `web_search` tool was unavailable because SearXNG base URL was not configured.
  - Correction: I did not fabricate external learning; I fell back to local docs and existing workspace evidence.
- Near-error: memory search for “recent work mistakes” returned mostly dream/reflection artifacts, which is weak evidence for operational review.
  - Correction: prefer local archived reflections, workspace operating docs, and explicit session/tool evidence over semantically nearby but low-signal memory hits.
- Process weakness: I still need to check structured-tool contracts earlier instead of after the first validation failure.

4) New communication/presentation technique learned
- Technique: use a 3-layer executive answer structure for analytical replies:
  1. Direct answer in one sentence.
  2. Two to three grouped supporting facts.
  3. Explicit implication / “so what for OCI”.
- Why it matters:
  - It matches the workspace playbook’s requirement to lead with the answer and group reasons.
  - It reduces rambling process narration and makes caveats easier to place without burying the point.
- Practical rule for tomorrow:
  - If the first paragraph does not already answer the question, rewrite it.

5) Anti-hallucination rule changes
- Rule change: treat tool-argument validation failures as evidence boundaries, not temporary annoyances. No placeholder IDs, no guessed fields, no speculative substitute claims.
- Rule change: when a source/tool is unavailable, state the exact missing support and continue only with what remains grounded.
- Rule change: distinguish platform coverage from market truth. If a table/feed is sparse, stale, or geographically limited, say that explicitly before drawing broad conclusions.
- Rule change: when local docs document a known gotcha, surface that gotcha in the analysis if it could change the answer.
- Rule change: for nightly reflections, prefer concrete artifacts in this order: local archived reflections, workspace operating docs, schema/query docs, then optional web research if the tool is actually working.

6) Habits to improve tomorrow
- Start by checking canonical local docs (`SCHEMA.md`, `QUERIES.md`, playbook/checklists) before custom analysis or structured tool use.
- Verify required parameters before the first call to any schema-bound tool.
- Keep claims tagged mentally as one of three classes: tool-supported, doc-supported, or inference.
- Lead with the answer faster; push caveats down unless they materially reverse the conclusion.
- Be explicit about why something is uncertain: tool outage, sparse coverage, stale table, or unresolved entity mapping.
- Keep memory updates sparse and durable; only store repeat failures or stable operating lessons.
