# PRD: Earnings Call Transcripts

**Status:** Approved for implementation
**Owner:** PM (strategic-insights-tool)
**Engineering plan:** `/home/ubuntu/.claude/plans/i-want-to-include-dynamic-summit.md`
**Target release:** Phase 2 ingestion + Earnings tab
**Last updated:** 2026-05-12

> This PRD frames the product intent and acceptance bar. It intentionally does
> not duplicate the engineering plan — refer to that plan for schema, file
> paths, scheduler wiring, and verification steps.

---

## Overview

The strategic-insights-tool today grounds its agentic reasoning in SEC filings
(10-K / 10-Q / 8-K), county permits, and a small set of curated tables. These
sources are authoritative but lagging — they describe what hyperscalers and
power players have already committed to, not what management is signaling
they will commit to next quarter.

This feature adds quarterly earnings call transcripts (via Alpha Vantage) as
a first-class data source: ingested with the same adapter discipline as
EDGAR, chunked into a BM25-searchable passage table, structured-extracted by
an LLM, and surfaced both in a dedicated "Earnings Calls" tab and inside
each company's detail panel. The synthesis agent gains a new
`source="earnings"` branch on `search_documents` so it can cite transcript
quotes alongside filings.

---

## Problem Statement

Filings tell us what has happened. Earnings calls tell us what is about to
happen. Three concrete gaps in the current pipeline:

1. **Forward-looking capex guidance is invisible.** Hyperscaler capex
   intentions are first disclosed verbally on the earnings call, often 4–8
   weeks before the 10-Q makes it explicit. The synthesis agent currently
   has no way to ground an OCI-vs-hyperscaler insight in next quarter's
   intent.
2. **Power-supply and grid-constraint commentary lives in Q&A, not filings.**
   Analyst questions on grid interconnect timelines and PPA economics draw
   the most candid management answers; none of that surfaces in 10-Q risk
   factors until much later (if at all).
3. **Competitive framing (who is winning AI workloads) is rarely written
   down.** Management routinely names competitors and characterizes wins
   and losses on earnings calls in ways their filings never will.

Without these inputs, the synthesis agent biases toward backwards-looking
"executed commitments" portfolio cards and under-produces the
forward-looking opportunity/threat cards that internal analysts actually
need for OCI positioning conversations.

---

## Target Users

**Primary:** Internal OCI analysts using the strategic-insights-tool to
brief leadership on hyperscaler datacenter / power buildout dynamics and
OCI's relative positioning. They consume the Companies tab, the AI Insights
tab, and (with this feature) the Earnings Calls tab.

**Secondary:** The synthesis agent itself, which reads workspace docs and
calls `search_documents` to ground every portfolio insight. Earnings
transcripts become a new citation source it can pull from.

Out of audience for this release: external customers, sales engineers,
non-OCI consumers of the tool.

---

## Goals

- Ingest the most recent earnings call transcript for every US-public
  company in `TRACKED_FILERS` (~35 companies), refreshed daily off the
  earnings calendar so new calls appear within 1–2 days of being held.
- Make every transcript BM25-searchable through the same
  `search_documents` agent tool that already serves EDGAR.
- Surface structured highlights (guidance, capex mentions, AI/power
  mentions, competitive mentions, MW-capacity mentions) and four-axis
  sentiment (AI demand / power constraints / datacenter capex / overall)
  per transcript.
- Give analysts a dedicated "Earnings Calls" tab with company / quarter /
  sentiment filters, plus a per-company timeline inside the existing
  CompanyDetailPanel.
- Enable the synthesis agent to cite `source="earnings"` passages in
  AI insights, especially forward-looking ones.

## Non-Goals

(Mirrors Part 7 of the engineering plan.)

- Real-time or streaming transcript ingestion — Alpha Vantage delivers
  post-call only.
- Foreign filers (e.g., TSMC, ASE) — these need a different provider and
  are explicitly excluded from the ticker resolution step.
- Audio analysis of the actual call recording (tone of voice, hesitation,
  speaker stress).
- Backfilling more than 4 quarters of history on first run — start at the
  last 90 days and let the calendar-driven refresh fill forward.
- Any modification of the existing EDGAR / permits / insights pipelines.
  The earnings pipeline is strictly additive.

---

## User Stories

### US-1: Browse the earnings feed
**As an** internal analyst,
**I want** a chronologically ordered feed of recent earnings calls across
all tracked companies,
**so that** I can quickly scan for last week's calls and spot which
companies sounded bullish vs cautious on AI / power / capex.

**Acceptance criteria:**
- Earnings Calls tab is accessible from the main nav after Supplier.
- Feed defaults to `call_date DESC` and shows at least the last 30 days of
  calls (when available).
- Each card displays: ticker, company name, quarter (e.g., `2026Q1`),
  call date, three sentiment badges (AI demand / power / datacenter capex)
  with green/amber/red/gray color coding, one top quote (≤140 chars), and
  a CitationFooter showing `retrieved_at` and source = "Alpha Vantage".
- Empty state renders cleanly when no transcripts exist yet.

