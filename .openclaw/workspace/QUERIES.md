# Strategic Insights — Canonical Query Patterns

These are the high-value query patterns the OpenClaw insights agent should reach for first when synthesizing or answering. Each pattern is grounded in either `backend/agents/insights/hypothesizer.py::build_factpack` (the canonical "what does the agent care about" bundle) or in the QA system prompt at `backend/agents/insights/prompts/qa_global_rules.md`.

**Hard constraints from `query_database` (sql_gate AST validator):**
- Single-statement `SELECT` only (CTEs and `UNION` allowed). DDL/DML rejected.
- LIMIT auto-attached at 10,000 rows if missing; clamped if higher requested.
- Per-statement timeout: 5,000 ms.
- No `pg_*` schema or table references.
- Read-only role (`ai_agent`).

**Always:** quote literals, use parameterized values where the agent has them, prefer `ILIKE` for company/state name matching, and **deduplicate canonical_name in `companies`** — the table has duplicate rows per ticker/CIK (e.g. "Microsoft" + "Microsoft Corporation" both with cik=`0000789019`). Use `c.ticker = 'MSFT'` or `DISTINCT ON (c.cik)` to avoid join multiplication.

**Smoke-test status (2026-05-07):** Patterns 1, 3, 4, 5 (8-K + activations), 7, 8, 9, 11, 12 verified to execute and return data. Pattern 6 (anomalies) is correct SQL but the table is empty — every call will return 0 rows until `_anomaly_detection` produces signals. Pattern 2 (vendor-supply quarterly) executes and returns data, but `total_mw_disclosed` is mostly NULL on vendor_supply rows. Pattern 10 examples were not run end-to-end (require concrete UUIDs at call time) but are direct restatements of the reads inside `agentic_synthesis.py` and `routers/agent.py`.

---

## Pattern 1: Power capacity by hyperscaler

**Business question it answers:** which operators control the most disclosed datacenter MW, and how concentrated is the market?
**When to use:** any "top hyperscalers" / "buildout pace" / "market share" prompt; opening move for competitive-positioning insights.
**Tables touched:** `sites`.
**SQL:**
```sql
SELECT provider_name,
       COUNT(*)                                   AS site_count,
       ROUND(SUM(power_capacity_mw)::numeric, 0)  AS total_mw,
       ROUND(AVG(power_capacity_mw)::numeric, 0)  AS avg_mw_per_site,
       SUM(CASE WHEN stage ILIKE '%active%' THEN 1 ELSE 0 END) AS active_sites
FROM sites
WHERE provider_name IS NOT NULL
  AND provider_name <> 'Company Not Disclosed'
  AND power_capacity_mw IS NOT NULL
GROUP BY provider_name
ORDER BY total_mw DESC NULLS LAST
LIMIT 10;
```
**Tunable bits:** `LIMIT` (top-N), filter by `state_code` for "top operators in TX", filter by `stage ILIKE '%active%'` for operational-only.
**Returns:** one row per operator with site count, total MW, average MW, active count. Top of the list as of 2026-05: AWS (40 GW), Tract (20 GW), Facebook/Meta (17 GW), Google (16 GW), Microsoft (15 GW).
**Variants:**
- By state: add `WHERE state_code = 'VA'`.
- By stage breakdown: `GROUP BY provider_name, stage`.
- AI-only: add `WHERE is_ai_facility = true`.
**Common pitfalls:**
- ALWAYS exclude `'Company Not Disclosed'` — it's the largest "operator" by row count (1,355).
- `power_capacity_mw` is in MW, not GW — divide by 1000 in the prose layer if you want GW.
- `provider_name` is free-text — `'Amazon'` and `'Amazon AWS'` are distinct. The canonical Aterio spelling is `'Amazon AWS'`.

---

## Pattern 2: GPU / vendor-supply filings by quarter

