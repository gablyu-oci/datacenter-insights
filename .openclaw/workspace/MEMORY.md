# MEMORY.md — Long-Term Distilled Memory

Curated, evergreen facts that survive across sessions. The raw
session transcripts in `.openclaw/agents/main/sessions/*.jsonl` are
the forensic record; this file is the distillate. Read on session
startup; update when something is genuinely worth keeping.

## How to use this file

- **Read first.** Before answering, scan the relevant section
  below for prior context.
- **Write sparingly.** Append a one-line note when:
  - The user explicitly says "remember this"
  - You uncover a recurring pattern across multiple sessions
  - You learn a non-obvious fact about a player, a platform
    quirk, or a data-source caveat
- **Prune.** When an entry goes stale (a deal closed, a tracked
  player IPO'd, a coverage gap fixed), remove or annotate it.
- **Don't accumulate a dossier.** If MEMORY.md grows past ~150
  lines, distill the oldest section into a 1-line summary and
  drop the rest.

Day-by-day raw notes go in `memory/YYYY-MM-DD.md`. They are the
working draft; this file is the published version.

---

## Players being tracked

_Append as patterns emerge. Format:_
> `<company>` — `<one-line observation>` — _<date or session ref>_

- Crusoe DC-1 Wyoming 360 MW  _<2026-05-06>_

## Recurring questions / decision patterns

_The kinds of questions the user keeps asking about. Helps you
anticipate the next one._

- When QA/database tooling errors, do not guess IDs or continue with unsupported claims; surface the constraint, re-check docs/tool contract, and retry only with validated inputs.  _<2026-05-07>_
- Always apply structured research and data-analysis techniques when generating AI insights; use hypothesis-driven, evidence-first analysis.  _<2026-05-07>_
- When OCI Insights tools fail on argument/ID validation, stop and re-check docs or prior successful calls; never invent placeholder insight_id, schema, or chart fields.  _<2026-05-08>_


## Platform quirks worth knowing

_E.g. "FactPack section X is empty most days because adapter Y
upserts without bumping `updated_at`." Concrete, actionable._

- Current memory setup needed manual restoration of daily notes and DREAMS.md; dreaming enabled but artifacts absent at initial audit.  _<2026-05-06>_
- SQL generation must verify warehouse columns against SCHEMA.md/QUERIES.md; plausible generic columns can break the v2 flow before persist.  _<2026-05-08>_
- Known follow-up: agent may skip build_chart despite stronger prompt; fallback covers for now. Likely fixes: model variant, MCP finalize gating until charts exist, or one-shot build_chart example.  _<2026-05-08>_


## User preferences observed

_Specific phrasings, units, levels-of-detail the user has
reacted positively / negatively to. Cross-checks what's in
USER.md, but USER.md is intent; this is observation._

- User prefers analyst outputs built from denominator-first ledgers, reconciled exposure math, and executive narrative that ties evidence directly to OCI implications.  _<2026-05-08>_
- User wants analytical style generalized from examples: learn the method, evidence handling, and narrative structure without copying the specific subject matter or template.  _<2026-05-08>_


## Threads to revisit

_Open questions where the answer wasn't yet available. When new
data lands, come back here and resolve them._

- Tracking Crusoe DC-1 in Wyoming as an offtake target.  _<2026-05-06>_
- Track Crusoe DC-1 in Wyoming as an offtake target.  _<2026-05-06>_


---

_Last reviewed: (initial seed; agent should refresh this line each time MEMORY.md is materially updated)_

## Promoted From Short-Term Memory (2026-05-07)

<!-- openclaw-memory-promotion:memory:memory/2026-05-06.md:1:20 -->
- # Daily Memory — 2026-05-06 ## Context - Workspace memory audit performed. - Confirmed current state: `MEMORY.md` exists and is indexed; `memory/` was previously empty; dreaming is enabled in config. ## Findings - Short-term daily notes were missing before this file was created. - `DREAMS.md` was absent. - Dreaming recall/artifact state was empty at audit time. - Vector recall was degraded because sqlite-vec was unavailable. ## Actions taken - Created today’s daily memory file to restore the expected short-term note layer. - Updated `AGENTS.md` guidance so future turns explicitly maintain daily notes, long-term memory, and dream diary expectations. - Created `DREAMS.md` as the human-review surface for dreaming outputs. ## User intent - User asked to examine memory setup and then implement what OpenClaw should be doing for memory persistence. [score=0.804 recalls=10 avg=0.448 source=memory/2026-05-06.md:1-20]
