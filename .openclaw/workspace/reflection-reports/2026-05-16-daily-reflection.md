1) Executive summary
- The biggest improvement opportunity is still preflight discipline: verify schema, table grain, and tool contracts before analysis, not after the first error.
- The strongest recurring lesson is to keep a clean boundary between tool-backed fact, source-backed fact, labeled inference, and OCI implication.
- Product understanding improved around warehouse caveats that directly affect analysis quality: `events` is the milestone system of record, `sites.power_capacity_mw` is the canonical MW field, and several plausible-but-wrong columns remain a live trap.
- Communication remains strongest when written answer-first: conclusion, 2–3 grouped supports, then the OCI consequence.

2) Product/data learned
- Re-confirmed from `SCHEMA.md` and `QUERIES.md`:
  - `sites.power_capacity_mw` is the canonical datacenter MW column.
  - `events` is the source of truth for milestone timing; deprecated lifecycle dates on `sites` should not be used for historical cuts.
  - `events.event_date` can include projected future milestones, so historical analysis should clamp to `CURRENT_DATE`.
  - `pct_construction` is a 0–1 fraction, not a 0–100 percentage.
  - `generator_permits.parent_company` is not a real column; parent rollups must use `resolved_company_id -> companies`.
  - `sites.end_user_companies` is a comma-separated string with sentinel “no customer” values.
- Re-confirmed from local docs:
  - `query_database` is single-statement, read-only, auto-limited, and time-constrained; narrow schema-aware SQL is mandatory.
  - Skills are loaded with precedence and allowlist gating; they should not be assumed from memory alone.
  - Sub-agents are isolated by default and completion is push-based, so polling loops are the wrong operating pattern.
  - Transcript hygiene is provider-specific and largely runtime-side; stored transcript shape and provider replay shape are not always identical.
- `FRESHNESS.md` is intentionally incomplete and should not block analysis; direct schema-aware drills are the fallback.

3) Mistakes corrected or near-errors
- Recurring corrected mistake: waiting for a query or tool error before checking the contract. Better practice is to read `SCHEMA.md`, `QUERIES.md`, and relevant tool docs first.
- Recurring near-error: letting plausible entity attribution outrun evidence, especially for unnamed end users, shell LLCs, and indirect company mapping.
- Recurring near-error: describing tools or platform behavior from memory instead of documentation.
- Positive correction: when docs are checked first, ambiguity collapses quickly and the analysis becomes both faster and safer.

4) New communication/presentation technique learned
- Reinforced technique from light web research: Pyramid Principle / answer-first communication remains the best fit for executive analytical writing.
- Practical version to keep using: state the answer first, support it with 2–3 grouped reasons, then show evidence.
- Useful refinement for analyst work: explicitly separate known facts, inference, and implication so concise writing does not smuggle in unsupported certainty.

5) Anti-hallucination rule changes
- Before unfamiliar analysis, run a short preflight: verify table grain, canonical metric column, date semantics, sentinel/null handling, and tool contract from docs.
- Never infer SQL identifiers from memory or from similar databases; use only schema-confirmed names.
- If an entity is not directly named in warehouse fields or cited documents, present it as a hypothesis, not an attribution.
- If tool behavior matters to the answer, verify it from local docs before stating it.
- Force each important sentence into one bucket: tool-backed fact, source-backed fact, or labeled inference. If it fits none, cut or rewrite it.

6) Habits to improve tomorrow
- Start each unfamiliar analysis with a 60-second preflight before writing SQL or narrative.
- Prefer recency and movement over static cumulative rankings unless the cumulative number is serving as a denominator.
- Before writing a named-entity headline, ask: what direct evidence names this entity?
- Write chart titles and opening lines as findings, not topics.
- Keep caveats subordinate unless they materially change the conclusion or confidence.

Evidence reviewed
- Workspace: `MEMORY.md`, `FRESHNESS.md`, `SCHEMA.md`, `QUERIES.md`, `AI_INSIGHTS_PLAYBOOK.md`, `AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md`, `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`, `SOUL.md`, prior reflection archive, reflection template
- OpenClaw docs: `/app/docs/tools/skills.md`, `/app/docs/tools/subagents.md`, `/app/docs/reference/transcript-hygiene.md`
- Light web research: answer-first / Pyramid Principle communication references used only as craft guidance, not as product or platform evidence
