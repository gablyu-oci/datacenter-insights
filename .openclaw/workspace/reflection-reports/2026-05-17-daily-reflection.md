1) Executive summary
- The main improvement today is procedural, not conceptual: inspect the evidence surface before synthesizing. The clearest error I found was an avoidable file-vs-directory mistake (`read /app/docs`) that cost a turn and is the same class of failure as schema guessing in SQL.
- Product understanding improved around how the warehouse and cron/runtime actually behave: `events` is the system of record for milestones, `sites.power_capacity_mw` is the canonical MW field, `query_database` is tightly sandboxed, and isolated cron runs use fresh sessions with guarded delivery semantics.
- The practical analyst lesson is unchanged but better evidenced: separate tool-backed fact, source-backed fact, and inference explicitly, then present the answer in executive order.

2) Product/data learned
- From `SCHEMA.md`: the Strategic Insights warehouse is the OCI Datacenter & Power Intelligence Platform warehouse, with core analytical surfaces in `sites`, `events`, `site_company_associations`, `generator_permits`, `building_permits`, `energy_projects`, `edgar_extractions`, and `companies`.
- Important warehouse constraints re-confirmed:
  - `sites.power_capacity_mw` is the canonical datacenter MW field.
  - `events` is the source of truth for milestone dates; deprecated lifecycle date columns on `sites` are not reliable for milestone analysis.
  - `events.event_date` can include future projected milestones, so historical analysis should clamp to `CURRENT_DATE`.
  - `generator_permits.parent_company` is not a real column; parent rollups must join via `resolved_company_id -> companies.canonical_name`.
  - `sites.end_user_companies` is a comma-separated string with sentinel no-customer values (`NULL`, empty string, `null`, `[]`).
- From `AI_INSIGHTS_PLAYBOOK.md` and `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`: good OCI analysis should bias toward recency/movement, not static cumulative rankings, and every insight should end in a concrete OCI opportunity or threat rather than “monitor/watch” language.
- From `/app/docs/automation/cron-jobs.md`: isolated cron runs use a fresh session each run, persist job state in Gateway files, create background task records, and guard against stale interim-status delivery.
- From `/app/docs/AGENTS.md`: docs work has strict link/content conventions; more broadly, local docs are the authoritative contract for behavior details that should not be recalled from memory.

3) Mistakes corrected or near-errors
- Confirmed concrete mistake from prior reflection workflow: I tried to `read` `/app/docs` as if it were a file and got `EISDIR`. The corrected process is to discover files first (`find`/listing), then read specific documents.
- Near-error pattern re-confirmed from memory and docs: waiting for the first tool/query failure before checking the contract. The better method is preflight first, especially on unfamiliar schema, date semantics, and tool behavior.
- Near-error pattern re-confirmed: plausible entity attribution can outrun evidence. If an end user, parent company, or customer is not directly named in warehouse fields or cited documents, it must stay provisional.
- Another subtle risk: treating remembered platform behavior as evidence. Tool constraints are part of the evidence base; if they matter to the recommendation, they need doc verification.

4) New communication/presentation technique learned
- Technique reinforced from light web research: Pyramid Principle / answer-first communication. Open with the recommendation or finding, then group supporting reasons, then show evidence.
- Practical adaptation for analyst work: use “finding titles,” not topic titles. Example habit: make the headline a claim that can be defended, not a subject label.
- Added presentation rule: keep a visible distinction between known, inferred, and implication/action. That preserves executive brevity without quietly overstating certainty.

5) Anti-hallucination rule changes
- New rule: before using `read`, confirm the target path is a file, not a directory; when surveying docs, list/discover first, then open only relevant files.
- Before first SQL on an unfamiliar table, verify exact columns, grain, date semantics, and known gotchas from `SCHEMA.md` or validated query patterns.
- If a named entity is not directly present in tool output or cited text, label the statement as inference/hypothesis rather than fact.
- Any sentence that is neither tool-backed fact, source-backed fact, nor clearly labeled inference should be cut.

6) Habits to improve tomorrow
- Run a 60-second preflight before unfamiliar analysis: file/table shape, canonical metric field, date reliability, sentinel/null behavior, and tool contract.
- Discover first, then read/query. Avoid direct path assumptions in docs and schema work.
- Bias every analysis toward change, recency, and decision relevance rather than cumulative rankings.
- Write the first sentence and chart title as the answer.
- Keep caveats subordinate unless they materially alter the conclusion.

Evidence reviewed
- Workspace: `MEMORY.md`, `SCHEMA.md`, `AI_INSIGHTS_PLAYBOOK.md`, `AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md`, `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`, prior reflection archive
- OpenClaw docs: `/app/docs/AGENTS.md`, `/app/docs/automation/cron-jobs.md`, `/app/docs/brave-search.md`
- Session transcripts: prior daily reflection run and recent session logs showing the concrete `EISDIR` error
- Light web research: Pyramid Principle / executive communication references, used only as supplementary communication guidance
