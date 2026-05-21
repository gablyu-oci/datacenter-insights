1) Executive summary
- Strongest improvement today was reinforcing an evidence-first operating rhythm: verify schema/tool contracts before analysis, then communicate findings in executive order rather than exploratory order.
- The main recurring risk remains claim inflation, not arithmetic. Local memory and prior reflections show that the bigger failure mode is turning plausible inference into stronger attribution or certainty than the evidence supports.
- I also sharpened one practical consulting habit: use answer-first structure, but explicitly distinguish what is known, what is inferred, and what OCI should do.

2) Product/data learned
- The OCI Strategic Insights warehouse is anchored on `sites`, `events`, `site_company_associations`, `generator_permits`, `energy_projects`, `edgar_extractions`, `companies`, and AI-insight pipeline tables.
- `query_database` is tightly constrained: single read-only `SELECT`, AST-gated, auto-clamped to `LIMIT 10000`, and subject to a ~5 second timeout. That means analyses should be narrow, deliberate, and schema-aware before querying.
- High-value schema constraints confirmed from `SCHEMA.md`:
  - `sites.power_capacity_mw` is the canonical MW column.
  - `generator_permits.parent_company` is not a real column; parent rollups must go through `resolved_company_id -> companies`.
  - `events.event_date` can include implausible future dates, so recency filters should cap at `CURRENT_DATE`.
  - Many `sites` lifecycle dates are `varchar`, so they are poor foundations for strict date logic.
  - `sites.end_user_companies` is a comma-separated string with sentinel null-like values.
  - `sites.provider_name` includes `Company Not Disclosed`, which should usually be excluded in provider rankings.
- `FRESHNESS.md` is intentionally incomplete and should not block work; direct, schema-aware drilling is the intended fallback.
- OpenClaw platform/tooling reminders from local docs:
  - skills are snapshot-based per session and should not be assumed to refresh mid-thought unless watcher/reload conditions apply;
  - sub-agents are isolated by default and completion is push-based, so polling loops are poor practice.

3) Mistakes corrected or near-errors
- Recurring corrected mistake: waiting until after a query/tool failure to verify the contract. The local playbook and prior reflections agree the fix is to front-load schema checks instead of treating the first error as discovery.
- Recurring near-error: upgrading pattern-matching into attribution. Durable memory already records this, and it remains the key analytical danger for OCI work involving unnamed end users, shell LLCs, or indirect evidence.
- Recurring near-error: describing tools from intuition rather than docs. Today’s review reinforced that tool constraints matter materially to analysis quality; remembered capability is not evidence.
- Positive correction pattern: once docs are consulted, corrections are usually straightforward. The process weakness is not inability to recover; it is letting unsupported structure enter the draft before verification.

4) New communication/presentation technique learned
- Best technique reinforced today: Pyramid Principle / answer-first communication. For executive readers, lead with the conclusion, support it with 2–3 grouped facts, then end with the commercial implication.
- Practical OCI adaptation: make titles and first sentences findings, not topics. Example pattern: conclusion -> why it is true -> OCI opportunity/threat.
- Additional refinement: separate statements into three layers when drafting:
  - known from tool/source evidence,
  - inferred from patterns,
  - recommended implication/action.
  This preserves concise consulting style without disguising inference as fact.

5) Anti-hallucination rule changes
- New durable rule: before first SQL on an unfamiliar table, read `SCHEMA.md` and verify exact columns/date types; never infer SQL identifiers from memory.
- Reinforced rule: if a company/customer/end user is not directly named in warehouse fields or cited documents, present it only as a hypothesis, never as attribution.
- New rule: do not describe a tool’s behavior from remembered intuition when a local doc exists; verify the contract first if the capability matters to the answer.
- New rule: every key sentence in an executive answer should map to one of three buckets—tool-backed fact, source-backed fact, or labeled inference. If it fits none, cut or rewrite it.

6) Habits to improve tomorrow
- Start each unfamiliar analysis with a 60-second preflight: table grain, canonical metric, date reliability, sentinel/null handling, stale-table risk, and likely filters.
- Before writing a headline with a named entity, ask: “What direct evidence names this entity?” If none, downgrade to a hypothesis framing.
- Bias analyses toward recency and movement, not static cumulative rankings, unless the cumulative view is only serving as a denominator.
- Use finding-first titles for summaries and charts.
- Keep caveats subordinate unless they materially change the recommendation or confidence.

Evidence used
- Local memory: `MEMORY.md`, prior reflection archives
- Workspace docs: `SCHEMA.md`, `AI_INSIGHTS_PLAYBOOK.md`, `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`, `AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md`, `FRESHNESS.md`
- OpenClaw docs: `/app/docs/tools/skills.md`, `/app/docs/tools/subagents.md`
- Light external research: web search snippets on Pyramid Principle / answer-first executive communication and hallucination-mitigation best practices
