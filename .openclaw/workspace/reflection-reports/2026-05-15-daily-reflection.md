1) Executive summary
- The main improvement opportunity is process discipline before synthesis: verify schema, table grain, and tool contracts up front, then write the conclusion in executive order. Most risk still comes from overconfident framing, not calculation.
- The strongest recurring lesson is that OCI-quality analysis requires a hard separation between what tools/docs directly support, what is inferred from patterns, and what commercial implication follows.
- Today’s review also reinforced a consulting communication habit worth keeping: answer first, support with 2–3 grouped facts, then close with the OCI implication.

2) Product/data learned
- The warehouse’s core analytical surfaces remain `sites`, `events`, `site_company_associations`, `generator_permits`, `energy_projects`, `edgar_extractions`, `companies`, plus the AI-insights pipeline tables. `sites` is the main datacenter inventory table; `events` is the system of record for lifecycle milestones.
- Key schema constraints re-confirmed from `SCHEMA.md` and `QUERIES.md`:
  - `sites.power_capacity_mw` is the canonical datacenter MW field.
  - `generator_permits.parent_company` is not a real column; parent rollups must use `resolved_company_id -> companies`.
  - Historical milestone analysis should use `events`, not deprecated lifecycle date columns on `sites`.
  - `events.event_date` can contain projected future milestones, so historical cuts should clamp to `CURRENT_DATE`.
  - `pct_construction` is a 0–1 fraction, not a 0–100 percentage.
  - `sites.end_user_companies` is a comma-separated string with sentinel no-customer values like `NULL`, empty string, `null`, and `[]`.
- Tool/platform constraints re-confirmed:
  - `query_database` is read-only, single-statement `SELECT`, auto-limited, and time-constrained; good analysis depends on narrow, schema-aware queries.
  - Skills are snapshot-based and should not be assumed to dynamically change within a session.
  - Sub-agents are isolated by default and are completion-push-based; polling loops are an antipattern.
- `FRESHNESS.md` is intentionally incomplete and should not be treated as blocking evidence; direct schema-aware drilling is the fallback.

3) Mistakes corrected or near-errors
- Recurring corrected mistake: using the first tool/query failure as the cue to inspect the contract. Better practice is to inspect `SCHEMA.md`, `QUERIES.md`, and relevant tool docs before the first query on unfamiliar terrain.
- Recurring near-error: letting plausible attribution outrun evidence, especially for unnamed end users, shell LLCs, or indirect company mapping. Prior durable memory already flags this, and today’s review confirms it remains the biggest hallucination risk.
- Recurring near-error: describing tooling behavior from memory instead of documentation. For analyst work, tool constraints are part of the evidence base; getting them wrong weakens conclusions and process recommendations.
- Positive correction: when local docs are consulted early, most ambiguity collapses quickly. The weakness is not recovery but delayed verification.

4) New communication/presentation technique learned
- Reinforced technique: Pyramid Principle / answer-first executive communication. State the conclusion first, then group 2–3 reasons, then provide evidence.
- Better consulting adaptation for OCI work: every title and first sentence should state a finding, not a topic.
- Drafting refinement worth keeping: organize claims into three layers—known, inferred, and implication/action. This keeps executive brevity from silently converting inference into fact.

5) Anti-hallucination rule changes
- Before first SQL on any unfamiliar table, read `SCHEMA.md` and verify exact columns, grain, and date semantics; never infer SQL identifiers from memory.
- If an entity is not directly named in warehouse fields or cited documents, present it as a hypothesis, not an attribution.
- When tool behavior matters to the answer, verify the contract from local docs instead of relying on remembered intuition.
- Force every key sentence into one of three buckets: tool-backed fact, source-backed fact, or labeled inference. If it fits none, cut or rewrite it.

6) Habits to improve tomorrow
- Start each unfamiliar analysis with a 60-second preflight: table grain, canonical metric column, date reliability, sentinel/null handling, stale-table risk, and the likely comparison axis.
- Before writing any named-entity headline, ask: “What direct evidence names this entity?” If none, downgrade the claim.
- Prefer movement and recency over static cumulative rankings unless the cumulative number is serving as a denominator.
- Write chart titles and opening sentences as findings.
- Keep caveats subordinate unless they materially change the conclusion or confidence.

Evidence reviewed
- Workspace: `MEMORY.md`, `SCHEMA.md`, `QUERIES.md`, `AI_INSIGHTS_PLAYBOOK.md`, `AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md`, `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`, `FRESHNESS.md`, prior reflection archive
- OpenClaw docs: `/app/docs/reference/transcript-hygiene.md`, `/app/docs/tools/skills.md`, `/app/docs/tools/subagents.md`
- Light web research: answer-first/Pyramid Principle communication references and anti-hallucination process references (used only as supplementary craft guidance, not as product/platform facts)
