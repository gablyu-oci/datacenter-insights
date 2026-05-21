1) Executive summary
- Strongest improvement opportunity: move schema/tool-contract verification earlier. Today’s local evidence reinforces that the highest-risk failure mode is not arithmetic error; it is making a plausible claim before confirming the warehouse field, tool behavior, or attribution basis.
- I learned useful platform constraints from local docs: `query_database` is single-statement read-only SQL with a 10k-row cap and ~5s timeout; `web_fetch` is plain HTTP extraction with no JavaScript; stale/empty warehouse tables should be avoided; `sites.power_capacity_mw` is the canonical MW field.
- Best consulting improvement from today’s review: keep executive communication answer-first, but explicitly separate three layers: known facts, inference, and OCI implication.

2) Product/data learned
- The Strategic Insights warehouse is centered on `sites`, `events`, `site_company_associations`, `generator_permits`, `energy_projects`, `edgar_extractions`, `companies`, and AI-insight pipeline tables.
- `query_database` is AST-gated: one SELECT statement only, no DDL/DML, no system-table access, auto-limited/clamped to 10,000 rows, with a 5-second timeout.
- Important warehouse gotchas from `SCHEMA.md`:
  - `generator_permits.parent_company` is not a real column.
  - `events.event_date` can contain implausible future values, so recency cuts should cap at `CURRENT_DATE`.
  - Many `sites` date fields are `varchar`, not real dates.
  - `sites.power_capacity_mw` is the canonical MW column.
  - `sites.end_user_companies` is a comma-separated string, not an array.
  - `sites.provider_name` includes `Company Not Disclosed`, which should usually be excluded in operator rankings.
- `FRESHNESS.md` is explicitly a placeholder and should not block analysis; direct drilling via schema-aware SQL is the intended fallback.

3) Mistakes corrected or near-errors
- Recurring corrected mistake: treating likely-but-unverified columns as real. Prior reflection evidence already showed misses like invalid column assumptions; today’s docs confirm this is a structural risk, not a one-off error.
- Recurring near-error: upgrading pattern-matching into attribution. Existing memory already documents the risk of turning unnamed or undisclosed end users into specific company claims.
- Recurring near-error: describing tool capabilities too broadly. Local docs confirm that `web_fetch` does not execute JavaScript, so using it conceptually as a browser substitute would be unsupported.
- Positive correction pattern: when tool/schema contracts are re-checked, the analysis usually self-corrects quickly. The issue is timing—verification should happen before drafting, not after a failed attempt.

4) New communication/presentation technique learned
- Reinforced consulting technique from external research plus local playbook alignment: use answer-first pyramid structure with action titles, not topic titles.
- Practical version for OCI/data work:
  - Sentence 1: direct conclusion.
  - Sentences 2-3: grouped supporting facts.
  - Final sentence: explicit OCI opportunity or OCI threat with entity + timeframe + number/action.
- Additional refinement: present uncertainty in layers—"known," "inferred," and "unknown"—so executive brevity does not smuggle in false certainty.

5) Anti-hallucination rule changes
- New rule: before the first SQL query on any unfamiliar table, read `SCHEMA.md` and verify the exact columns, date types, and known gotchas.
- New rule: if a company/customer/end-user is not directly named in warehouse fields or cited documents, present it only as a hypothesis, never as attribution.
- New rule: do not describe a tool by remembered intuition when a local tool doc exists; verify the contract first.
- New rule: when presenting an executive conclusion, tag each key statement mentally as either tool-supported fact, source-supported fact, or inference. If a sentence has no backing in one of those buckets, rewrite or remove it.

6) Habits to improve tomorrow
- Start every unfamiliar analysis with a 60-second preflight: table grain, canonical metric column, date quality, null/sentinel handling, and stale-table check.
- Compare every named-entity claim against direct evidence before writing the headline.
- Prefer recency/movement cuts over static cumulative rankings unless the cumulative view is only a denominator.
- Use action-title phrasing for summaries and charts: finding first, topic second.
- Keep caveats subordinate unless they change the decision.

Evidence used
- Local memory: `MEMORY.md`, `memory/dreaming/light/2026-05-13.md`
- Local docs: `/app/docs/tools/web-fetch.md`, `/app/docs/tools/exec-approvals.md`, `/app/docs/tools/subagents.md`, `/app/docs/gateway/sandbox-vs-tool-policy-vs-elevated.md`
- Workspace docs: `SCHEMA.md`, `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`, `AI_INSIGHTS_PLAYBOOK.md`, `FRESHNESS.md`
- Light external research: web search results on pyramid-principle / executive communication and evidence-based anti-hallucination practice
