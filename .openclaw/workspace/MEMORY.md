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

(no current entries)

## Recurring questions / decision patterns

_The kinds of questions the user keeps asking about. Helps you
anticipate the next one._

(no current entries)

## Platform quirks worth knowing

_E.g. "FactPack section X is empty most days because adapter Y
upserts without bumping `updated_at`." Concrete, actionable._

(no current entries)

## User preferences observed

_Specific phrasings, units, levels-of-detail the user has
reacted positively / negatively to. Cross-checks what's in
USER.md, but USER.md is intent; this is observation._

(no current entries)

## Threads to revisit

_Open questions where the answer wasn't yet available. When new
data lands, come back here and resolve them._

(no current entries)

---

_Last reviewed: (initial seed; agent should refresh this line each time MEMORY.md is materially updated)_
