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
| **Neo-cloud / 3rd-party untenanted capacity** (HIGHEST OCI VALUE) | `sites` grouped by `provider_name`, hyperscalers excluded | "Crusoe has 3.3 GW untenanted, WY pipeline 100% open — offtake target." Rotate across Crusoe, CoreWeave, Lambda, Aligned, Compass, CyrusOne. |
| Document-grounded | `edgar_extractions`, `search_documents` | "Meta's 10-K confirms 9.7 GW AI capacity earmarked." |
| **Forward-looking guidance from earnings transcripts** | `earnings_transcripts`, `search_documents(source='earnings')` | "Microsoft Q2 call: CEO guides 'every dollar of FY26 capex going into AI-ready capacity'; sentiment_power_constraints=cautious — contradicts the cumulative MW-only read of the filings, raises forward execution risk for peer X." Must cite at least one `source="earnings"` passage. Use when management language on AI / power / capex **contradicts or amplifies** what filings say. |
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
3. **Common-knowledge test (CRITICAL).** Would a datacenter trade analyst already know this? Examples that automatically fail this test and must be dropped:
   - "AWS is concentrated in Northern Virginia / 40% in VA"
   - "Hyperscaler X has the largest total MW footprint"
   - "Meta is investing in AI infrastructure"
   - "Microsoft and Google are growing their datacenter footprints"
   - "PJM has long interconnection queues"
   The bar: show me something I cannot easily get from a trade publication or a basic SQL ranking. Static cumulative footprint comparisons usually fail this test.
4. **Defensive OCI ending.** Does the body close with "OCI should monitor / treat as strategic / be aware / consider"? If so, the OCI lens has not been applied — name a commercial consequence or replace the card.
5. **Already-said.** Does this card add something to the portfolio the existing cards don't? "Meta is dense per site" + "Meta is AI-weighted" + "Meta does behind-the-meter" is one finding restated three ways.

## Recency bias — bias every drill toward what's CHANGING, not cumulative state

Static metrics describe a state every analyst already knows. Decision-grade insights are about **what's changing this year, this quarter, this month.**

Bias every drill toward:

- **Latest-year filter on every query** — `issued_date >= '2026-01-01'` (permits), `event_date >= '2026-01-01' AND event_date <= CURRENT_DATE` (events; clamp the upper bound — future-dated rows are projections, not history), `period_end >= '2026-01-01'` (EDGAR). **`sites.announced_date` and `sites.construction_start_date` are NULL** in the DB now — use `events` joined on `aterio_dc_uid` instead. Cumulative views are only useful as denominators ("Z% is new this year").
- **Year-over-year deltas** — 2026 vs 2025: accelerating, decelerating, pattern break. "Microsoft permitted 4 GW in 2026 H1 vs 1.2 GW in 2025 H1" beats "Microsoft has 14 GW total."
- **Recent filings** — prefer 8-K (event-driven) and 10-Q (latest quarter) over 10-K (annual look-back) when surfacing power moves.
- **Movement, not stock** — who STARTED building this year, who PULLED OUT, who MOVED concentration from state X to state Y, who SIGNED a new PPA, who ABANDONED a queue position.
- **`events` table** — event-time-stamped, ideal for recency cuts. Use `events` for partnership / siting / offtake / vendor moves in the last 90 days.

When a static cumulative is the only available view, ALWAYS pair it with a recency cut: "X has Y total, Z% of which is post-2026" or "first-mover in nuclear PPAs (0 GW in 2025, 14.6 GW in 2026)." Never ship a bare cumulative.

## Aterio data quirks — respect these when reading `sites` and `events`

These shape what claims are defensible. Every one is observed on the current dataset; ignore them and you'll ship a wrong number.

