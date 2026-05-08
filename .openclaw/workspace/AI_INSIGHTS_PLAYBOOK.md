# AI Insights Playbook

This file defines the default operating method for generating AI insights in the OCI Datacenter & Power Intelligence Platform.

## Standing rule

Always use structured research and data-analysis techniques when generating AI insights.

Do not generate insights as freeform narrative first. Start from a question, hypothesis, or anomaly, then test it against grounded evidence.

## Portfolio construction (run-level, not card-level)

Treat each session as a **portfolio** of complementary cards, not five individually passable findings. Five variants of the same `sites` story is not a session — it is one finding restated.

### Required mix per 5-insight session

Aim for one card from each band:

| Band | Source surface | Example hypothesis |
|---|---|---|
| Scale / concentration | `sites` | "Hyperscaler X owns N% of state Y MW." |
| Forward-looking power supply | `generator_permits[source='pjm']`, `energy_projects` | "Queue attrition: 723 GW withdrawn vs 70 GW active in PJM." |
| Customer / operator / siting | `sites` + `events`, `companies` | "Crusoe is concentrating siting in TX with X named offtakers." |
| Document-grounded | `edgar_extractions`, `search_documents` | "Meta's 10-K confirms 9.7 GW AI capacity earmarked." |
| OCI action | any, but body must name a commercial next step | "Fermi America has 10.4 GW uncontracted at site Z — offtake target." |

### Hard caps

- **≥3 distinct source tables/corpora** across the set.
- **Max 2 insights per protagonist** (company, state, ISO).
- **Max 2 insights per source table** unless the user explicitly asked for a one-table cut.
- **≥1 forward-looking card** (permits, queue, projects, filings — not a static `sites` snapshot).
- **≥1 document-grounded card** (`search_documents` or `edgar_extractions` cited in the body).
- **≥1 OCI action card** that names a contractable MW / offtake target / procurement bottleneck / customer target — not a "monitor / watch / be aware" framing.

## Disqualifier screen — do not persist if any apply

Before calling `persist_insight`, run this gate. Any "yes" → drop the card and pick a new hypothesis instead.

1. **Caveat-as-headline.** Is this card primarily about coverage gaps, schema quirks, or warehouse warnings? Coverage caveats belong in the body and the `confidence` field, never in the headline. Example: "Oracle MW unusable for peer ranking" is data hygiene, not an insight — fix the comparison axis instead.
2. **Baseline ranking with no novelty.** Is this just the most-obvious first ranking off the table? "AWS has the most MW" is table-stakes; "AWS is more state-concentrated than peers, with X% in VA" is novel.
3. **Defensive OCI ending.** Does the body close with "OCI should monitor / treat as strategic / be aware / consider"? If so, the OCI lens has not been applied — name a commercial consequence or replace the card.
4. **Already-said.** Does this card add something to the portfolio the existing cards don't? "Meta is dense per site" + "Meta is AI-weighted" + "Meta does behind-the-meter" is one finding restated three ways.

## Hypothesis-driven branching, not opportunistic ranking

Do NOT start from "what can I rank from `sites`?". Start from one of these analytical postures:

- Which hyperscaler is most exposed to a single ISO / utility / power market — and what's the bottleneck?
- Where is uncontracted or weakly-attributed pipeline most likely to become OCI-relevant in the next 6 months?
- Which players are solving grid bottlenecks via onsite generation or alternative procurement — and what does that signal?
- Which named LLCs / developers are recurring across permits + filings + events — i.e. who is *actually* building, not just announcing?
- Which states / counties are concentrating multi-tenant developer exposure where OCI could co-site?

Then query to **confirm or falsify**. A confirmed hypothesis is a stronger insight than a backwards-derived narrative from a ranking.

## Core operating sequence

For each AI insight, use this sequence:

1. **Question**
   - What exact question is being answered?
   - What decision would this insight support?

2. **Hypothesis**
   - Form a falsifiable working claim.
   - Example: a player is accelerating in a state because power supply loosened, not because land became available.

3. **MECE structure**
   - Break the problem into non-overlapping buckets.
   - Typical buckets:
     - demand signal
     - power availability
     - siting/permitting
     - capital/vendor signal
     - timing
     - OCI implication

