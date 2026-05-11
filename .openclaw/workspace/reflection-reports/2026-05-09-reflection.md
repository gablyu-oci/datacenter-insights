1) Executive summary
- Strongest improvement: I reinforced an evidence-first analyst workflow by grounding lessons in local platform docs (`SCHEMA.md`, playbook/checklists, `AGENTS.md`, `USER.md`) and prior reflection history before drawing conclusions.
- The main recurring risk remains contract/schema sloppiness under tool friction: the durable fix is to verify tool shape, file paths, and documented schema before improvising.
- I improved consulting style by converging on answer-first executive structure: conclusion first, 2-3 supporting facts second, OCI implication last.
- Product understanding deepened around platform constraints that matter for analysis quality: strict SQL gating, known warehouse gotchas, sparse/stale tables, and the role of cron-isolated runs.

2) Product/data learned
- `query_database` is tightly constrained: single read-only `SELECT`, AST-gated, 10k row cap, 5s timeout, and no DDL/DML or system-table access (`SCHEMA.md`).
- Several warehouse caveats are durable and materially affect analytical accuracy:
  - `generator_permits.parent_company` is not a real column.
  - `events.event_date` can contain future junk values and should be clamped to `<= CURRENT_DATE`.
  - `sites.power_capacity_mw` is the canonical MW field.
  - `sites.provider_name = 'Company Not Disclosed'` should be excluded from operator rankings.
  - `anomalies` is currently empty and should not be treated as an active signal source.
- Workflow/platform lesson: cron isolated jobs are appropriate for detached recurring reflection/reporting, while TaskFlow is for more durable orchestration.
- User/workflow guidance from local files remains consistent: use denominator-first ledgers, executive order writing, and explicit OCI implications.

3) Mistakes corrected or near-errors
- Near-error: I initially tried to `read` `/app/docs` as if it were a file and hit `EISDIR`.
  - Correction: directory discovery comes first; then read specific files.
- Recurring mistake pattern (confirmed by prior reflections and memory): treating tool validation friction like something to push through instead of a signal to stop and re-check the contract.
  - Correction: if a tool rejects inputs, stop immediately and verify docs/examples before retrying.
- Near-error in reflection process design: it is easy to claim a workflow change before the governing artifact or archive behavior is actually in place.
  - Correction: make the artifact change first, then describe it as completed.

4) New communication/presentation technique learned
- Technique reinforced: answer-first executive communication using a simple pyramid:
  - sentence 1 = direct conclusion,
  - next 2-3 bullets/sentences = strongest supporting facts,
  - final sentence = OCI implication / so-what.
- External research supported this: multiple consulting-oriented sources emphasized answer-first communication and structured support rather than chronological reasoning traces.
- Practical implication: titles, headlines, and first sentences should state the takeaway, not just the topic.

5) Anti-hallucination rule changes
- New reinforcement: when the issue is tool contract, schema, or path shape, do not compensate by guessing. Fix the contract problem first.
- New reinforcement: every quantitative or platform-behavior claim should be traceable to one of three buckets only:
  - local docs,
  - direct tool output,
  - clearly identified external source.
- New reinforcement: external web research can improve communication craft and analytical method, but it cannot substitute for warehouse evidence when a claim is supposed to be data-backed.

6) Habits to improve tomorrow
- Check canonical local docs before first custom SQL or structured-tool call.
- Lead every substantive answer with the conclusion, not the process.
- Keep caveats in the answer, but subordinate them unless they materially change the read.
- Use explicit source labels mentally while drafting: doc-backed, tool-backed, inferred.
- Do at least one focused block of external industry learning in addition to craft/process improvement.