1. **Milestone dates live in `events`, not on `sites`.** `sites.announced_date / construction_start_date / cancelled_date / project_withdrawn_date` are NULL in the DB (Aterio dropped them in May 2026). Any query that filters on those columns returns zero rows silently. Join `events e ON e.aterio_dc_uid = sites.aterio_dc_uid` and filter `e.event_type`.
2. **`events.event_date > CURRENT_DATE` is a PROJECTED milestone, not history.** Aterio emits forward-looking rows (e.g. `event_type = 'activation', event_date = 2029-03-31`) in the same shape as past ones. For historical metrics ("median time to activate", "sites activated this year") always clamp `event_date <= CURRENT_DATE`. For pipeline metrics ("scheduled to activate by 2027"), explicitly call out "projected" in prose.
3. **`pct_construction` is a 0–1.0 fraction, not 0–100.** Treating it as a percentage (e.g. `WHERE pct_construction >= 70`) silently returns zero rows. Multiply by 100 for display. Max value across the entire table is 1.0.
4. **`construction_start` is first-imagery-observed, not groundbreak.** For retrofit sites, the shell already existed, so Aterio's `construction_start` date can be late and `pct_construction` jumps from 0 → 50%+ within days (xAI Macroharder: 0 → 60% in 12 days). This is not a data bug — it's how Aterio measures. **Time-to-build distributions are polluted by retrofits.** AI-cohort median total (announce → active) is ~25 months; non-AI is ~32 months — but P10 builds <12 months are almost always retrofits, not heroic execution.
5. **Aterio does NOT label retrofit vs greenfield.** No structured column carries it. The data dictionary doesn't either. Don't slice by build type from SQL — you cannot. ~71 sites have explicit retrofit language in the free-text `notes` column; the other 7,100+ are unlabeled. If a question requires build-type segmentation, frame as a known gap, not a number.
6. **`construction_progress` is a new event type with percentage payload.** Multiple rows per site (one per imagery-detected milestone). `payload->>'pct_complete'` is the integer percentage (5, 10, 20, 30, 40, 50, 60, 70, 85, 90, 95). Powerful for "stuck at 30%+ for >6 months" / "construction velocity by operator" / "% complete distribution by region" — these slices are underused.
7. **Stage column vs event-derived stage are two different concepts.** `sites.stage` is Aterio's CURRENT declared stage (`Announcement / Construction / Active / Cancelled / Withdrawn / Delayed / Land Bank`). Event-derived stage (latest milestone ≤ year-end Y) is a reconstructed historical state. For "X% of sites under construction today" use `sites.stage = 'Construction'`. For "X% of sites were under construction at end-2024" reconstruct from `events`.

## OCI opportunity vs threat framing

Every insight must close with one of two labels: **OCI opportunity** or **OCI threat**. Both must name (a) an entity, (b) a window/timeframe, (c) a number or named action.

### Opportunity framings — name the target

- **Offtake target**: "Project X (developer Y) has N MW uncontracted as of [recent date] — viable OCI offtake target before Z next milestone."
- **Customer-acquisition target**: "Neo-cloud N just announced D GW with no named offtaker in [latest filing] — open conversation for OCI bare-metal."
- **Site arbitrage**: "Hyperscaler X just exited state Y queue → freed substation capacity — OCI can re-bid before queue refills."
- **Capacity arbitrage**: "Developer X has N MW of contractable phases at site Y, no offtaker named in 2026 filings — direct OCI counterpart conversation."

### Threat framings — name the risk

- **Vendor / supply lock-up**: "Vendor X just signed multi-GW capacity to peer Y in [date] — OCI's next D GW faces vendor contention through Q[N]."
- **Customer poaching**: "Customer X disclosed multi-GW commitment to peer Y in [latest filing] — OCI account at risk in [region]."
- **Region exclusion**: "Peer X absorbed N% of [state]'s 2026 substation queue — OCI's [region] expansion blocked through Q[N]."
- **Pacing gap**: "Peer X permitted N GW in 2026 H1 vs OCI's [public number] — competitive growth gap of D GW."

The label "**OCI opportunity:**" or "**OCI threat:**" should appear inline in the closing sentence so it's scannable. Generic "competitive read" framings without an entity / window / number fail.

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