### US-2: Filter the feed by company, quarter, and sentiment
**As an** analyst preparing a brief on a specific company or quarter,
**I want** to filter the feed by company, quarter, and sentiment axis,
**so that** I can isolate the calls relevant to my current question
without scrolling.

**Acceptance criteria:**
- Company multi-select is populated from `TRACKED_FILERS` (US-public
  subset).
- Quarter filter offers at least the last 4 calendar quarters.
- Sentiment-axis toggle lets the user select one of {AI demand, power
  constraints, datacenter capex, overall} and filter to a sentiment value
  (bullish / cautious / bearish).
- Filters compose (AND) and are reflected in the API call via querystring.
- Clearing all filters returns to the default feed view.

### US-3: Drill into a transcript's structured highlights
**As an** analyst investigating a specific call,
**I want** to expand a card and see the LLM-extracted highlights grouped
into Guidance / Capex / AI & Power / Competitive / MW Capacity,
**so that** I can pull exact management quotes into my brief without
reading the full transcript.

**Acceptance criteria:**
- Clicking a card opens a modal with five labeled sections.
- Each extracted item shows the verbatim quote in a monospace block with
  speaker attribution (CEO / CFO / analyst name when available).
- The modal links to the upstream `transcript_url` at the bottom.
- Modal closes via Escape, backdrop click, and an explicit close button.
- Sections with zero extracted items are hidden (not shown empty).

### US-4: See a company's earnings history in its detail panel
**As an** analyst already looking at a company in the Companies tab,
**I want** an "Earnings Calls" section inside the CompanyDetailPanel
showing every transcript we have for that company,
**so that** I do not have to switch tabs to see the trajectory of
management commentary over time.

**Acceptance criteria:**
- CompanyDetailPanel adds a fourth section (after Filings / Sites /
  RoleSummary) titled "Earnings Calls".
- Renders as a compact timeline: date | quarter | overall sentiment badge
  | one-line headline from `guidance`.
- Rows are clickable and open the same expanded modal used in
  EarningsTab.
- If no transcripts exist for the company, the section shows a single
  "No earnings transcripts yet" placeholder (not hidden silently).

### US-5: Search transcripts via the agent
**As the** synthesis agent (and indirectly, an analyst running an
ad-hoc agent query),
**I want** `search_documents(source="earnings")` to return BM25-ranked
passages with citation metadata,
**so that** I can ground forward-looking insights in management quotes.

**Acceptance criteria:**
- `ALLOWED_SOURCES` includes `"earnings"`.
- `search_documents(query, source="earnings", k=N)` returns up to N
  passages ranked by `ts_rank_cd` against
  `websearch_to_tsquery('english', query)`.
- Each result carries the standard citation envelope with
  `source="earnings"`, `company`, `filing_type` = `earnings_call_{quarter}`,
  `url`, `retrieved_at`, `passage_id`, `speaker`, and `section`.
- `source="all"` merges EDGAR, permits, and earnings results and re-ranks
  by score.

### US-6: AI insights cite earnings transcripts
**As an** analyst reviewing the AI Insights tab,
**I want** at least one insight per week to cite an earnings transcript
passage when forward-looking commentary supports the claim,
**so that** I can trust the agent is using the freshest available
signal, not just lagging filings.

**Acceptance criteria:**
- Synthesis prompt and AI_INSIGHTS_PLAYBOOK include an explicit card type
  for forward-looking guidance grounded in transcripts.
- A weekly check (manual at first; automated later) confirms ≥1 insight
  in the past 7 days has at least one citation with `source="earnings"`.
- Citations render with the speaker and quarter visible to the analyst
  in the existing insight card UI.

### US-7: Pipeline freshness is visible
**As an** analyst, when I see a stale or missing transcript,
**I want** to know when the adapter last ran and what its coverage looks
like,
**so that** I can tell whether the gap is a data issue or just that the
company has not reported yet.

**Acceptance criteria:**
- `ingestion_runs`, `data_coverage`, and `data_lineage` are populated by
  the earnings adapter on every run (success and failure).
- `.openclaw/workspace/FRESHNESS.md` lists `earnings_transcripts` with
  cadence and last-refresh semantics.
- The Earnings tab's CitationFooter exposes the most recent
  `retrieved_at` for whatever the user is viewing.

---

## Functional Requirements

The engineering plan (Parts 1–3) is the source of truth. Highlights for
PRD-level scope confirmation:

**Ingestion (Plan Part 1):**
- New tables `earnings_transcripts` (parent) and `earnings_passages`
  (BM25 chunks), migration `019_earnings_transcripts.py`, mirroring the
  shape of `edgar_extractions` / `edgar_passages`.
- New adapter `EarningsTranscriptsAdapter` conforming to the existing
  `DataSourceAdapter` protocol, with raw-JSON cache (12h TTL), idempotent
  `(cik, quarter)` upsert, and rate-limited Alpha Vantage calls.
- Speaker-aware chunker targeting ~500 tokens (hard cap 800) per passage,
  preserving Q&A turn boundaries and tagging `section` as
  `prepared_remarks` or `q_and_a`.
