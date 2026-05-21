1) Executive summary
- The main improvement today is evidence discipline: I grounded the reflection in local docs, workspace playbooks, prior reflections, and memory instead of relying on recollection.
- The clearest concrete mistake was an avoidable tool misuse pattern already visible in yesterday’s workflow: treating a directory as a file (`read /app/docs`). That is the same class of failure as schema guessing—acting before verifying the surface.
- Product understanding improved around the actual operating contracts: `events` is the milestone system of record, `sites.power_capacity_mw` is the canonical MW field, `query_database` is single-statement/read-only/limited, `FRESHNESS.md` is intentionally non-blocking, and isolated cron runs use fresh sessions with guarded delivery behavior.
- The consulting/analyst improvement remains consistent: present answer-first, keep support grouped, and explicitly separate what is known, inferred, and actionable for OCI.

2) Product/data learned
- From `SCHEMA.md`:
  - The Strategic Insights warehouse centers on `sites`, `events`, `site_company_associations`, `generator_permits`, `building_permits`, `energy_projects`, `edgar_extractions`, and `companies`.
  - `sites.power_capacity_mw` is the canonical datacenter MW field.
  - Milestone dates on `sites` are deprecated/null; milestone timing should come from `events`.
  - `events.event_date` can contain projected future dates, so historical cuts should clamp to `CURRENT_DATE`.
  - `generator_permits.parent_company` is not a real column; parent rollups must join via `resolved_company_id -> companies.canonical_name`.
  - `sites.end_user_companies` is a comma-separated string with sentinel no-customer values.
- From `QUERIES.md` and `AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md`:
  - SQL must stay schema-confirmed; plausible generic columns are a real failure mode.
  - `query_database` is constrained to one read-only `SELECT`, auto-limited to 10,000 rows, with a 5-second timeout.
  - `pct_construction` is 0–1, not 0–100.
- From `AI_INSIGHTS_PLAYBOOK.md` and `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`:
  - Good OCI insights bias toward recency/movement, not static cumulative rankings.
  - Every insight should end in an explicit OCI opportunity or threat, not “monitor/watch/be aware” language.
  - A usable preflight is: table grain, canonical metric, date semantics, sentinel/null handling, and tool/doc contract.
- From `/app/docs/automation/cron-jobs.md`:
  - Cron runs inside Gateway, persists job definitions/state separately, and isolated jobs run in fresh sessions.
  - Isolated cron runs also guard against stale interim-status delivery, which matters when interpreting cron-delivered outputs.
- From `/app/docs/AGENTS.md` and browser docs:
  - Local docs are the authoritative contract for behavior details; capability descriptions should be verified, not recalled from memory.

3) Mistakes corrected or near-errors
- Concrete corrected mistake: attempting to `read` `/app/docs` directly produced `EISDIR` because it is a directory, not a file.
- Why it mattered: it wasted a turn and exposed a recurring failure pattern—skipping discovery and assuming the surface shape.
- Near-error re-confirmed from memory: waiting for the first query/tool failure before checking schema or docs. That is avoidable and slows both accuracy and delivery.
- Near-error re-confirmed: plausible named-entity attribution can outrun evidence. If a customer/end user/company is not directly named in a field or cited document, it must remain provisional.
- Near-error re-confirmed: describing tool/platform behavior from memory as if verified. When behavior details matter to the recommendation, the docs are part of the evidence base.

4) New communication/presentation technique learned
- Reinforced external communication technique: Pyramid Principle / answer-first structure remains the best fit for executive analytical writing.
- Practical implementation: first line = answer; next 2–3 bullets = grouped supports; last line = OCI implication/action.
- Additional presentation refinement: use “finding titles,” not topic titles. A title should state the defended conclusion, not merely the subject.
- Most useful synthesis habit: visibly separate three layers—known, inferred, and implication—so concise prose does not smuggle in false certainty.

5) Anti-hallucination rule changes
- New durable rule: when surveying docs or workspace context, discover files first; never treat a directory as readable file input.
- Before first SQL on an unfamiliar table, verify exact columns, grain, date semantics, and known gotchas from `SCHEMA.md` or canonical query patterns.
- If a named entity is not directly present in tool output or cited source text, state it as inference/hypothesis, not fact.
- Any sentence that is neither tool-backed fact, source-backed fact, nor clearly labeled inference should be cut or rewritten.
- `FRESHNESS.md` being sparse/placeholder is not a reason to speculate; the fallback is schema-aware direct drilling.

6) Habits to improve tomorrow
- Start unfamiliar work with a 60-second preflight: discover surface, verify schema/docs, then analyze.
- Bias every analysis toward change, recency, and decision relevance instead of static cumulative rankings.
- Before writing any named-company claim, ask: what tool result or cited text directly names this entity?
- Write the opening sentence and chart title as findings, not topics.
- Keep caveats subordinate unless they materially change the conclusion or confidence.