4. **Evidence pull**
   - Pull only the evidence needed to test the claim.
   - Prefer platform-grounded evidence first:
     - Postgres rows from `query_database`
     - chart data from `build_chart`
     - filing/permit passages from `search_documents`
     - rows or passages cited by prior insights in this session
   - Use web research when it adds market context, confirmation, or communication technique.

5. **Alternative explanations**
   - Ask what else could explain the observed signal.
   - Do not stop at the first plausible narrative.

6. **Quantification**
   - Verify every important numeric claim.
   - If a number is not in a tool result or citation snippet, do not state it as fact.
   - Use sensitivity/scenario framing when source coverage is partial.

7. **OCI implication — name the commercial consequence**
   - End with the so-what for OCI in **action terms**, not awareness terms.
   - **Banned endings:** "OCI should monitor…", "OCI should treat as strategic", "OCI should be aware", "this is worth watching".
   - **Required framings — pick one and name the entity / geography / consequence:**
     - Contractable MW: "Project X (developer Y) has N MW uncontracted in state Z — offtake exposure for OCI."
     - Region-specific siting risk: "VA substation queue is dominated by AWS through Q3 2027 — OCI's incremental VA buildout faces N-month transmission lag."
     - Competitor concentration risk: "Meta now operates X% of the AI-flagged MW in the warehouse — OCI's AI-data services compete on a smaller addressable base than headline cloud-share suggests."
     - Procurement implication: "Vendor X holds A/B/C contracts across hyperscalers Y/Z — OCI will face vendor-capacity contention on its next M GW."
     - Customer-acquisition target: "Neo-cloud N has just announced D GW with no named offtaker in the latest 8-K — viable conversation for OCI bare-metal."
     - Transmission/substation bottleneck: "ISO X queue attrition is N% in 2026 — OCI's pipeline assumptions in territory Y need a 0.6× haircut."

8. **Confidence discipline**
   - Separate:
     - known from evidence
     - inferred from pattern
     - unknown / not yet supported

## Required analysis techniques

Use these by default when relevant:

### 1. Hypothesis-driven analysis
Start with a claim that can be supported or falsified.

### 2. MECE structuring
Avoid overlapping categories and mixed logic.

### 3. Segmentation
Compare like with like:
- hyperscaler vs neocloud
- announced vs under construction vs operational
- state / county / ISO / utility territory
- contracted vs uncontracted supply

### 4. Sensitivity / scenario analysis
When a conclusion depends on uncertain assumptions, show what changes if the assumption moves.

### 5. Root-cause analysis
For anomalies or directional changes, ask what mechanism likely drove the shift.

### 6. Executive communication
Use top-down communication:
- lead with the answer
- support with 2–4 grouped reasons
- then give evidence
- finish with OCI implication

## Anti-hallucination rules

1. Never start with a polished story before checking evidence.
2. Never invent MW, $, dates, row ids, or company relationships.
3. Never imply database support without a tool result.
4. Mark inference as inference.
5. If evidence is partial, say what is known and what is missing.
6. If a tool errors, do not guess around it.
7. Prefer a narrower true claim over a broader unsupported one.
8. For quantitative questions, reach for numbers first, language second.

## Calibrated inference (READ BEFORE REFUSING TO ANSWER)

You are a professional analyst, not a transcriber. Inference is your
job — but every inference must be **labeled** so the reader knows what
is fact vs interpretation.

**Default behavior when evidence is partial:**

- Make the best-supported inference and ship it.
- Hedge with markers: "likely", "appears to", "suggests", "consistent
  with", "if the X pattern holds, then Y".
- State what would falsify or strengthen the inference: "a named
  offtaker in the next 8-K would change this read."
- If you have ZERO supporting tool results, say so explicitly and
  point at what to drill next — do not refuse silently.

**Forbidden patterns (these signal failure, not professionalism):**

- "I cannot determine without more information." (Wrong — make the
  inference, label it, name what would sharpen it.)
- "Without seeing X, I can't say." (Wrong — say what X probably is
  given Y, mark as inference.)
- Listing five hedges in a row before any actual claim. (Wrong —
  lead with the claim, follow with one calibrated caveat.)
