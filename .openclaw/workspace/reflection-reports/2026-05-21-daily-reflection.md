1) Executive summary
- Best improvement today: I re-grounded myself in the actual warehouse and tool contracts before synthesizing. The clearest concrete mistake was an avoidable surface-shape error (`read` on `/app/docs` as though it were a file), which is the same failure mode as schema guessing.
- Product understanding improved around the OCI analytics surface: `events` is the milestone source of truth, `sites.power_capacity_mw` is the canonical MW field, `query_database` is single-statement/read-only/limited, and sub-agents are isolated by default with push-based completion.
- The practical analyst/consultant takeaway is straightforward: separate tool-backed fact, doc/source-backed fact, and inference explicitly; then present the answer in executive order.

2) Product/data learned
- From `SCHEMA.md`:
  - The core warehouse surfaces are `sites`, `events`, `site_company_associations`, `generator_permits`, `building_permits`, `energy_projects`, `edgar_extractions`, and `companies`.
  - `sites.power_capacity_mw` is the canonical datacenter MW field.
  - Milestone dates should come from `events`; deprecated milestone columns on `sites` are not reliable for lifecycle analysis.
  - `events.event_date` can include projected future milestones, so historical cuts should clamp to `CURRENT_DATE`.
  - `generator_permits.parent_company` is not a real column; parent rollups must join via `resolved_company_id -> companies.canonical_name`.
  - `sites.end_user_companies` is a comma-separated string with sentinel no-customer values.
- From local workflow docs/playbooks:
  - SQL must be schema-confirmed; plausible generic columns remain a recurring failure mode.
  - `query_database` allows one read-only `SELECT`, auto-limits at 10,000 rows, and runs under a 5-second statement timeout.
  - `pct_construction` is a 0–1 fraction, not 0–100.
  - Good OCI insights bias toward recency and movement, not static cumulative rankings.
  - Every insight should end in an explicit OCI opportunity or OCI threat, not “monitor/watch/be aware” language.
  - A useful preflight is: grain, canonical metric, date semantics, sentinel/null handling, and tool/doc contract.
- From `/app/docs`:
  - Cron runs inside Gateway, persists jobs/state, and isolated jobs run in fresh sessions.
  - Local docs are the authoritative contract for behavior details; they should be verified, not recalled from memory.
  - Parallel specialist work is a scarce-capacity design problem: reduce contention, define lane contracts, and push slow work into background/isolated paths.

3) Mistakes corrected or near-errors
- Concrete corrected mistake: I attempted to `read` `/app/docs` directly and got `EISDIR` because it is a directory, not a file.
- Why it matters: this is the same class of mistake as querying unverified columns—acting before confirming the surface shape.
- Near-error re-confirmed: waiting for the first tool or SQL failure before checking the contract. The better pattern is preflight first.
- Near-error re-confirmed: plausible named-entity attribution can outrun evidence. If a customer, end user, or parent company is not directly named in tool output or cited text, it must remain inference.
- Near-error re-confirmed: describing platform/tool behavior from recollection as if verified. If the behavior matters, the docs are part of the evidence base.

4) New communication/presentation technique learned
- Reinforced technique from light web research: Pyramid Principle / answer-first communication.
- Practical implementation:
  - first line = defended answer
  - next 2–3 bullets = grouped support
  - last line = OCI implication or action
- Extra refinement: use finding titles, not topic titles. The title should state the conclusion, not just the subject.
- Most useful synthesis habit: visibly separate known, inferred, and implication so concise prose does not smuggle in false certainty.

5) Anti-hallucination rule changes
- New rule: when surveying docs or workspace context, discover files first; never treat a directory as file input.
- Before first SQL on an unfamiliar table, verify exact columns, grain, date semantics, and known gotchas from `SCHEMA.md` or canonical query patterns.
- If a named entity is not directly present in tool output or cited source text, state it as inference/hypothesis, not fact.
- Any sentence that is neither tool-backed fact, source-backed fact, nor clearly labeled inference should be cut or rewritten.
- Sparse freshness/context files are not a reason to speculate; the fallback is schema-aware direct drilling.

6) Habits to improve tomorrow
- Start unfamiliar work with a 60-second preflight: discover surface, verify schema/docs, then analyze.
- Bias every analysis toward change, recency, and decision relevance instead of static cumulative rankings.
- Before writing any named-company claim, ask: what tool result or cited text directly names this entity?
- Write the opening sentence and chart title as findings, not topics.
- Keep caveats subordinate unless they materially change the conclusion or confidence.

Evidence reviewed
- Workspace: `MEMORY.md`, `SCHEMA.md`, recent reflection archives
- OpenClaw docs: `/app/docs/AGENTS.md`, `/app/docs/concepts/agent-workspace.md`, `/app/docs/concepts/memory-search.md`, `/app/docs/concepts/parallel-specialist-lanes.md`, `/app/docs/automation/cron-jobs.md`, `/app/docs/cli/approvals.md`
- Light web research: Pyramid Principle / answer-first communication references, used only as supplementary communication guidance
