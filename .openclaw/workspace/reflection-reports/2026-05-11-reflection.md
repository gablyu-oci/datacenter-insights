1) Executive summary
- Strongest improvement: I reinforced an evidence-first analyst workflow by grounding this reflection in local platform docs (`SCHEMA.md`, `QUERIES.md`, playbook/checklists, memory docs) and only using web research for communication craft and verification method ideas.
- Main recurring risk remains contract sloppiness under friction: when a path, tool, or schema assumption fails, I can lose time unless I stop immediately and verify the contract.
- The clearest consulting improvement is to present answer-first: conclusion first, 2-3 supporting facts second, implication/action last.
- Product understanding improved around the warehouse’s real constraints: schema gotchas, sparse/stale tables, and the difference between warehouse-backed claims and externally sourced general advice.

2) Product/data learned
- `query_database` is intentionally constrained: one read-only `SELECT`, AST-gated, auto-limited/clamped to 10,000 rows, 5-second timeout, and no system/admin table access (`SCHEMA.md`).
- Durable warehouse gotchas that materially affect analysis quality:
  - `generator_permits.parent_company` is not a real column.
  - `events.event_date` can contain future junk values; recent-event queries should usually clamp to `<= CURRENT_DATE`.
  - `sites.power_capacity_mw` is the canonical MW field.
  - `sites.provider_name = 'Company Not Disclosed'` should be excluded from operator rankings.
  - `anomalies` is currently empty, so it should not be treated as an active source of signal.
- The local method docs are mutually reinforcing:
  - Start from a question/hypothesis, not prose-first (`AI_INSIGHTS_PLAYBOOK.md`).
  - Run explicit disqualifier and ship checks before persisting insights (`AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`).
  - Verify schema reality before custom SQL (`AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md`, `SCHEMA.md`, `QUERIES.md`).
- `FRESHNESS.md` is currently a placeholder and should not be over-trusted; when freshness matters, direct querying is the reliable path.

3) Mistakes corrected or near-errors
- Near-error: I first tried to `read` `/app/docs` as if it were a file and got an `EISDIR` error.
  - Correction: enumerate the directory first, then read specific files.
  - Lesson: path-shape mistakes and schema-shape mistakes are the same family—verify the object before acting on it.
- Recurring near-error pattern: treating tool/schema friction as something to push through instead of a signal to re-check assumptions.
  - Correction: after the first contract error, stop and verify docs/examples before retrying.
- Reflection discipline improvement: distinguish clearly between what today’s tools/docs directly supported and what prior memory suggested. That keeps the reflection evidence-based instead of self-congratulatory narrative.

4) New communication/presentation technique learned
- Reinforced technique: use a simple Pyramid Principle structure for executive communication:
  - sentence 1: answer,
  - next 2-3 bullets/sentences: grouped supporting facts,
  - final sentence: implication or action.
- The web pass consistently supported this top-down consulting pattern, especially around stating the takeaway before the analytical path.
- Practical adaptation for OCI/data work: chart titles, headlines, and opening lines should state the finding, not the topic.

5) Anti-hallucination rule changes
- New durable rule: when a tool/path/schema rejects an assumption, stop and verify the contract before retrying; do not improvise around the error.
- Reinforced rule: every meaningful quantitative/platform claim should be mentally tagged as one of four types while drafting: tool-backed, doc-backed, inferred, or externally sourced.
- Reinforced rule: external web research can improve communication craft and analysis method, but it cannot substitute for warehouse evidence when making platform/data claims.
- Reinforced rule: prefer narrower true statements over broader unsupported synthesis, especially where coverage is partial, stale, or placeholder-backed.

6) Habits to improve tomorrow
- Check canonical local docs before the first custom SQL or structured-tool assumption.
- Start every substantive answer with the conclusion.
- Compare claims against source type before sending: doc, tool, inference, or web.
- Keep caveats subordinate unless they change the decision.
- Add one focused external learning block on data-analysis or consulting craft each day, but keep platform claims grounded in local evidence.
