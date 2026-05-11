1) Executive summary
- Strongest improvement: I stayed closer to evidence by grounding this reflection in local platform docs (`SCHEMA.md`, playbook/checklists, `AGENTS.md`, `USER.md`), prior archived reflections, and a small targeted web pass on executive communication.
- Main recurring risk remains contract/schema sloppiness under friction. Today’s concrete example was trying to read `/app/docs` as a file; the broader lesson remains: when tooling or paths reject an assumption, stop and verify the contract instead of improvising.
- Analyst/consulting quality improved by reinforcing answer-first communication: conclusion first, 2-3 supporting facts second, OCI implication or practical takeaway last.
- Product understanding deepened around warehouse constraints that matter for credible analysis: strict `query_database` gating, known schema gotchas, sparse/stale tables, and the need to distinguish warehouse-supported claims from craft-oriented external research.

2) Product/data learned
- `query_database` is tightly constrained by design: one read-only `SELECT` statement, AST-gated, `LIMIT` capped at 10,000, 5-second timeout, and no system-table / admin-function access (`SCHEMA.md`).
- Several warehouse caveats are durable and materially affect analytical accuracy:
  - `generator_permits.parent_company` is not a real column.
  - `events.event_date` can contain future junk values and should usually be clamped to `<= CURRENT_DATE` for recent-event analysis.
  - `sites.power_capacity_mw` is the canonical MW field.
  - `sites.provider_name = 'Company Not Disclosed'` should be excluded from operator rankings.
  - `anomalies` is currently empty and should not be treated as an active signal source.
- Local operating docs remain aligned on method:
  - Start with a question/hypothesis, not freeform narrative (`AI_INSIGHTS_PLAYBOOK.md`).
  - Run per-card and per-session disqualifier checks before shipping insights (`AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`).
  - Verify table/column reality against `SCHEMA.md` / `QUERIES.md` before writing custom SQL (`AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md`).
- User-facing presentation expectations remain clear from `USER.md`: real numbers, speed of recent signals, platform-freshness honesty, and no hedging filler.

3) Mistakes corrected or near-errors
- Near-error: I initially tried to `read` `/app/docs` as if it were a file and got `EISDIR`.
  - Correction: discover directory contents first, then read specific files.
  - Durable lesson: path-shape mistakes are the same class of error as schema-shape mistakes — verify the object before acting on it.
- Recurring mistake pattern confirmed by prior reflections: treating structured-tool/schema friction like something to push through instead of a signal to re-check the contract.
  - Correction: if a tool, path, or schema rejects inputs, stop immediately and verify docs/examples before retrying.
- Near-error in process reporting: it is easy to describe a workflow improvement before the underlying artifact/workflow is actually what enforced it.
  - Correction: make the artifact or archive behavior real first, then describe it as completed.

4) New communication/presentation technique learned
- Technique reinforced: answer-first executive communication using a simple pyramid structure:
  - first sentence = direct conclusion,
  - next 2-3 bullets/sentences = strongest supporting facts,
  - final sentence = implication / action / so-what.
- External research supported this pattern. The web results consistently emphasized Pyramid Principle-style communication: lead with the answer, then grouped support, then implication.
- Practical implication: titles, headlines, and opening sentences should state the takeaway, not merely the topic or the analysis process.

5) Anti-hallucination rule changes
- Reinforced rule: when the issue is tool contract, schema, or path shape, do not compensate by guessing. Fix the contract problem first.
- Reinforced rule: every quantitative or platform-behavior claim should be traceable to one of three buckets only:
  - local docs,
  - direct tool output,
  - clearly identified external source.
- Reinforced rule: external web research can improve communication craft and analytical method, but it cannot substitute for warehouse evidence when a claim is supposed to be data-backed.
- Reinforced rule: prefer a narrower true claim over a broader unsupported one, especially when warehouse coverage is partial or stale.

6) Habits to improve tomorrow
- Check canonical local docs before the first custom SQL or structured-tool call.
- Lead every substantive answer with the conclusion, not the process.
- Keep caveats in the answer, but subordinate them unless they materially change the read.
- Use explicit source labels mentally while drafting: doc-backed, tool-backed, inferred, externally-sourced.
- Do at least one focused block of external industry learning in addition to craft/process improvement.
