1) Executive summary
- Today’s strongest improvement was becoming more evidence-bound: I used local schema/query docs plus transcript review to distinguish what the platform actually supports from what I merely inferred.
- The main failure pattern was tool-contract sloppiness under friction: I guessed invalid `insight_id` values in OCI Insights QA/database calls, and I initially submitted `propose_qa_chart` without the required `series` payload. Both were avoidable.
- Product understanding improved materially: cron isolated jobs are fresh-session runs, scheduled jobs persist in Gateway state, query_database is AST-gated/read-only with a 5s timeout and 10k row cap, and several warehouse gotchas materially affect analysis quality.
- Communication improvement: lead with the answer, then caveats, then implication. That matched both the local persona guidance and external executive-communication patterns better than exploratory narration.
- Durable operating change recorded to memory: when QA/database tooling errors, do not invent IDs or continue with unsupported claims; re-check the tool contract and only retry with validated inputs.

2) Product/data learned
- From `SCHEMA.md`:
  - `query_database` is single-statement `SELECT` only, AST-validated, read-only, max 10,000 rows, statement timeout 5,000 ms.
  - Important gotchas:
    - `generator_permits.parent_company` is not a real column; parent rollups must join through `companies`.
    - `events.event_date` can contain future junk values; recent-event queries should clamp to `<= CURRENT_DATE`.
    - many `sites` lifecycle dates are `varchar`, not proper `date` columns.
    - `sites.power_capacity_mw` is the canonical MW field.
    - `sites.provider_name = 'Company Not Disclosed'` should be excluded from operator rankings.
    - `companies` is noisy/sparse in places; ticker/canonical filters matter.
- From `QUERIES.md`:
  - Canonical query patterns already existed for common asks like hyperscaler MW, permits by parent, state site rankings, and recent events. I should use/adapt those first instead of improvising from scratch.
  - The docs explicitly note `anomalies` is empty right now, so I should not imply anomaly coverage exists when it does not.
- From `SOUL.md`:
  - In QA-global mode, the guidance says empty-string `""` should be used for `insight_id` on drill-down read tools. Transcript evidence showed that guessed placeholders like `qa-global`, `current`, or fake UUIDs failed.
  - The persona requires direct, numerate, OCI-relevant framing and prohibits inventing numbers.
  - Chart choice should match the question shape, and chart payloads need complete specs.
- From cron/task docs:
  - Cron runs persist in Gateway, isolated jobs get fresh sessions, and one-shot jobs auto-delete after success.
  - TaskFlow is for durable multi-step orchestration; plain cron is enough for this reflection/report job.

3) Mistakes corrected or near-errors
- Mistake: I tried invalid `insight_id` values (`qa-global`, `000...`, `111...`, `current`) when querying OCI Insights tools.
  - Evidence: transcript `08c7356f-...` shows `bad_insight_id` and `404: insight_not_found` failures before the correct empty-string call succeeded.
  - Correction: use the documented tool contract from `SOUL.md` for QA-global; if the tool still fails, say the tool path is blocked instead of fabricating workarounds.
- Mistake: I first called `oci-insights__propose_qa_chart` without `series`.
  - Evidence: transcript `57f536b1-...` and `08c7356f-...` show validation failures requiring `series`.
  - Correction: treat chart specs as schema-bound objects, not shorthand signals.
- Near-error: I initially tried to `read` `/app/docs` directly as a file and got `EISDIR`.
  - Correction: list directories first, then read specific files.
- Near-error: I briefly considered web/browser fallback for a warehouse question when the real issue was malformed tool inputs.
  - Correction: solve contract/config problems before changing data source.
- Process gap: I told the user the archive behavior was in place before the folder/template existed, then fixed it later.
  - Correction: separate “prompt updated” from “runtime scaffolding created”.

4) New communication/presentation technique learned
- Technique: answer-first executive structure using a simple pyramid:
  - Line 1: the direct answer / headline.
  - Line 2-3: the 2-3 strongest supporting facts.
  - Final line: “so what” / implication / next useful cut.
- Why this is worth keeping:
  - It matches the local `SOUL.md` guidance (“consultative, not hedging”, “skip filler”, “pre-empt the next question”).
  - It also aligns with common consulting-style Pyramid Principle guidance from external sources: lead with the conclusion, then grouped support, then implication/action.
- Practical example from today:
  - Better: “Microsoft has ~2.5 GW in Virginia, concentrated in Boydton (~44%). Next-largest clusters are Bristow, Clarksville, and Leesburg. That concentration matters because it localizes competitive pressure on utility/substation capacity.”
  - Worse: leading with tool friction, caveats, or process before the answer.

5) Anti-hallucination rule changes
- New rule: when a tool call fails because of argument/contract issues, do not improvise placeholder IDs, inferred schema, or alternative unsupported claims. Stop, inspect the contract/doc, then retry with validated inputs.
- New rule: every numeric claim in this domain must be traceable to one of three things only: tool result, local schema/query documentation, or explicitly cited external source.
- New rule: distinguish “feed coverage” from “market reality.” Example: generator-permit counts by state reflected current covered feeds, not national market share.
- New rule: when docs describe a known gotcha, surface it in the answer if it affects interpretation (`events.event_date`, `Company Not Disclosed`, sparse MW fields, empty anomalies table).
- New rule: for schema-bound tools, assume required fields exist until proven otherwise; check examples/docs before first call instead of learning by validation failure.

6) Habits to improve tomorrow
- Start analytical turns by checking canonical local docs/patterns first when the question maps to a known warehouse query shape.
- Before first use of a structured tool in a turn, verify required arguments from docs or prior successful examples.
- Keep a strict separation between:
  - what the tool returned,
  - what the docs state,
  - and what I infer.
- In final answers, lead with the answer in one sentence, then caveats only if they materially change interpretation.
- Be more explicit when something is a platform limitation versus my own temporary failure.
- Continue capturing only durable lessons in long-term memory, not one-off transcript noise.
