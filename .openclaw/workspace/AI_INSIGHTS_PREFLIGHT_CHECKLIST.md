# AI Insights Pre-Flight Checklist

Two checklists in this file:
1. **Per-card** — run before each `persist_insight` call (sections 1-11 below).
2. **Per-session** — run before `finalize_session` (the "Pre-finalize session audit" at the bottom).

## 0. Portfolio fit (run BEFORE drilling)

- Is this card filling a band the session is missing? (scale / forward-looking / customer-siting / document-grounded / OCI action)
- If the existing set already has the same protagonist, table, or angle, pick a different one.
- Cap reminder: max 2 cards per protagonist, max 2 cards per source table, ≥3 source families across the set, ≥1 forward-looking, ≥1 document-grounded, ≥1 OCI-actionable.

## 1. Scope check
- What exact question am I answering?
- Is this insight scoped to the current insight/session/fact pattern?
- Am I staying within the available evidence?

## 2. Hypothesis check
- What is the working claim?
- Is it falsifiable?
- What evidence would disprove it?

## 3. Evidence check
- Did I verify the key facts with tool results (`query_database`, `search_documents`, `build_chart`) or cited sources?
- Does every important numeric claim have support?
- Am I relying on an assumption I have not validated?

## 4. Structure check
- Is the analysis MECE?
- Did I separate demand, supply, permitting, timing, and OCI implication cleanly?
- Am I comparing like with like?

## 5. Alternative-explanation check
- What else could explain this signal?
- Did I test the strongest competing explanation?
- Am I overstating causality from correlation?

## 6. Hallucination guard
- Did I invent any MW, $, date, row id, source, or relationship?
- Did I imply certainty where the evidence is partial?
- If a tool failed, did I avoid guessing around it?

## 7. Communication check
- Does the headline state the answer, not the topic?
- Is the argument top-down and executive-readable?
- Did I lead with the conclusion, then grouped reasons, then evidence?

## 8. OCI actionability check (NOT awareness)
- Does the OCI sentence name a **commercial or strategic consequence** — contractable MW, named offtake target, region-specific siting risk, procurement bottleneck, customer-acquisition target, transmission/queue implication?
- **Banned endings** (auto-fail if present): "OCI should monitor", "OCI should treat as strategic", "OCI should be aware", "this is worth watching", "this matters for OCI".
- Does the OCI sentence name an **entity** (company, project, developer, ISO, state)? If not, it's vague — rewrite or replace.

## 9. Confidence check
- What is known?
- What is inferred?
- What remains unknown?
- Is the confidence level proportional to the evidence quality?

## 10. Disqualifier screen — DO NOT PERSIST if any apply
- **Caveat-as-headline.** Is this card primarily a coverage gap / schema quirk / warehouse warning? (e.g. "Oracle MW unusable for peer ranking") → drop. Caveats live in the body and `confidence` field, never the headline.
- **Baseline ranking with no novelty.** Is this just the most-obvious first ranking off the table? (e.g. "AWS has the most MW") → drop or sharpen with a novel angle.
- **Common-knowledge test (CRITICAL).** Would a datacenter trade analyst already know this from recent industry coverage? Auto-fail examples:
  - "AWS is concentrated in Northern Virginia / 40% in VA" → DROP
  - "Hyperscaler X has the largest total MW" → DROP
  - "Meta is investing in AI infrastructure" → DROP
  - "PJM has long interconnection queues" → DROP
  Bar: would this insight surprise or change the mind of a datacenter PM? If no → drop.
- **Static cumulative.** Is the headline a lifetime/cumulative number with no recency cut? → reframe as "what's new in 2026" or drop.
- **Defensive OCI lens.** Does the body close with "OCI should monitor / treat as strategic / be aware"? → rewrite the OCI sentence as an explicit opportunity or threat with entity + window + number, or drop the card.
- **Already-said.** Does this card add something the existing portfolio doesn't already say about the same protagonist? → drop.

## 10b. Recency / movement check
- Does this insight describe what's CHANGED in 2026, or just a cumulative state?
- Did the SQL include a `>= '2026-01-01'` (or last-90-days) filter on a date column?
- Is there a year-over-year delta (2026 vs 2025) that strengthens the claim?
- Static cumulative-only insights must be reframed with a recency cut or replaced.

## 10c. OCI opportunity-or-threat check
- Does the closing sentence carry an explicit "**OCI opportunity:**" or "**OCI threat:**" label?
- Does it name (a) an entity, (b) a window/timeframe, (c) a number or named action?
- "Competitive read" / "siting risk" / "market context" without those three components fails. Either tighten or drop.

## 11. Chart QA (BEFORE calling build_chart)
- Does the encoding match the analytical question, or is the chart restating the headline?
- Will category labels collide on the x-axis? (Multiple rows with the same category value → set `color` / `series` to disambiguate, e.g. `color: provider_name` when two hyperscalers are both top in VA.)
- Did you separate `category` and `series` dimensions when both exist?
- Is a `table` chart honestly better when the comparison is across >5 unrelated metrics?
- Does the title state the **finding** ("AWS leads PJM at 21.8 GW"), not just the **topic** ("PJM exposure")?

## 12. Final ship check
- Is this narrower and truer than the broader unsupported version?
- Would a skeptical analyst accept every important claim?
- If challenged on any sentence, can I point to the evidence?

---

## Pre-finalize session audit (run BEFORE finalize_session)

Review the run as a portfolio. Any "no" → replace the weakest card before finalize.

- ≥3 source families represented?
- ≤2 cards per protagonist?
- ≤2 cards per source table?
- ≥1 forward-looking card (permits / projects / filings, not static `sites` snapshot)?
- ≥1 document-grounded card (`search_documents` or `edgar_extractions` cited in body)?
- ≥1 explicitly actionable OCI card (named offtake target / procurement bottleneck / customer / region risk)?
- No card whose headline is a coverage caveat?
- No two cards saying the same thing about the same protagonist?
- Every insight has a chart bound via FK?
- Every chart's title is a finding sentence (not a topic label)?

If any check fails, drill a fresh hypothesis, persist + chart it, then call `finalize_session`. Portfolio integrity > five individually-passable cards.

## Per-card scoring rubric (for tie-breaking)

Score 1-3 across:
- Evidence strength (grounded in tool results, not interpretation)
- Novelty (not the first obvious ranking)
- OCI actionability (names a commercial consequence)
- Set diversity contribution (adds what's missing)
- Chart clarity (encoding ↔ claim, readable labels, finding title)

Cards weak (1) on 2+ dimensions are drops, not ships.