- Single-pass LLM extractor (`earnings_extractor.py`) producing
  guidance / capex_mentions / ai_power_mentions / competitive_mentions /
  mw_capacity_mentions plus four-axis sentiment, with substring quote
  validation to prevent hallucinated citations.
- Daily scheduler job `earnings_transcripts_daily` at 06:45 UTC, gated
  internally by the Alpha Vantage earnings calendar.

**Agent integration (Plan Part 2):**
- `search_documents` extended with an `earnings` branch (and merged into
  the `all` branch).
- Workspace docs updated: `SCHEMA.md`, `FRESHNESS.md`,
  `AI_INSIGHTS_PLAYBOOK.md`, and the synthesis prompt's
  `synthesis_rules.md`.

**API + UI (Plan Part 3):**
- Three endpoints under `/api/earnings` and
  `/api/companies/{id}/earnings`, all using the standard
  LineageEnvelope / CoverageEnvelope shape.
- New tab `EarningsTab.tsx` with filters, card feed, and expanded modal.
- New section inside `CompanyDetailPanel` rendering a per-company
  timeline that opens the same modal.

---

## Success Metrics

Measured 30 days after first production run.

| Metric | Target |
|---|---|
| Transcript coverage | 100% of US-public `TRACKED_FILERS` have ≥1 transcript ingested within 30 days of the feature shipping. |
| Refresh latency | New transcripts appear in the feed within 48 hours of the call being held (assumes Alpha Vantage publishes within 24–36 hours). |
| Agent adoption | ≥1 AI insight per week cites at least one `source="earnings"` passage. |
| Extraction quality | <5% of extracted highlights fail substring validation against `raw_text` (these are dropped and logged). |
| Pipeline reliability | `earnings_transcripts_daily` succeeds on ≥95% of scheduled runs over a rolling 14-day window (failures logged to `ingestion_runs`). |
| API performance | `/api/earnings` p95 latency under 400ms for a 20-card page. |
| Cost | LLM extraction cost ≤ $5/year (planned: ~$2.80/year at 35 companies × 4 quarters × Sonnet pricing). |

---

## Open Questions & Risks

**Open questions**

1. **Alpha Vantage transcript coverage for smaller utilities and IPPs.**
   Hyperscalers are reliably covered; less certain for some independent
   power producers in `TRACKED_FILERS`. Need a coverage probe in week 1
   and a fallback plan if any tracked US-public company is missing.
2. **Sentiment axis taxonomy stability.** The four axes
   (ai_demand / power_constraints / datacenter_capex / overall) are a
   first guess. Should the analyst UX expose a fifth axis (e.g.,
   "regulatory")? Defer until we have 30 days of real labels to inspect.
3. **Speaker normalization.** Alpha Vantage's speaker strings are not
   canonical (e.g., "Jensen Huang – CEO" vs "Jensen Huang, Chief
   Executive Officer"). Decide whether to normalize at ingest time or
   only at display time. Plan currently does the latter implicitly.
4. **Re-extraction policy.** Plan re-runs extraction if a transcript is
   older than 30 days without a re-extraction marker. Is that the right
   threshold once the prompt stabilizes? Revisit after one full quarter.
5. **`source="all"` ranking.** Cross-source BM25 scores are not strictly
   comparable. Acceptable for v1; revisit if analysts report earnings
   passages crowding out filings (or vice versa) in agent grounding.

**Risks**

- **Alpha Vantage free-tier ceiling (25 calls/day).** Mitigated by
  calendar-gated fetching, but a backfill misstep could blow the budget
  in a single morning. Adapter must enforce a daily call counter and
  short-circuit when near the limit.
- **API key handling.** `ALPHA_VANTAGE_API_KEY` lives only in env. Risk
  of accidental commit; mitigated by adding it to `.env.example` (key
  blanked) and never logging it.
- **LLM hallucinated quotes.** Defended by substring validation, same
  approach as `validate_buyer()` in `edgar_extractor`. Risk remains for
  paraphrase-style fields (e.g., `dollar_amount` parsed from a quote);
  these should be re-validated by a unit test on a known-good
  transcript.
- **Synthesis prompt regression.** Adding a new citable source can shift
  the agent's portfolio mix. Mitigated by keeping changes additive
  ("acceptable source alongside EDGAR") and watching the existing
  portfolio-quality preflight checks for regressions.
- **Schema drift between EDGAR and earnings passage tables.** The two
  tables are intentionally parallel; future changes to one should be
  mirrored. Add a brief note to `SCHEMA.md` so future contributors do
  not accidentally diverge them.

---

## References

- Engineering plan: `/home/ubuntu/.claude/plans/i-want-to-include-dynamic-summit.md`
- Canonical adapter to mirror: `backend/ingestion/edgar.py`
- Canonical extractor to mirror: `backend/agents/edgar_extractor.py`
- Search tool being extended: `backend/agents/insights/tools/search_documents.py`
- Workspace orientation docs the agent reads:
  `.openclaw/workspace/SCHEMA.md`, `FRESHNESS.md`,
  `AI_INSIGHTS_PLAYBOOK.md`