**Business question it answers:** how is the chip-supply ecosystem (NVIDIA-customer disclosures, foundry orders, …) trending quarterly?
**When to use:** when the user asks about NVIDIA exposure, AI-chip orders, or supplier momentum; mirrors hypothesizer's `edgar_capacity_mentions_7d` extended to vendor-supply pillar.
**Tables touched:** `edgar_extractions`.
**SQL:**
```sql
SELECT DATE_TRUNC('quarter', filing_date)::date AS quarter,
       COUNT(*) AS filings,
       COUNT(DISTINCT cik) AS distinct_filers,
       COUNT(*) FILTER (WHERE capacity_mw IS NOT NULL) AS filings_with_mw,
       ROUND(SUM(capacity_mw)::numeric, 0)             AS total_mw_disclosed
FROM edgar_extractions
WHERE pillar = 'vendor_supply'
  AND filing_date >= CURRENT_DATE - INTERVAL '24 months'
GROUP BY 1
ORDER BY quarter DESC;
```
**Tunable bits:** swap `pillar = 'power_contract'` for PPA filings. Adjust window (12/24/36 months). Add `cik IN (...)` to scope to a vendor cohort.
**Returns:** quarterly bucket with filings count, distinct filers, MW (often NULL for vendor_supply). Currently 6–15 filings per quarter.
**Variants:**
- Per-filer: `GROUP BY DATE_TRUNC('quarter', filing_date), cik` then `JOIN companies` to label.
- Power-related only (broader than vendor_supply): `WHERE is_power_related = true`.
**Common pitfalls:**
- `capacity_mw` is **frequently NULL on vendor_supply rows** — the LLM extractor flags is_power_related but doesn't always pull a number. The total_mw column is mostly null.
- Use `is_power_related` (boolean, indexed) when you want all power/datacenter-flagged filings regardless of pillar.

---

## Pattern 3: Permit filings by hyperscaler (parent rollup)

**Business question it answers:** how many generator permits has each hyperscaler filed, what shell LLC names did they use?
**When to use:** "which big-tech companies have generator permits", "where is Microsoft permitting backup power", competitive-permitting insights.
**Tables touched:** `generator_permits`, `companies`.
**SQL:**
```sql
SELECT c.canonical_name AS parent,
       COUNT(*)                                     AS permits,
       STRING_AGG(DISTINCT g.permittee_raw_name, ', ' ORDER BY g.permittee_raw_name) AS filed_as,
       STRING_AGG(DISTINCT g.state_code, ',' ORDER BY g.state_code)                  AS states,
       ROUND(SUM(g.rated_mw_total)::numeric, 0)     AS total_rated_mw
FROM generator_permits g
JOIN companies c ON c.id = g.resolved_company_id
WHERE c.ticker IN ('AMZN','MSFT','GOOGL','META','ORCL','AAPL','NVDA')
GROUP BY c.canonical_name
ORDER BY permits DESC;
```
**Tunable bits:** swap `ticker` filter for `c.canonical_name IN (...)` if user names a non-public company. Filter by `g.source = 'epa_echo'` for federal-only, `g.source = 'pjm'` for ISO-queue interconnection requests.
**Returns:** parent-level count + the shell LLC names actually used + states + total MW. As of 2026-05: Meta 4 permits (incl. via Meta Platforms Inc. resolution), Amazon 1 (Vadata Inc.), Google 1 (Raiden LLC), Microsoft 1 (Microsoft Azure FXS LLC), Oracle 1 (Oracle America Inc.). **Most permits in the warehouse are NOT filed by hyperscalers** — they're filed by utilities (AEP, Dominion, FirstEnergy, …).
**Variants:**
- All resolved companies (not just hyperscalers): drop the `WHERE c.ticker IN (...)` filter, add `LIMIT 20`.
- Source breakdown: `GROUP BY c.canonical_name, g.source`.
- Time-series: `WHERE g.issued_date >= '2024-01-01' GROUP BY DATE_TRUNC('month', g.issued_date), c.canonical_name`.
**Common pitfalls:**
- **There is NO `generator_permits.parent_company` column** — the QA prompt mistakenly claims one. Always join via `resolved_company_id → companies.canonical_name`.
- `rated_mw_total` is frequently NULL on PJM ISO-queue rows (capacity sits in `raw_payload->>'capacity_mw'` instead). For ISO-queue MW you need JSONB extraction.
- The `companies` table has **duplicate rows per CIK** ("Microsoft" + "Microsoft Corporation"). The `JOIN` will multiply rows. Use `WHERE c.ticker = 'MSFT'` if you want a single hyperscaler — picking the canonical row by ticker dedupes implicitly.