- Stopping at "the data is insufficient" when you have ANY tool
  result. (Wrong — what the data DOES show, plus what's missing.)

**Inference > refusal.** A "likely" answer with one citation beats a
"I don't know" with five hedges. Stating something as inference IS
professional; refusing to engage is not.

**Inference != fabrication.** Never state an unverified number, date,
relationship, or row_id as fact. The whole point of marking inference
is to keep the fact/interpretation line clean — cross it and you've
just hallucinated.

## Hard exception: NEVER infer when generating SQL

The calibrated-inference rule above applies to **analytical claims**.
It does NOT apply to **SQL identifiers**. When you write SQL:

- **Use only table and column names verified in `SCHEMA.md`.** If you
  haven't read SCHEMA.md this session, read it first. If a column you
  want isn't documented there, abandon that query — do NOT guess
  plausible names like `capacity_mw`, `customer_name`, `parent_company`.
- **No inference, no "likely the column is called...", no patterns from
  similar databases you've seen.** SCHEMA.md is the only source of
  truth for our schema.
- **If the column you need isn't in SCHEMA.md**, three valid moves
  (in order):
  1. Pick a different column from SCHEMA.md that answers a related
     question and ship that instead.
  2. Use a `search_documents` call against EDGAR / permits to source
     the same fact from text rather than structured data.
  3. Drop the hypothesis and pick a different one — empty SQL trumps
     wrong SQL.
- **`UndefinedColumn` / `UndefinedFunction` errors are agent failures**,
  not data gaps. Each one wastes a tool call. After ONE such error,
  re-read the relevant table in SCHEMA.md before trying again.

This rule overrides the inference encouragement in the section above
when the two collide. Inference is for what the data MEANS; the
schema is what it IS.

## Preferred output shape for insights

1. Headline: the answer, not the topic
2. Why it matters: 1–2 sentences
3. Evidence: grouped, numeric, specific
4. Alternative explanation or caveat: if material
5. So what for OCI: explicit

## Communication rules

- Be consultative, not hedging.
- Be concise, but not thin.
- Avoid filler and throat-clearing.
- Use active voice.
- Use the user’s units: MW, GW, $M, $B, %.
- Do not use vague terms when a precise one is available.

## Chart QA before accepting a card

Before issuing `build_chart`, mentally check:

1. **Encoding ↔ question fit.** Is the chart answering the analytical question, or just restating the headline number? A `kpi_tile` of the headline is restating; a `bar` chart of the breakdown is answering.
2. **Label collision.** Will category labels collide on the x-axis when multiple rows share a value? (E.g. two hyperscalers both top-state in VA → without `color: provider_name` the labels mash to "VAVA" or similar.) Set `color` / `series` to disambiguate.
3. **Series vs category.** If a row has both a category and a series dimension, did you set `color` / `series` rather than collapse them?
4. **Table vs chart.** When the comparison spans >5 unrelated metrics, a `table` chart is honestly better than a stacked bar.
5. **Title states the finding, not the topic.** "AWS leads PJM at 21.8 GW" beats "PJM exposure". The title is a sentence, not a label.

## Pre-finalize portfolio audit

Before calling `finalize_session`, review the run as a portfolio:

- ≥3 source families represented?
- ≤2 cards per protagonist?
- ≤2 cards per source table?
- ≥1 forward-looking card?
- ≥1 document-grounded card?
- ≥1 explicitly actionable OCI card?
- No card whose headline is a coverage caveat?
- Every insight has a chart bound via FK?

If any check fails, **replace the weakest card** before finalizing. Drill a fresh hypothesis, persist + chart it, then call `finalize_session`.

## Per-card scoring rubric

For each candidate insight, score 1-3 across:

- **Evidence strength** — grounded in real rows / docs, not interpretation.
- **Novelty** — not the first obvious ranking off the table.
- **OCI actionability** — names a commercial / strategic consequence with an entity or geography.
- **Set diversity contribution** — adds something the existing cards don't.
- **Chart clarity** — encoding fits the claim, labels readable, title is a finding.

Anything weak (1) on 2+ dimensions should be dropped, not shipped.

## Continuous improvement

When reflection finds a recurring mistake, add or refine a rule here or in durable memory.
