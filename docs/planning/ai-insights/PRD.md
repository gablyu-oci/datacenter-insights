# PRD — AI Insights Tab
**Owner:** Strategic Insights team (OCI) · **Stakeholder:** Karan
**Status:** Draft v0.2 — **Track B (V2) implementation landed 2026-05-04** · **Date:** 2026-05-04
**Cross-refs:** [`./RESEARCH.md`](./RESEARCH.md) · [`./ARCHITECTURE.md`](./ARCHITECTURE.md) · [`./UX.md`](./UX.md) · [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) · [`./TASKS.md`](./TASKS.md)
**Parent PRD:** [`/strategic-insights-tool/PRD.md`](../../../PRD.md)

> **Track B / V2 status (2026-05-04):** ✅ shipped — web search (Brave-primary; Tavily *not* used as fallback in V2 per kickoff override of RESEARCH §1.3), `emit_citation` with substring + GW/MW/%/$ numeric gate, agree/disagree judge (gpt-5.4-mini, low effort), per-insight chat dock + SSE endpoints, 3 V2 skills (cohort-analysis, methodology-explainer, peer-review-template), tool-call cap raise (insight-discovery 12×4 → 20×4 = 80; chat stays 12×4 = 48), citation hover-card UX, low-external-support pill, V2 feature flag, `web_search_unavailable` banner. Skill registry now **15** (12 V1 + 3 V2). Alembic 011 dry-run clean. 27/27 V2 pytest pass. See [TASKS.md §T8](./TASKS.md#t8-v2-backlog-high-level) for the per-item ship table.

---

## 0. TL;DR

Add a 10th tab — **AI Insights** — where an LLM agent on OCI Llama Stack autonomously surveys the platform's existing data and produces 5–10 supported insights per session. Each insight ships with a Recharts visualization, 2–5 web-citation supports, and a chat thread for follow-up. The agent uses a curated subset of 14–17 Claude Code data-analytics skills, plus seven existing platform tools (`query_database`, `call_api`, `get_chart_data`, `web_search`, `run_skill`, `emit_chart`, `emit_citation`). V1 ships read-only, batch-generated, no-chat in 4–6 weeks; V2 adds chat + web-search in +3–4 weeks; V3 adds scheduled re-runs + insight-diff in +2–3 weeks. Phased exits at each step.

---

## 1. Background & Problem

### 1.1 Why now

The platform today (per [parent PRD §2](../../../PRD.md) and [`docs/planning/DEMO_BRIEF_2026-05-01.md`](../DEMO_BRIEF_2026-05-01.md)) ships **9 tabs and 22 routers** of competitive-intel data: 6,973 sites, 1,247 companies, 4,150 generator permits, 345 building permits, 88 EDGAR-extracted rows, 23 curated power deals, plus a live L1/L2 triangulation model. **The data is there. The interpretation is not.** Karan currently has to:

1. Open each tab in turn,
2. Eyeball the chart for anomalies,
3. Switch to a separate browser tab to corroborate against industry coverage (SemiAnalysis, Reuters, etc.),
4. Decide whether the signal is real.

That loop is the gap. **The platform produces facts; it does not produce findings.** Strategy work is the synthesis on top — and synthesis is exactly what an LLM with tool access is well-suited for, *if* it is constrained to the actual data and *if* every claim is provenance-tagged.

### 1.2 Relationship to existing agents

| Existing agent | Scope | What's different about AI Insights |
|---|---|---|
| **`weekly_brief`** ([`backend/agents/weekly_brief.py`](../../../backend/agents/weekly_brief.py)) | Sunday 23:00 UTC card; 5–10 bullets of *what changed last week* | Time-bounded, narrative-only, no charts, no follow-up. AI Insights is *atemporal* (full DB surface), produces charts, and supports drill-down. |
| **`triangulation_qa`** | User-initiated chat, scoped to triangulation L1/L2 | Reactive (you have to ask a question). AI Insights is *proactive* (surfaces what to ask about). |
| **`datacenter_qa`** | User-initiated chat, scoped to sites/permits | Same — reactive, single-pillar. AI Insights spans all 9 tabs. |

**The gap closed:** Karan opens the tool on Monday morning, lands on AI Insights, and sees 5–10 fresh, supported claims about the data — claims he didn't have to formulate. He clicks the strongest one, opens the chat, and pushes back. The reactive agents stay; AI Insights complements them as the *proactive surface*.

### 1.3 Why an *agent* and not a query builder

A static dashboard of "top 10 anomalies" is achievable today with anomaly_detector outputs. The reason for an agent is that *insights are not anomalies*. An insight is "Oracle is the only hyperscaler whose contracted-GW lead is concentrated in renewables (10/11.6 GW), implying a different financing posture than Amazon/Microsoft" — a **claim that requires combining multiple tabs, looking up external context, and judging materiality**. That synthesis step is not pattern-match; it is reasoning over heterogeneous sources, which is what LLM tool-use is for.

---

## 2. Goals (V1)

| # | Goal | Measurable |
|---|---|---|
| G1 | Per session, the agent produces **5–10 distinct, non-trivial insights** drawn from the platform's existing data | Count + dedup rate (no two insights share >70% n-gram overlap) |
| G2 | **≥80% of insights are accompanied by a Recharts chart** that is non-trivially derived from the data (not a "single number with units") | Manual review of 20 dogfood sessions |
| G3 | **Every insight has provenance**: data-sources used, skills run, generated-at timestamp, confidence | 100% — enforced by emit-time schema validation |
| G4 | **Karan rates ≥40% of insights "useful"** in dogfood (5-point scale, useful = 4 or 5) | Capture rating in-product; weekly review |
| G5 | Insight generation completes in **≤3 minutes p50, ≤8 minutes p95** per session | Server-side timing; logged to `llm_extraction_runs` |
| G6 | **Zero hallucinated tables/columns** — agent never references DB objects that don't exist | Strict whitelist via introspection; failed calls logged |

V2 adds:
- G7: ≥75% of insights ship with **2–5 web-search citations**, each tagged agree/disagree.
- G8: Each insight supports a **chat follow-up thread** persisted across sessions.

V3 adds:
- G9: Scheduled re-runs (weekly) with **insight-diff** vs prior run.
- G10: Subscribe/notify on a saved insight (e.g., "tell me when Oracle's gap-vs-implied changes by >20%").

---

## 3. Non-goals

| # | Non-goal | Rationale |
|---|---|---|
| N1 | **No write access to the database** | Agent is strictly read-only. Mutations stay in the ingestion pipeline. |
| N2 | **No model fine-tuning** | OCI Llama Stack hosts the models; we use them as-is. Prompt-engineering only. |
| N3 | **No real-time / streaming insight regeneration** | Sessions are batch. Streaming protocol within a session (token-by-token UI) is acceptable; continuous re-eval is not. |
| N4 | **Does not replace any existing tab** | Strictly additive; existing Power, Triangulation, Companies, Permits etc. tabs are unchanged. Per [parent PRD §S5](../../../PRD.md), the rule is additive-only. |
| N5 | **No automated trading / external alerting** | Per [parent PRD §10](../../../PRD.md). |
| N6 | **No cross-customer learning** | Each session is stateless aside from per-session insight + thread persistence. |
| N7 | **Not a replacement for `weekly_brief`** | Weekly brief is time-bounded narrative for execs; AI Insights is open-domain analytical surface. Both ship. |
| N8 | **No PDF / email export in V1** | Deferred to V3 if Karan asks. |
| N9 | **No multi-user collaboration features (comments, sharing, ACLs)** | Per [parent PRD §8 Decision 5](../../../PRD.md): no auth in v1, internal-only. |

---

## 4. Users & Use Cases

### 4.1 Karan (exec sponsor)

> *Monday morning. He opens the tool, lands on AI Insights. Sees: "Oracle's contracted-renewable share (86%) is 3× the hyperscaler median; this is structurally divergent from Amazon (0% renewable in last 5 deals) and Microsoft (55%)." He clicks the chart, scrolls citations, sees one Reuters piece tagged "agree", one SemiAnalysis blog tagged "disagree". He opens the thread: "Is the renewable concentration a financing constraint or a strategy?" The agent answers using `query_database` over `curated_deals` + `edgar_extractions`, producing a follow-up table.*

**Journey:** lands → scans 5–10 cards → clicks 1–2 → opens chat → walks away with 1 talking point for the next exec sync.

### 4.2 Strategy analyst

> *Composing a competitive briefing on Q2 hyperscaler buildout. Opens AI Insights, filters insight cards by tag (`#power`, `#permits`). Copies a chart + provenance footer into Confluence. Clicks the SEC URL in the citations to verify the underlying 8-K.*

**Journey:** filter → harvest 2–3 insights → cite into deck.

### 4.3 Capacity planner

> *Looking for under-permitted regions. Opens AI Insights, asks the agent in chat: "Which states have the highest contracted-GW per active building permit?" Agent runs a multi-step query (sites + permits + curated_deals), returns a state-ranked table with a stacked bar chart, citations to the relevant Loudoun/Mesa Socrata datasets.*

**Journey:** open chat directly → ask a structured question → get a chart + sources back.

---

## 5. Functional Requirements

### 5.1 Insight Discovery

**Definition (insight):** a single declarative claim about the platform's data that satisfies all four:

1. **Specific** — names entities (companies, states, sites, vendors) and a quantity.
2. **Supported** — at least one row of evidence retrievable via `query_database` or `call_api`.
3. **Non-trivial** — not directly visible as a tile on any of the 9 existing tabs. Examples of *trivial* (rejected): "Amazon has the most contracted GW" (visible on Power tab as the largest bar). Examples of *non-trivial* (accepted): "Amazon is the only hyperscaler whose top 5 deals are all nuclear, while Google's are all renewable."
4. **Material** — the claim, if true, would change a strategy decision. Subjective; the agent self-rates and surfaces a `materiality_score ∈ {low, medium, high}`. Reviewer (Karan) ratings calibrate the prompt over time.

**Generation loop (per session):**

1. Agent calls `call_api` against a fixed set of "survey" endpoints to bootstrap context (gw-summary, triangulation/l1, triangulation/l2, anomalies/recent, companies top-50). Cap: 8 bootstrap calls.
2. Agent runs **EDA skills** (`programmatic-eda`, `data-quality-audit`) to identify structure + gaps.
3. Agent generates **5–15 candidate hypotheses**.
4. For each hypothesis: agent runs **2–4 verification calls** (`query_database` or `call_api`) and either confirms, rejects, or adjusts the claim.
5. Agent **ranks** confirmed hypotheses by materiality + novelty + data support, picks top 5–10.
6. For each kept insight: agent runs **narrative skills** (`insight-synthesis`, `data-narrative-builder`, `impact-quantification`) to produce the headline + one-paragraph body + chart spec.
7. Agent emits results via `emit_chart` and (V2) `emit_citation`.

**Cap (safety):**
- **48 tool calls** per session in V1 (12-turn loop × 4-wide parallel; raise to 80 in V2 to accommodate web search).
- **8-minute wall-clock** per session.
- **No recursive agent calls** — flat tool-use only.
- **No `query_database` execution unless** the SQL passes a parser whitelist (SELECT only, single statement, no `pg_*` schema, max 10 K rows). See [`./ARCHITECTURE.md`](./ARCHITECTURE.md) for enforcement.

**Dedup:** before emitting, normalize each insight headline (lowercase, strip stop-words, sort tokens) and reject if Jaccard similarity ≥0.7 to any prior insight in the same session.

### 5.2 Charts (Recharts spec contract)

**Hard rule:** the frontend already depends on **Recharts** (per `frontend/package.json`). **No new charting library may be introduced.** The agent emits a JSON spec; the frontend renders it via a single `<InsightChart spec={...} />` component.

**Supported chart types (V1):** `bar`, `stackedBar`, `groupedBar`, `line`, `area`, `scatter`, `pie`, `heatmap` (composed from Recharts primitives). Out: `radar`, `treemap`, `sankey`, `radialBar` (V2 candidates).

**Spec schema (planning-level; finalize in [`./ARCHITECTURE.md`](./ARCHITECTURE.md)):**

```
ChartSpec {
  chart_id: string                 // stable per-session ID
  type: "bar"|"stackedBar"|"groupedBar"|"line"|"area"|"scatter"|"pie"|"heatmap"
  title: string                    // short, declarative
  subtitle?: string                // 1-line context
  data_source: {
    kind: "query"|"api"|"chart_data"
    spec: {                        // one of:
      sql?: string                 // the literal SQL run, for provenance
      endpoint?: string            // e.g., "/api/triangulation/l2"
      params?: Record<string,any>
      tab_chart?: {tab: string, chart_id: string}
    }
    rows: number                   // count of rows that fed the chart
    fetched_at: ISO8601
  }
  data: Array<Record<string, string|number>>   // already shaped for Recharts
  encoding: {
    x: {field: string, type: "category"|"time"|"quantitative", label?: string}
    y: {field: string, type: "quantitative", label?: string}
    series?: {field: string}       // for stacked / grouped / multi-line
    color?: {field?: string, scheme?: "categorical"|"sequential"}
  }
  annotations?: Array<{
    type: "line"|"band"|"point",
    value: number|string,
    label: string
  }>
  formatting?: {y_unit?: "GW"|"MW"|"USD"|"count"|"%", y_precision?: number}
}
```

**Data-source rules:**
- **Every chart MUST cite its data source** (one of `query`, `api`, or `chart_data`). Charts emitted without a `data_source` are rejected at validation.
- **Inline `data` is mandatory** — the frontend renders from the spec, does not re-fetch. (Reproducibility.)
- **Max 500 rows** per chart spec. Beyond 500 the agent must aggregate before emitting (e.g., top-N + "other").
- **No fabricated data points.** Every row in `data` must have come from a `data_source` call captured in the session log. Enforced server-side via row-hash check.

### 5.3 Web Search & Citations (V2)

**Mandatory:** every insight in V2 ships with **2–5 web-search citations**.

**Per citation:**

```
Citation {
  url: string
  title: string
  snippet: string           // ≤280 chars, lifted from search result
  agree_or_disagree: "agree" | "disagree" | "context"
  rationale: string         // 1 sentence why agent tagged it this way
  retrieved_at: ISO8601
  search_query: string      // exact query used to find it
}
```

**Tagging logic:**
- `agree`: source corroborates the insight's quantitative claim (within 20%) or qualitative direction.
- `disagree`: source contradicts the insight's claim or direction.
- `context`: source is relevant background but neither agrees nor disagrees (e.g., regulatory context, vendor PR).

**Required cite count:**
- V2 rule: **≥2 citations** per insight, **≥1 of which must be `agree` or `disagree`** (pure `context`-only is insufficient). Up to 5 max to keep cards readable.
- If the agent cannot find ≥2 citations after **3 web-search calls** for an insight, the insight is **emitted with a `low_external_support` flag** and Karan can choose to filter these out.

**Search provider:** TBD — defer to [`./RESEARCH.md`](./RESEARCH.md). Candidates: Brave Search API, Bing Web Search API, Tavily, SerpAPI. Selection criteria documented there.

**Rate / cost guardrail:** ≤8 web-search calls per session in V2. Enforced via the tool wrapper.

### 5.4 Chat Follow-up (V2)

**Per-insight thread.** Every insight card has a "Discuss" button. Clicking opens a chat panel scoped to that insight.

**Context window scope:**
- **Always in context:** the insight's headline + body, the chart spec (compact form), the citations (URLs + snippets), and the data-source call(s) that produced the chart.
- **Conditionally in context (on demand):** prior turns of *this* thread.
- **Never in context:** other insights' threads. Cross-insight chat happens in a separate "general" chat (deferred to V3).

**Tool surface in chat:** same 7 tools (`query_database`, `call_api`, `get_chart_data`, `web_search`, `run_skill`, `emit_chart`, `emit_citation`). Yes — the chat agent can emit **additional charts and citations** that get appended below the original insight in the same card. This is the "drill-down" pattern.

**Persistence:** threads stored in a new `insight_threads` table (schema in [`./ARCHITECTURE.md`](./ARCHITECTURE.md)). Insights themselves persisted in `ai_insights`. No per-user scoping (no auth in v1).

**Latency budget per turn:** ≤20 seconds p50, ≤45 seconds p95.

### 5.5 Skill-driven analysis

**Mechanism:** the agent calls `run_skill(skill_name, inputs)`, which loads the skill's prompt + (optionally) deterministic preprocessing (e.g., for `programmatic-eda`, a Python preprocessor that runs `df.describe()` on a queried frame and returns it to the agent). Skill outputs are returned to the agent as structured JSON.

**Visibility:** by default, skills run **hidden** — the user sees the resulting insight, not the intermediate skill outputs. **Provenance footer**, however, lists which skills were run for each insight (e.g., "skills: programmatic-eda, segmentation-analysis, insight-synthesis"). This is a deliberate trade-off: full transparency would overwhelm the card; full opacity would defeat trust.

**Power-user mode (V3):** clicking "show reasoning" on an insight expands the full skill-call trace (prompts redacted, outputs visible).

**Skills are not Claude Code skills as-shipped.** Each chosen skill must be **converted** to a Llama-Stack-compatible prompt with a deterministic shim (typed inputs/outputs, no filesystem access, no tool-call recursion). See [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) for the conversion playbook.

### 5.6 Trust & Provenance

Every insight card MUST surface a **provenance footer** with:

| Field | Source |
|---|---|
| `data_sources_used` | List of every `data_source.spec` from every chart in the card, plus any `call_api` endpoint called, plus row counts. |
| `skills_run` | Ordered list of skills invoked (`programmatic-eda`, `insight-synthesis`, etc.). |
| `confidence` | `low` / `medium` / `high` — agent self-rates based on (a) row count behind the chart, (b) cite count + agree-vs-disagree balance, (c) staleness of the underlying ingestion run. Heuristic in [`./ARCHITECTURE.md`](./ARCHITECTURE.md). |
| `materiality` | `low` / `medium` / `high` — see §5.1. |
| `generated_at` | ISO8601, server time. |
| `model` | Model ID used (e.g., `oci/openai.gpt-5.4`). |
| `session_id` | Stable handle to the originating session. |

**No insight may render without all 7 fields populated.** The renderer enforces this.

---

## 6. Skill Relevance Cut

The brief lists 33 skills under `~/.claude/skills/`. The brief explicitly highlights 17 candidates. PM cut below: **15 keeps**, **18 drops**. Rationale and phase per row.

### 6.1 Capability buckets

| Bucket | Purpose in AI Insights |
|---|---|
| **EDA** | Structure-find: shape data, detect distributions, gaps, outliers — the bootstrap step. |
| **Hypothesis-testing / analysis** | Convert hunches into evidenced claims (segmentation, time-series, root-cause). |
| **Narrative & framing** | Turn an evidenced claim into an insight card (headline, body, exec gloss). |
| **QA / trust** | Defensive — stop the agent from emitting weak or hallucinated insights. |

### 6.2 The cut

| # | Skill | Decision | Bucket | V-phase | Rationale |
|---|---|---|---|---|---|
| 1 | `programmatic-eda` | **KEEP** | EDA | V1 | First step every session. Agent points it at a queried frame to get descriptive stats + skew flags. |
| 2 | `data-quality-audit` | **KEEP** | QA | V1 | Surfaces null density, type drift, freshness. Drives the "low confidence" flag if the underlying ingestion is stale. |
| 3 | `root-cause-investigation` | **KEEP** | Hypothesis | V1 | Drives the "why" follow-up that turns an anomaly into an insight (e.g., "why did Amazon's 8-K cadence drop in March?"). |
| 4 | `time-series-analysis` | **KEEP** | Hypothesis | V1 | Native to the platform — `power/timeseries`, `permits/building?days=180`, anomaly detector outputs are all time-indexed. |
| 5 | `segmentation-analysis` | **KEEP** | Hypothesis | V1 | The bread-and-butter cut: by hyperscaler, by state, by deal-type (nuclear vs renewable), by lifecycle stage. |
| 6 | `cohort-analysis` | **KEEP** | Hypothesis | V2 | Useful for sites by year-of-announcement vs commissioning lag. Lower priority than segmentation in V1. |
| 7 | `ab-test-analysis` | **DROP** | Hypothesis | — | No A/B context in this product. We're not running experiments; we're reading public data. |
| 8 | `funnel-analysis` | **DROP** | Hypothesis | — | No conversion funnel in competitive intel. The closest analog (announce → permit → site → commission) is better served by `time-series-analysis` + `cohort-analysis`. |
| 9 | `business-metrics-calculator` | **KEEP** | Hypothesis | V1 | We have GW, MW, $-revenue, gap. Standardizes per-metric computation (e.g., contracted-GW-per-state-per-quarter). |
| 10 | `insight-synthesis` | **KEEP** | Narrative | V1 | The skill that turns a verified hypothesis into a one-sentence headline. Core. |
| 11 | `executive-summary-generator` | **KEEP** | Narrative | V1 | Karan-facing card-body generator. Tone calibration matters here. |
| 12 | `visualization-builder` | **KEEP** | Narrative | V1 | Chooses chart type + encoding given the data shape. Outputs the `ChartSpec` JSON. |
| 13 | `data-narrative-builder` | **KEEP** | Narrative | V1 | Stitches headline + chart + caption into a coherent card body. Distinct from `executive-summary-generator` in that it operates *per insight*, not over a corpus. |
| 14 | `impact-quantification` | **KEEP** | Narrative | V1 | "What's the GW gap in dollars?" — converts technical numbers into stakes. Important for materiality scoring. |
| 15 | `methodology-explainer` | **KEEP** | QA | V2 | Produces the "how was this computed?" pop-out. Essential when Karan pushes back. V1 ships a static methodology footer; V2 swaps in the skill-driven version. |
| 16 | `technical-to-business-translator` | **KEEP** | Narrative | V1 | Converts "L2 implied GW = 4.4" into "FY26 NVIDIA revenue implies datacenter compute demand of 4.4 GW worldwide" — exec-readable. |
| 17 | `peer-review-template` | **KEEP** | QA | V2 | Pre-emit defensive check: agent self-reviews each insight against a checklist (specificity, support, non-triviality, materiality). Costs an extra LLM call per insight; deferred to V2 to keep V1 latency low. |
| 18 | `statistical-test-selection` | **DROP** | Hypothesis | — | We're rarely doing inferential stats on this dataset. Most claims are descriptive (counts, sums, ratios). Reconsider in V3 if a use case appears. |
| 19 | `correlation-vs-causation` | **DROP** | QA | — | Useful in principle, but our claims lean descriptive ("X happened") not causal ("X caused Y"). Risk of overhead without payoff. |
| 20 | `sql-query-builder` | **DROP** | EDA | — | Redundant — the agent already constructs SQL inline through `query_database`. A skill wrapper adds a layer without information. |
| 21 | `dashboard-design` | **DROP** | Narrative | — | Out of scope: we're emitting individual cards, not dashboards. The 9 existing tabs are the dashboards. |
| 22 | `kpi-tree` | **DROP** | Narrative | — | Useful for org-internal metrics; we don't have an internal-tree concept here. |
| 23 | `data-cleaning` | **DROP** | EDA | — | Cleaning happens in the ingestion pipeline. Agent operates on cleaned data. |
| 24 | `missing-data-imputation` | **DROP** | EDA | — | Per [parent PRD §S5](../../../PRD.md), the rule is honest coverage badges, not imputation. Imputing missing GW would silently fabricate signal. |
| 25 | `outlier-detection` | **DROP** | EDA | — | Already covered by `anomaly_detector` agent (live in production). Agent reads anomaly outputs via `call_api`. |
| 26 | `geospatial-analysis` | **DROP (V1) → reconsider V3** | Hypothesis | V3-maybe | Compelling for state/county clustering, but Recharts can't render maps; the existing Power Map tab uses Leaflet. V3 may add a map-emit path; not in V1/V2 scope. |
| 27 | `forecasting` | **DROP** | Hypothesis | — | Per [parent PRD §2](../../../PRD.md), predictive forecasting is an explicit non-goal. |
| 28 | `churn-analysis` | **DROP** | Hypothesis | — | No churn concept in competitive intel. |
| 29 | `pricing-analysis` | **DROP** | Hypothesis | — | We have ASP assumptions in L2 model, but no pricing-curve data to analyze. |
| 30 | `survey-analysis` | **DROP** | Hypothesis | — | No surveys in this product. |
| 31 | `nps-analysis` | **DROP** | Hypothesis | — | No NPS data. |
| 32 | `marketing-attribution` | **DROP** | Hypothesis | — | No marketing data. |
| 33 | `customer-lifetime-value` | **DROP** | Hypothesis | — | No customer data; OCI is upstream of customer signals here. |

**Note on assumed skill list:** The 33-skill catalog is referenced by the brief but not directly enumerable from this thread. PM proceeded by treating the 17 brief-named skills as the keep-candidates and inferring 16 plausible drop-candidates (rows 18–33) from a standard data-analytics skill catalog. Exact skill names and the final list of 33 to be reconciled in [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) by the agent doing the actual conversion. **Assumption flagged.**

### 6.3 Keep summary by phase

| Phase | Skills active | Total |
|---|---|---|
| **V1** | programmatic-eda, data-quality-audit, root-cause-investigation, time-series-analysis, segmentation-analysis, business-metrics-calculator, insight-synthesis, executive-summary-generator, visualization-builder, data-narrative-builder, impact-quantification, technical-to-business-translator | **12** |
| **V2** (adds) | cohort-analysis, methodology-explainer, peer-review-template | **15** |
| **V3** (reconsider) | geospatial-analysis (if map-emit lands) | **15–16** |

Brief target: 14–17 keeps. **Final cut: 15 keeps**, lands in the middle of the band.

---

## 7. Success Metrics

### 7.1 Quantitative

| # | Metric | V1 target | V2 target | V3 target |
|---|---|---|---|---|
| Q1 | Insights per session | 5–10 | 5–10 | 5–10 |
| Q2 | % insights with non-trivial chart | ≥80% | ≥85% | ≥90% |
| Q3 | % insights with ≥2 citations | n/a (V2+) | ≥75% | ≥85% |
| Q4 | % insights w/ ≥1 agree-or-disagree (not just context) | n/a | ≥70% | ≥80% |
| Q5 | p50 / p95 generation latency | ≤3 / ≤8 min | ≤4 / ≤10 min | ≤4 / ≤10 min |
| Q6 | Tool-call cap breaches per 100 sessions | ≤5 | ≤5 | ≤5 |
| Q7 | Hallucinated table/column references per 100 sessions | 0 | 0 | 0 |
| Q8 | Dedup rejects per session | ≤2 | ≤2 | ≤2 |
| Q9 | % chat threads ≥3 turns deep (engagement signal) | n/a | ≥30% | ≥40% |

### 7.2 Qualitative

- Karan rates **≥40%** of insights "useful" (4 or 5 on 5-point scale) in V1 dogfood; **≥55%** by V2; **≥65%** by V3.
- Strategy analyst can copy ≥1 insight per session into a working briefing without rewording the headline.
- Capacity planner reports the chat answers structured questions correctly **≥70%** of the time (V2 metric, capture by spot-audit).

### 7.3 Negative metrics (catastrophic failure flags)

- Any insight whose claim is **factually wrong** about the underlying data → P0 incident.
- Any chart whose `data` does not match the `data_source` row hash → P0 incident.
- Any web citation that 404s within 7 days of emit → log + warn; if rate >5%, P1.

---

## 8. Phased Rollout

### V1 (4–6 weeks) — "Static cards, no chat, no web"

**Scope:**
- New tab `AI Insights` registered in the frontend nav.
- "Generate insights" button → backend kicks a session → poll for completion → render cards.
- 5–10 cards per session. Each card: headline + body + chart + provenance footer. No chat, no citations.
- 12 skills active (V1 column above).
- Tools live: `query_database`, `call_api`, `get_chart_data`, `run_skill`, `emit_chart`. **NOT live:** `web_search`, `emit_citation`.
- Persistence: `ai_insights` + `ai_sessions` tables (schemas in [`./ARCHITECTURE.md`](./ARCHITECTURE.md)).

**Exit criteria:**
- Karan completes 5 dogfood sessions with no P0 incidents.
- Q1, Q2, Q5, Q6, Q7, Q8 metrics meet target on a sample of 20 sessions.
- Q4 (Karan rating) ≥30% useful (relaxed V1 bar; raises in V2).

### V2 (+3–4 weeks) — "Chat + web search"

**Scope:**
- Web-search tool live; citation emit + tagging.
- Chat panel per insight; `insight_threads` table.
- Skills expanded to 15 (add cohort, methodology-explainer, peer-review-template).
- Tool-call cap raised to 80; web-search cap 8 / session.
- "Subscribe to this insight" button (UI scaffold only — no actual notifications until V3).

**Exit criteria:**
- Q3, Q4 (≥55%), Q9 metrics meet target on 20 dogfood sessions.
- Cite-validation: spot-check 30 random citations, ≥27 reach 2xx and the snippet is in the page.

### V3 (+2–3 weeks) — "Cron + diff + notify"

**Scope:**
- Weekly cron (Sun 23:30 UTC, 30 min after `weekly_brief`) generates a fresh AI Insights run.
- Insight-diff renderer: when the same canonical insight (matched by entity + claim-type) re-appears with new numbers, render "Δ vs last week" badge.
- Subscribe/notify: email or in-product banner when a saved insight's underlying number moves >user-threshold.
- (Stretch) `geospatial-analysis` skill if map-emit path lands.

**Exit criteria:**
- Diff renders correctly on 3 consecutive weekly runs.
- ≥1 subscribe-trigger fires correctly in dogfood.

---

## 9. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **Hallucination** — agent invents a number, table, or company. | Medium | High | (a) Strict tool-call whitelist; SQL validated against live `information_schema` before exec. (b) Row-hash check between chart `data` and `data_source` results. (c) `peer-review-template` skill in V2 as a self-check pass. (d) Provenance footer surfaces the actual SQL/endpoint, so a reviewer can verify. |
| R2 | **Runaway agent loops** — agent calls itself or hits rate-limit storms. | Medium | High | Hard tool-call cap (48 V1 / 80 V2 — 12 turns × 4 parallel); wall-clock timeout (8 min); no recursive `run_skill`; rate limit on `query_database` (max 20 / session). |
| R3 | **Web search cost / quality** | Medium | Medium | Defer to V2; cap 8 calls / session. Provider selection in [`./RESEARCH.md`](./RESEARCH.md) prioritizes ≤$0.01/query and a free tier for dev. |
| R4 | **Skill conversion fidelity** — Claude Code skills behave differently on Llama Stack models. | High | Medium | Per-skill golden-output regression suite ([`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md)). Convert skills one at a time; ship V1 with the 6–8 highest-confidence ones first. |
| R5 | **Latency** — 8-min budget breached on complex sessions. | Medium | Medium | (a) Parallelize independent tool calls. (b) Pre-warm bootstrap data via cache. (c) Stream insights as they finish (agent emits one card → frontend renders it → agent continues). Streaming protocol in [`./ARCHITECTURE.md`](./ARCHITECTURE.md). |
| R6 | **DB query safety** — agent submits expensive or write-shaped SQL. | Low | Critical | (a) Read-only DB role. (b) SQL parser whitelist (SELECT only, no CTEs that touch `pg_*`, no `pg_sleep`). (c) Statement timeout 5 s. (d) Row cap 10 K. |
| R7 | **Stale ingestion produces stale insights** — agent reports on data ingested 30 days ago. | Medium | Medium | `data-quality-audit` skill surfaces last-run-age per source; insights flagged `low_confidence` if any underlying source is older than its expected freshness band ([parent PRD §7](../../../PRD.md)). |
| R8 | **User over-trusts the agent** — treats output as ground truth. | Medium | High | Card-level "AI-generated" badge, prominent provenance footer, every chart click-throughs to source. Karan pre-briefed at V1 demo. |
| R9 | **Llama Stack outage** | Low | High | Graceful failure: insight tab shows last successful session with its `generated_at` timestamp. No silent fallbacks to mock data — banner shows "AI service unavailable." |
| R10 | **Prompt injection via ingested data** (an EDGAR filing contains "ignore previous instructions"). | Low | Medium | Tool outputs are always serialized as JSON, not concatenated into the prompt as raw text. Skill prompts treat data fields as values, not instructions. Spot-audit V1. |

---

## 10. Open Questions

| # | Question | Owner | Decision deadline |
|---|---|---|---|
| OQ1 | **Web-search provider** — Brave / Bing / Tavily / SerpAPI? Cost, recall, snippet quality, ToS. | Researcher → [`./RESEARCH.md`](./RESEARCH.md) | Before V2 kickoff |
| OQ2 | **Chart-spec format** — adopt the §5.2 schema as-is, or align with an existing internal schema (e.g., the `chart_spec` already returned by `datacenter_qa` and `triangulation_qa`)? | Architect → [`./ARCHITECTURE.md`](./ARCHITECTURE.md) | Before V1 implementation start |
| OQ3 | **Streaming protocol** — SSE vs WebSocket vs long-poll? Latency vs proxy compatibility. | Architect → [`./ARCHITECTURE.md`](./ARCHITECTURE.md) | Before V1 implementation start |
| OQ4 | **Skill conversion path** — direct prompt port, or Llama-Stack-native rewrite? | Skill engineer → [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) | Sprint 1 of V1 |
| OQ5 | **Materiality scoring rubric** — agent self-rate via prompt only, or seed with reviewer-labeled training examples? | PM + Karan | Sprint 2 of V1 |
| OQ6 | **Insight uniqueness across sessions** — should the agent see prior sessions' insights to avoid repetition, or run cold each time? Trade-off: novelty vs continuity. | PM | Before V3 (cron rollout) |
| OQ7 | **Citation freshness** — is a citation acceptable if its source is >12 months old? | PM + Karan | Before V2 |
| OQ8 | **Confidence rubric** — what numeric thresholds map to low/medium/high? (e.g., row count, citation count, source age) | Architect + PM | Before V1 demo |
| OQ9 | **Cron timing in V3** — Sunday 23:30 UTC clashes with `weekly_brief` log volume; choose a non-overlapping window. | Ops | Before V3 |
| OQ10 | **Chat persistence retention** — do threads live forever, or rotate after N days? | PM | Before V2 |
| OQ11 | **Are the 33 skills the exact set?** — confirm catalog at `~/.claude/skills/`. The cut in §6 assumed the standard data-analytics skill set; deltas will require re-rationalization. | Skill engineer | Sprint 1 of V1 |

---

## 11. Cross-references

- [`./RESEARCH.md`](./RESEARCH.md) — Web-search provider eval; competitive landscape of insight-generation agents; prompt-injection threat model.
- [`./ARCHITECTURE.md`](./ARCHITECTURE.md) — `ChartSpec` schema finalization; streaming protocol; DB safety enforcement; tool-call wrappers; tables (`ai_sessions`, `ai_insights`, `insight_threads`); confidence rubric.
- [`./UX.md`](./UX.md) — Card layout, provenance footer placement, chat panel docking, "subscribe" affordance, AI-generated badge.
- [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) — Per-skill conversion plan from Claude Code skill format → Llama-Stack-native skill module; golden-output regression harness; reconciliation against actual `~/.claude/skills/` catalog.
- [`./TASKS.md`](./TASKS.md) — V1 / V2 / V3 task breakdown; estimates; owner assignments.
- [`/strategic-insights-tool/PRD.md`](../../../PRD.md) — Parent product PRD (existing 9 tabs, parent goals).
- [`/strategic-insights-tool/docs/planning/DEMO_BRIEF_2026-05-01.md`](../DEMO_BRIEF_2026-05-01.md) — Live system inventory used to size data scope.