---

## Pattern 4: Site-level capacity and operator (state focus)

**Business question it answers:** what are the largest sites in a given state, who runs them, what stage are they in?
**When to use:** "biggest datacenters in Texas", "AWS's Virginia footprint", site-by-site rankings.
**Tables touched:** `sites`.
**SQL:**
```sql
SELECT building_name,
       campus_name,
       provider_name,
       city_name,
       power_capacity_mw,
       stage,
       pct_construction,
       end_user_companies,
       utility_name,
       bal_auth_abbr,
       datasheet_url
FROM sites
WHERE state_code = 'TX'
  AND power_capacity_mw IS NOT NULL
  AND provider_name <> 'Company Not Disclosed'
ORDER BY power_capacity_mw DESC
LIMIT 20;
```
**Tunable bits:** `state_code` (any 2-letter), `provider_name = 'Microsoft'`, `stage ILIKE '%active%'` for built-only, `is_ai_facility = true` for AI-purpose only.
**Returns:** site-by-site detail with operator, location, MW, stage, customer, utility, balancing authority, citation URL.
**Variants:**
- Specific operator + state: `WHERE provider_name = 'Microsoft' AND state_code = 'VA'`.
- City-level rollup (mirrors QA-prompt example): `GROUP BY city_name`, `SUM(power_capacity_mw)`.
- With end-user count: add `array_length(string_to_array(end_user_companies, ','), 1) AS n_tenants`.
**Common pitfalls:**
- `stage` is free-text — values include "Active under construction", "Operational", etc. Use `ILIKE '%active%'`, not `=`.
- `pct_construction` is a **0–1.0 fraction**, not 0–100. DB max across all rows is 1.0. For display multiply by 100; for filters use `>= 0.70` not `>= 70`. It's derived from Aterio satellite imagery, not operator-declared.
- `building_name` is sometimes NULL — fall back to `campus_name` then `aterio_dc_uid` for display.

---

## Pattern 5: Recent material events (8-K, activations, expansions)

**Business question it answers:** what happened this week / month at a given operator's sites? What 8-Ks were filed?
**When to use:** "recent activity at X", weekly briefing input, Phase-2 anomaly context.
**Tables touched:** `events`, `sites`, `edgar_extractions`, `companies`.
**SQL (Aterio events at a hyperscaler's sites):**
```sql
SELECT e.event_date,
       e.event_type,
       s.building_name,
       s.state_code,
       s.power_capacity_mw,
       LEFT(e.event_description, 200) AS description,
       e.source_url
FROM events e
JOIN sites s ON s.aterio_dc_uid = e.aterio_dc_uid
WHERE s.provider_name = 'Amazon AWS'
  AND e.event_date >= CURRENT_DATE - INTERVAL '90 days'
  AND e.event_date <= CURRENT_DATE
ORDER BY e.event_date DESC
LIMIT 25;
```
**SQL (recent 8-Ks for a public hyperscaler):**
```sql
SELECT e.filing_date,
       e.signing_date,
       e.item_codes,
       e.capacity_mw,
       e.energy_source,
       e.buyer_canonical,
       e.seller_canonical,
       LEFT(e.excerpt, 250) AS excerpt,
       e.edgar_url
FROM edgar_extractions e
JOIN companies c ON c.cik = e.cik
WHERE c.ticker = 'AMZN'
  AND e.form_type = '8-K'
ORDER BY e.filing_date DESC
LIMIT 20;
```
**Tunable bits:** swap `provider_name`, swap `ticker`, change form_type to `'10-K'` / `'10-Q'`, change window.
**Returns:** date-ordered event/filing rows with citation URL.
**Variants:**
- Activations only: `WHERE e.event_type = 'activation' AND e.event_date <= CURRENT_DATE` (the clamp matters — projected/planned activations have future dates and pollute "recent activation" cuts).
- Construction-progress milestones with %: `WHERE e.event_type = 'construction_progress'`, then `(e.payload->>'pct_complete')::int` gives the percentage (5/10/20/.../95). Useful for "median time from 30% → 70%", "sites stalled above N% for >M months", "% complete distribution by operator".
- Other event types now available: `withdrawn`, `delayed`, `land_bank_purchase`, `construction_finished`. Avoid `permit_filed` and `expansion` — they don't exist in current data.
- All events for a state: drop the `provider_name` filter, add `WHERE s.state_code = 'VA'`.
- Power-related EDGAR only (any form): `WHERE e.is_power_related = true`.
**Common pitfalls:**
- **`events.event_date` contains future dates up to 2048-06-30** (source-CSV junk). Always clamp `event_date <= CURRENT_DATE`.
- The EDGAR `cik` is 10-digit zero-padded as a string. `companies.cik` is the same shape — direct equality works.
- 8-K coverage is sparse (only 8 rows total, 4 distinct CIKs as of 2026-05). Most material disclosures land as 10-Q (62 rows) or 10-K (27 rows). For "recent material events" prefer `WHERE form_type IN ('8-K','10-Q','10-K')`.

---

## Pattern 6: Anomaly / surge detection

**Business question it answers:** what metric just spiked or dropped beyond its 12-week trailing baseline?
**When to use:** synthesis "anomalies_today" section; "what should I look at this week"; weekly brief seed.
**Tables touched:** `anomalies`.
**SQL:**
```sql
SELECT metric_kind,
       dimension,
       period_end,
       value,
       baseline_mean,
       baseline_stddev,
       z_score,
       direction,
       sample_size,
       note
FROM anomalies
WHERE period_end >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY ABS(z_score) DESC
LIMIT 12;
```
**Tunable bits:** narrow `metric_kind = 'pjm_queue_mw'` etc., flip `direction = 'spike'` for surges only.
**Returns:** ranked anomalies by absolute z-score. Each row = one (metric_kind, dimension, period_end) outlier.
**Variants:**
- Hypothesizer fallback: if `period_end`-windowed query returns nothing, fall back to `WHERE DATE(detected_at) >= CURRENT_DATE - INTERVAL '30 days'`.
**Common pitfalls:**
- **`anomalies` is currently EMPTY (0 rows).** The `_anomaly_detection` cron runs daily but no signals have crossed the 2σ trailing-12-week threshold. Don't promise the user anomalies that aren't there — fall back to "no anomalies in the last N days" rather than fabricating.
- `metric_kind` enum is open-ended. Documented seeds: `pjm_queue_mw`, `permit_filings_va`, `edgar_capacity_mw`. New kinds may appear.
- `dimension` defaults to `'ALL'` when no sub-bucket is meaningful.

---

## Pattern 7: Cross-source triangulation (same MW across SEC + permit + ISO queue)

**Business question it answers:** does the SEC disclosure match the permit / ISO-queue filing? (Triangulation is the platform's core value-add — corroborating one signal with two more.)
**When to use:** validating a deal claim, building a confidence-weighted insight, answering "is this real".
**Tables touched:** `edgar_extractions`, `generator_permits`, `companies`, `sites` (optional demand-side endpoint).
**SQL (one canonical company across three sources):**
```sql
WITH target AS (
  SELECT id, canonical_name, ticker, cik
  FROM companies
  WHERE ticker = 'AMZN'  -- swap as needed
  ORDER BY id LIMIT 1   -- dedupe duplicate rows
),
edgar AS (
  SELECT 'edgar'::text     AS source,
         e.filing_date::text AS event_date,
         e.capacity_mw     AS mw,
         e.energy_source   AS detail,
         e.edgar_url       AS source_url,
         LEFT(e.excerpt, 160) AS context
  FROM edgar_extractions e, target t
  WHERE e.cik = t.cik
    AND (e.is_power_related = true OR e.capacity_mw IS NOT NULL)
    AND e.filing_date >= CURRENT_DATE - INTERVAL '12 months'
),
permits AS (
  SELECT 'permit'::text          AS source,
         g.issued_date::text     AS event_date,
         g.rated_mw_total        AS mw,
         g.fuel_type             AS detail,
         NULL::text              AS source_url,
         g.facility_name         AS context
  FROM generator_permits g, target t
  WHERE g.resolved_company_id = t.id
    AND (g.issued_date IS NULL OR g.issued_date >= CURRENT_DATE - INTERVAL '12 months')
),
sites AS (
  -- Pull activation date from the events table -- sites.activation_date is
  -- now NULL in raw SQL (Aterio dropped the inventory date columns).
  SELECT 'site'::text                                    AS source,
         (SELECT MIN(ev.event_date)::text
            FROM events ev
            WHERE ev.aterio_dc_uid = s.aterio_dc_uid
              AND ev.event_type = 'activation'
              AND ev.event_date <= CURRENT_DATE)        AS event_date,
         s.power_capacity_mw                             AS mw,
         s.stage                                         AS detail,
         s.datasheet_url                                 AS source_url,
         (s.building_name || ' (' || COALESCE(s.state_code,'?') || ')') AS context
  FROM sites s, target t
  WHERE s.provider_name ILIKE '%' || t.canonical_name || '%'
)
SELECT * FROM edgar
UNION ALL SELECT * FROM permits
UNION ALL SELECT * FROM sites
ORDER BY mw DESC NULLS LAST
LIMIT 50;
```
**Tunable bits:** target ticker / canonical_name; window length; min MW threshold (`AND mw >= 100`).
**Returns:** unified signal feed across edgar / permit / site for the named entity, sorted by MW.
**Variants:**
- Just SEC + permit (skip the site-side endpoint): drop the `sites` CTE.
- MW-bucket dedup: wrap with another CTE that buckets `mw` to 100-MW intervals and counts distinct sources per bucket — buckets with `>= 2` sources are corroborated.
**Common pitfalls:**
- `sites.activation_date` (and the other milestone-date columns on `sites`) are **NULL in raw SQL** — Aterio dropped them from the inventory CSV (May 2026). All historical milestone dates live in the `events` table. The query above already pulls activation from `events`; if you need a different milestone, swap `event_type = 'activation'` for `'announcement' / 'construction_start' / 'cancellation' / 'withdrawn'`. Clamp `event_date <= CURRENT_DATE` for historical analyses (future event rows are projections).
- `provider_name ILIKE '%amazon%'` will catch "Amazon AWS" AND "Amazon Web Services" AND occasionally false positives — review the matches. Tighter: `provider_name IN ('Amazon AWS', 'Amazon')`.
- The `companies` table has multiple rows per ticker (canonical-name aliases). `ORDER BY id LIMIT 1` picks the lowest-id canonical row, which is usually the short form ("Amazon" vs "Amazon.com Inc.").

---

## Pattern 8: Uncontracted / single-tenant capacity (commercial gap)

**Business question it answers:** which sites have built capacity but no named end-user — i.e. potentially contractable residual MW for a new offtaker?
**When to use:** opening move for any commercial-opportunity insight; mirrors hypothesizer's `uncontracted_capacity_top_sites`, `concentrated_offtake_sites`, `epa_echo_high_mw_no_known_customer` sections.
**Tables touched:** `sites`.
**SQL (top uncontracted sites):**
```sql
SELECT building_name,
       campus_name,
       provider_name,
       state_code,
       power_capacity_mw,
       aterio_est_mw,
       stage,
       datasheet_url
FROM sites
WHERE power_capacity_mw IS NOT NULL
  AND (end_user_companies IS NULL
       OR TRIM(end_user_companies) = ''
       OR LOWER(TRIM(end_user_companies)) IN ('null','[]'))
  AND stage ILIKE ANY (ARRAY['%active%','%construction%','%commissioning%'])
ORDER BY power_capacity_mw DESC NULLS LAST
LIMIT 12;
```
**SQL (single-tenant concentration — top quartile):**
```sql
WITH per_state AS (
  SELECT state_code,
         percentile_cont(0.75) WITHIN GROUP (ORDER BY power_capacity_mw)
           FILTER (WHERE power_capacity_mw IS NOT NULL) AS q3
  FROM sites
  WHERE state_code IS NOT NULL
  GROUP BY state_code
)
SELECT s.building_name, s.campus_name, s.provider_name, s.state_code,
       s.power_capacity_mw, s.end_user_companies, s.stage, ps.q3 AS state_q3_threshold
FROM sites s
JOIN per_state ps USING (state_code)
WHERE s.power_capacity_mw IS NOT NULL
  AND s.end_user_companies IS NOT NULL
  AND TRIM(s.end_user_companies) <> ''
  AND s.end_user_companies NOT LIKE '%,%'   -- exactly one named tenant
  AND ps.q3 IS NOT NULL
  AND s.power_capacity_mw >= ps.q3
ORDER BY s.power_capacity_mw DESC NULLS LAST
LIMIT 12;
```
**Tunable bits:** stage filter, state filter, MW floor (`AND power_capacity_mw >= 100`), top-N.
**Returns:** ranked sites/operators with the gap framing.
**Variants:**
- Developer-level (low median offtake count): see `_section_capacity_by_developer_with_low_offtake` in `agents/insights/hypothesizer.py:611`.
- Filter to AI facilities: `AND is_ai_facility = true`.
**Common pitfalls:**
- The four-way "no end user" sentinel test is critical — `end_user_companies` may be `NULL`, `''`, `'null'`, or `'[]'`. Don't simplify to `IS NULL`.
- `stage` includes "Active under construction" and "Operational" — use `ILIKE` not `=`.
- `power_capacity_mw` represents potential capacity; an active-stage site without a named tenant is a STRONGER opportunity signal than an announcement-stage one.

---

## Pattern 9: Permit filings by region (with MW where available)

**Business question it answers:** where are generators / building permits being filed right now, what's the cumulative MW?
**When to use:** state/region buildout pace; weekly brief input; mirrors hypothesizer's `new_permits_24h` and `epa_echo_new_records_24h`.
**Tables touched:** `building_permits`, `generator_permits`.
**SQL (building permits by month and county):**
```sql
SELECT DATE_TRUNC('month', issued_date)::date AS month,
       state,
       county,
       source,
       COUNT(*) AS permits,
       ROUND(SUM(valuation_usd)::numeric, 0) AS total_valuation_usd,
       SUM(square_footage)                   AS total_sqft
FROM building_permits
WHERE issued_date >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY 1, state, county, source
ORDER BY month DESC, total_valuation_usd DESC;
```
**SQL (generator permits by state, with MW):**
```sql
SELECT state_code,
       source,
       COUNT(*) AS permits,
       COUNT(*) FILTER (WHERE rated_mw_total IS NOT NULL) AS permits_with_mw,
       ROUND(SUM(rated_mw_total)::numeric, 0) AS total_rated_mw,
       MAX(issued_date) AS latest_issued
FROM generator_permits
WHERE issued_date >= CURRENT_DATE - INTERVAL '12 months'
   OR (issued_date IS NULL AND created_at >= CURRENT_DATE - INTERVAL '12 months')
GROUP BY state_code, source
ORDER BY total_rated_mw DESC NULLS LAST;
```
**Tunable bits:** date window, state filter, source filter (`source IN ('epa_echo','pjm')`).
**Returns:** monthly bucket per (state, county, source) with permit count + valuation + MW.
**Variants:**
- Top permittees in a state (raw): `SELECT permittee_raw_name, COUNT(*) FROM generator_permits WHERE state_code = 'VA' GROUP BY 1 ORDER BY 2 DESC LIMIT 20;`
- Cross to canonical via the resolver: see Pattern 3.
**Common pitfalls:**
- **`building_permits` has only two source feeds**: `loudoun_va` (271 rows) and `mesa_az` (76 rows). Don't claim national permit coverage — qualify the answer to "in our two-county sample".
- `pjm` ISO-queue rows in `generator_permits` (3,631 rows, the dominant source) usually have NULL `issued_date`. The `created_at` fallback in the WHERE clause catches them. PJM rows DO carry `rated_mw_total` reliably (smoke-test 2026-05-07: 13 N/ + 1 VA rows in last 12 mo total 5,155 MW).
- **`epa_echo`, `tceq`, `va_open_data`, `socrata_ny` rows have `rated_mw_total = NULL` in this warehouse** — the air-permit feeds parse facility identity but not nameplate capacity. Don't sum `rated_mw_total` and expect federal-permit MW totals; you'll only see PJM ISO-queue MW.
- `valuation_usd` is the declared construction cost on the application — not realised capex. Sum is illustrative, not authoritative.

---

## Pattern 10: AI-insights pipeline introspection

**Business question it answers:** what insights did this session emit, with what citations, and what's the cross-day "ongoing" lineage?
**When to use:** debugging the synthesis loop, evaluating insight quality, the V2 follow-up chat surface, "show me last cycle's output".
**Tables touched:** `ai_session`, `ai_insight`, `agent_citation`, `agent_chart`, `insight_thread`.
**SQL (recent insights for a session):**
```sql
SELECT i.idx,
       i.headline,
       i.confidence,
       i.materiality,
       i.skills_run,
       i.supporting_row_ids,
       i.created_at,
       (SELECT COUNT(*) FROM agent_citation WHERE insight_id = i.id) AS citations,
       (SELECT COUNT(*) FROM agent_chart    WHERE insight_id = i.id) AS charts
FROM ai_insight i
WHERE i.session_id = '<UUID>'::uuid
ORDER BY i.idx;
```
**SQL (citations attached to an insight):**
```sql
SELECT c.url,
       c.title,
       LEFT(c.snippet, 200) AS snippet,
       c.agree_or_disagree,
       c.rationale,
       c.search_query,
       c.provider,
       c.retrieved_at
FROM agent_citation c
WHERE c.insight_id = '<UUID>'::uuid
ORDER BY c.created_at;
```
**SQL (cross-day "ongoing" lineage):**
```sql
WITH RECURSIVE chain AS (
  SELECT id, headline, ongoing_of_id, created_at, 0 AS depth
  FROM ai_insight
  WHERE id = '<UUID>'::uuid
  UNION ALL
  SELECT i.id, i.headline, i.ongoing_of_id, i.created_at, c.depth + 1
  FROM ai_insight i
  JOIN chain c ON c.ongoing_of_id = i.id
)
SELECT * FROM chain ORDER BY depth;
```
**SQL (recent sessions and their yield):**
```sql
SELECT s.id, s.status, s.started_at, s.duration_ms, s.insights_emitted, s.budget_status,
       COUNT(i.id) AS actual_insights
FROM ai_session s
LEFT JOIN ai_insight i ON i.session_id = s.id
WHERE s.started_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY s.id
ORDER BY s.started_at DESC;
```
**Tunable bits:** swap `session_id` / `insight_id` UUIDs; window the recent-sessions view.
**Returns:** insight detail / citation list / ongoing chain / session yield.
**Variants:**
- Cron-only sessions: `WHERE s.created_by IS NOT NULL AND s.cron_run_date IS NOT NULL`.
- Failing sessions: `WHERE s.status IN ('degraded','failed')`.
**Common pitfalls:**
- **`ai_insight.citation_count` is denormalised but currently NOT updated** — use `(SELECT COUNT(*) FROM agent_citation WHERE insight_id = i.id)` for the actual count. Sample inspection: 5 recent insights all show `citation_count=0` but actually have 3 citations each.
- `agent_tool_call` is empty (0 rows) — tool-call audit currently lives in `agent_message.tool_calls` JSONB. Don't query `agent_tool_call` for "what tools did this session run".
- `supporting_row_ids` is JSONB — to expand: `jsonb_array_elements_text(supporting_row_ids)`.

---

## Pattern 11: Coverage gaps (which pillars / states are stale)

**Business question it answers:** which (pillar × state × source) combinations are stale or partial — i.e. where do we lack data?
**When to use:** trustworthiness framing, "what should we improve next", input to the synthesis `coverage_gaps` section.
**Tables touched:** `data_coverage`.
**SQL:**
```sql
SELECT pillar,
       state_code,
       source,
       coverage_status,
       record_count,
       last_ingested_at,
       freshness_sla_hours,
       LEFT(notes, 120) AS notes
FROM data_coverage
WHERE coverage_status IN ('partial','pending','unavailable')
ORDER BY last_ingested_at ASC NULLS FIRST,
         pillar, state_code
LIMIT 25;
```
**Tunable bits:** filter `pillar = 'power'`, `state_code = 'VA'`, or include `coverage_status = 'federal_baseline'` for a broader view.
**Returns:** stalest (pillar, state, source) tuples first.
**Variants:**
- Per-pillar summary: `SELECT pillar, coverage_status, COUNT(*) FROM data_coverage GROUP BY 1, 2 ORDER BY 1, 2;`
- "what's freshest": flip ORDER BY to `DESC NULLS LAST`.
**Common pitfalls:**
- `coverage_status` is one of {`full`, `partial`, `federal_baseline`, `pending`, `unavailable`} — not boolean.
- `freshness_sla_hours` is the *target* SLA in hours; `last_ingested_at` is when the row was actually filled. Compare them in the prose layer to flag SLA breaches.

---

## Pattern 12: Ingestion-run health (when did we last ingest source X?)

**Business question it answers:** is data X fresh? Did the last run for adapter Y succeed?
**When to use:** "is the EDGAR data current?", weekly brief context, debugging stale results.
**Tables touched:** `ingestion_runs`.
**SQL:**
```sql
SELECT adapter_name,
       MAX(started_at)                                    AS last_started,
       MAX(started_at) FILTER (WHERE status='success')    AS last_success,
       MAX(started_at) FILTER (WHERE status='failure')    AS last_failure,
       COUNT(*) FILTER (WHERE started_at >= CURRENT_DATE - INTERVAL '7 days') AS runs_7d,
       SUM(records_stored) FILTER (WHERE started_at >= CURRENT_DATE - INTERVAL '7 days') AS rows_stored_7d
FROM ingestion_runs
WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY adapter_name
ORDER BY last_started DESC NULLS LAST;
```
**Tunable bits:** window length, filter to a single adapter (`WHERE adapter_name = 'edgar'`).
**Returns:** adapter-by-adapter freshness scorecard.
**Variants:**
- Just failures: `WHERE status IN ('failure','partial_failure') ORDER BY started_at DESC`.
- Daily success rate: `GROUP BY DATE_TRUNC('day', started_at), status`.
**Common pitfalls:**
- Internal cron jobs (prefixed `_`) appear here too: `_coverage_refresh`, `_stale_check`, `_insights_daily`, `_anomaly_detection`, `_cache_cleanup`, `_weekly_brief`. Distinguish them from data adapters when reporting.
- `records_stored` for cron jobs is usually 0 — they don't stage rows, they audit.
- `error_log` is JSONB — for failure detail use `error_log->>'message'`.

---

## Cross-pattern composition tips

- **Always emit a citation.** Most fact tables carry a URL: `sites.datasheet_url`, `sites.permit_url`, `events.source_url`, `edgar_extractions.edgar_url`, `agent_citation.url`. Surface one of these inline.
- **Prefer `JOIN companies … WHERE c.ticker = 'XYZ'` over `WHERE provider_name = 'X'`** — tickers are stable, names drift (`'Amazon'` vs `'Amazon AWS'` vs `'Amazon.com Inc.'`).
- **Use `ROUND(SUM(...)::numeric, 0)`** — `double precision` outputs scientific notation in some psql clients; numeric round produces a clean integer for the agent's prose layer.
- **When a query returns 0 rows, don't silently fail — say "no rows match"** and try a broader window or drop a constraint, then say what you tried.
