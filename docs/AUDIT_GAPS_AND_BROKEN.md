# AUDIT — Gaps & Broken Surfaces

**Date:** 2026-05-20
**Auditor:** dev-team Orchestrator (PM-led, read-only)
**Branch:** `feat/save-and-history` (uncommitted refactor: +9,024 / −58,072 across 122 files)
**Method:** Repo walk · router-vs-frontend consumer matrix · data-freshness mtime scan · cron inventory · `pytest` (449 tests) · `eslint` + `tsc` + `vite build` · uvicorn smoke-start + curl probes of 36 GET routes · AI-agent prompt review · half-finished-work scan
**Audience:** OCI leadership (gabrielle.lyu@oracle.com). Product is being reoriented from the 5-layer framework to an explicit **OCI Opportunities & Threats** framing — findings are prioritised against that pivot.

---

## 1. Executive summary

### Top 5 BROKEN right now

| # | Severity | Issue | Why it matters |
|---|---|---|---|
| B1 | **P0** | **Frontend production build fails.** `tsc -b` errors out with 8 TypeScript errors (`CompanyRow` undefined in `CompaniesTab.tsx:674-675`, Recharts prop mismatch in `CounterpartyPieCard.tsx:221`, `PowerTab.tsx:293` discriminated-union overlap, plus 4 unused-import errors). `vite build` never runs. The site as deployed today is a stale bundle; the next deploy from `feat/save-and-history` will fail at CI. | Ship-blocker for any release from this branch. |
| B2 | **P0** | **Vite dev server exposed to the public internet.** `logs/frontend.log` (mtime today 18:44 UTC) is full of hostile scanner traffic: `/etc/passwd` traversals (UTF-8 over-long encodings), `<script>alert(...)</script>` injections, attempted `phpunit/eval-stdin.php` RCE probes, and repeated `.env` / `.env.local` exfiltration attempts (Vite warns "outside serving allow list" but still leaks file existence). This is a **security incident**, not just a misconfiguration. | Internal CI for OCI execs, exposed publicly with no auth. |
| B3 | **P0** | **AI Insights tab polls a deleted endpoint every 30 s.** `frontend/src/hooks/useOpenQuestionsPolling.ts:69` fetches `GET /api/insights/open-questions`. The handler was removed from the backend on this branch (its test file `backend/tests/test_open_questions_route.py` was deleted; `grep -r open_questions backend/routers/` returns no matches). Every AI Insights view → 404 every 30 s, repeated console errors, "Tracked Questions" sidebar permanently shows stale/empty state. | Most-used tab silently broken. |
| B4 | **P0** | **Alpha Vantage 2026Q2 earnings pipeline writes empty cache files.** Today's 06:45–06:50 UTC cron run produced 20 files, each 62–66 bytes, all containing `{"symbol": "X", "quarter": "2026Q2", "transcript": []}` (AMZN, GOOGL, META, INTC, AMD, AVGO, AMKR, AEP, DUK, SO, IBM, NEE, CEG, TLN, VST, AES, EXC, D, ALAB, AAPL). Empty payloads are cached → next run serves stale empties → AI Insights synthesis (Mon 09:00 UTC) cannot cite any Q2 transcript. Mock-shaped data leaking into the "real" earnings surface. | "Forward-looking guidance from earnings transcripts" hypothesis band (per `synthesis_rules.md` and `AI_INSIGHTS_PLAYBOOK.md`) is silently disabled. |
| B5 | **P0** | **`tiktoken` missing → earnings chunker emits zero passages.** Backend pytest: 448/449 pass; the failure is `test_earnings_adapter.py::test_adapter_run_happy_path_writes_transcript_passages_and_audit` (`assert 0 == 1`). Adapter logs `earnings_chunker.tiktoken_unavailable`. Compounds B4: even on quarters where AV returns transcripts, none of them reach the search corpus as embedded passages, so `search_documents(source='earnings')` returns empty. | Earnings transcripts are effectively absent from the AI-Insights evidence base even when AV works. |

### Top 5 MISSING vs the OCI Opportunities & Threats (O&T) pivot

| # | Pri | What's missing | O&T relevance |
|---|---|---|---|
| M1 | **P0** | **OCI Share Trend timeseries surface.** `/api/{tab}/oci-share` exists but: (a) only `power` and `permits` are implemented — `gpu`, `nics`, `tsmc`, `triangulation` return hardcoded `null` with note `"No real data available for this tab yet"`; (b) it is a single point-in-time number, not a trend; (c) zero frontend consumers — no tab renders it. | The single most-asked exec question — "is OCI's share moving?" — is unanswerable in the UI today. |
| M2 | **P0** | **Threat / Anomaly feed in the UI.** `GET /api/anomalies/recent` exists, queries the `Anomaly` table (Z-score ≥ 2σ change-detection on permit filings, MW deltas, queue movements). Backend probe returned `200 {data: [], count: 0}` — table is empty, suggesting `anomaly_detection_nightly` cron either never wrote rows or rows were purged. No UI consumer, no badge, no alert. | The O&T framing's threat half is invisible. There is nowhere on the site to see "what changed that should worry us." |
| M3 | **P0** | **Customer-concentration / counterparty exposure tracking.** `GET /api/companies/{id}/counterparties` and `GET /api/companies/{id}/role-distribution` are implemented (return 200 with data) but BOTH are orphans — `CompaniesTab` is the only consumer of `/api/companies/*` and it currently doesn't ship at all (B1: `CompanyRow` undefined). There is no per-OCI-customer page, no Top-N counterparty pie, no "Customer X disclosed multi-GW to peer Y" surface. | Threat framing #2 from the playbook ("customer poaching") has zero UI. |
| M4 | **P0** | **Competitor capex deltas / EDGAR-frames surface.** `/api/edgar/frames/{concept}/{period}` is wired and returns real XBRL frames (Assets, PropertyPlantAndEquipmentNet, etc.). No frontend consumer. The Earnings tab only scores transcripts on 4 sentiment axes; nothing renders the actual capex movement curve per hyperscaler — the L5 spine of "who's spending more, faster, where." | Opportunity framing #3 ("region/queue arbitrage when a hyperscaler pulls back") needs capex deceleration visible. |
| M5 | **P0** | **Executive landing page / Weekly Brief in UI.** `/api/brief/latest` returns a real `BriefRun` row (id=6, generated_at=2026-05-17T23:00Z, 10 weekly briefs in DB). `WeeklyBriefCard.tsx` exists in the frontend tree but is not wired into `App.tsx` / `TabNav.tsx`. The default landing is still `DataCentersTab` — an L4 inventory view, not an O&T summary. | Leadership opens the tool and sees a sites table, not "here is this week's opportunity + threat." |

### Headline numbers

- **83** backend routes total · **51** with a frontend consumer · **32 orphan (38.6%)** · **1 confirmed 404 risk wired** (`/api/insights/open-questions`) · **1 missing-endpoint hit** (`/api/insights/health` polled by AIInsightsTab) · **501 stub** still live (`/api/agent/qa/conversations/{id}`).
- **449** backend tests · **1** failing (tiktoken).
- **Frontend lint:** 26 errors + 7 warnings; predominantly `react-hooks/set-state-in-effect`.
- **Frontend build:** **FAILS** (8 TS errors).
- **Cron jobs:** 13 configured. 6 confirmed healthy via artifact mtimes. 4 DB-backed jobs unverifiable from disk. **1 failing silently** (earnings_transcripts_daily emits empties).
- **In-flight refactor:** 122 files modified on `feat/save-and-history`, **net −49,048 lines**. 5 backend test files deleted (incl. `test_open_questions_route.py`). 997-line diff on `CompaniesTab.tsx` (currently broken). Synthesis pipeline prompts being edited live.

---

## 2. Broken-now table

Format: severity · file:line refs · repro steps (or evidence).

| ID | Sev | Component | File / refs | Symptom | Repro / evidence |
|---|---|---|---|---|---|
| BR-01 | **P0** | Frontend build | `frontend/src/components/tabs/CompaniesTab.tsx:674,675` | `TS2304: Cannot find name 'CompanyRow'` (×2) | `cd frontend && npm run build` → fails. |
| BR-02 | **P0** | Frontend build | `frontend/src/components/tabs/companies/CounterpartyPieCard.tsx:221` | `TS2769: No overload matches this call.` Recharts `<Pie>` does not accept `sortValues` prop. | Same command as BR-01. |
| BR-03 | **P0** | Frontend build | `frontend/src/components/tabs/PowerTab.tsx:293` | `TS2367: This comparison appears to be unintentional.` Comparing `'live' \| 'curated_archived' \| undefined` against `'archive'`. | Same. Indicates a recent rename ("archive" → "curated_archived") that wasn't propagated. |
| BR-04 | **P0** | Frontend build | `frontend/src/components/earnings/EarningsDetailModal.tsx:5,199` | `TS6133/TS6196`: `normalizeSentiment` and `RawTranscriptResponse` declared but never used. Dead imports left over from the earnings-tab refactor. | Same. |
| BR-05 | **P0** | Frontend build | `frontend/src/components/tabs/ai-insights/__tests__/InsightSidebar.test.tsx:16` | `TS6133`: unused `waitFor` import. | Same. |
| BR-06 | **P0** | Frontend ↔ backend contract | `frontend/src/hooks/useOpenQuestionsPolling.ts:69`, `frontend/src/components/tabs/ai-insights/tracked-questions/TrackedQuestionsSidebar.tsx:10,12,61` | Polls `GET ${baseUrl}/api/insights/open-questions` every 30 s. Endpoint removed from backend on this branch — `grep -r open_questions backend/routers/` returns no matches; `backend/tests/test_open_questions_route.py` deleted. | Open AI Insights tab → DevTools → Network → see 404 every 30 s. |
| BR-07 | **P0** | Frontend ↔ backend contract | `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx` (calls `/api/insights/health`) | Backend `insights` router exposes no `/health` sub-route. Probe of `/api/insights/health` returns 404. | Backend openapi.json does not list it; route inventory in §5 confirms. |
| BR-08 | **P0** | Security / deployment | `logs/frontend.log` (mtime 2026-05-20 18:44) | Vite dev server exposed to public internet. Hostile scanners hitting `.env`, `.env.local`, `/etc/passwd` (UTF-8 over-long), XSS GETs, `phpunit/eval-stdin.php` RCE probes. Vite "outside serving allow list" warnings leak file existence. | `grep -c "outside of Vite serving allow list" logs/frontend.log` → many hundreds. `ps -ef \| grep vite` shows long-running dev server bound to public iface. |
| BR-09 | **P0** | Data pipeline | `backend/data/cache/earnings_av_transcript_*_2026Q2.json` (20 files, 62–66 B each, mtime today 06:45–06:50) | Alpha Vantage call returns HTTP 200 with `{"transcript": []}`; adapter caches the empty result. `_check_throttled()` passes (no `Information` / `Note` keys) so it never retries. Next run serves stale empties. | `head -c 500 backend/data/cache/earnings_av_transcript_AMZN_2026Q2.json` → `{"symbol":"AMZN","quarter":"2026Q2","transcript":[]}`. |
| BR-10 | **P0** | Search corpus | `backend/ingestion/earnings_chunker.py` (logs `earnings_chunker.tiktoken_unavailable`) | `tiktoken` missing in env → chunker emits 0 passages → `search_documents(source='earnings')` returns nothing → synthesis cannot cite transcripts. | `cd backend && python3 -m pytest tests/test_earnings_adapter.py -x` → 1 failure (`assert 0 == 1`). |
| BR-11 | P1 | OCI O&T endpoint | `backend/routers/oci_share.py:40,68-86` | Hardcoded `_NO_DATA_TABS = {"gpu", "nics", "tsmc", "triangulation"}` return `oci_pct=null` with `note: "No real data available for this tab yet"`. Power + permits work. | `curl localhost:8000/api/gpu/oci-share` → null body. |
| BR-12 | P1 | UI labelling | `frontend/src/components/layout/TabNav.tsx` (TriangulationTab badge), `routers/triangulation.py` | Tab labelled `[MOCK]` even though `/api/triangulation/l1` and `/l2` return real data (200 with rows) per route probe. Wrong honesty signal. | Backend probe (§5) returns rows; UI still shows MOCK badge. |
| BR-13 | P1 | API stub | `backend/routers/agent.py` | `GET /api/agent/qa/conversations/{id}` returns `501 {"detail":"Not implemented -- scheduled for Phase 1"}`. Phase 1 is long done (we're on v2 cutover). | `curl localhost:8000/api/agent/qa/conversations/1` → 501. |
| BR-14 | P1 | Pydantic deprecations | `backend/routers/companies.py:87,90,95` | Three `Query(regex=...)` uses — Pydantic v2 expects `pattern=`. Logged as `DeprecationWarning` during pytest. Will hard-error on next Pydantic major. | pytest output: 3× DeprecationWarning. |
| BR-15 | P1 | Lint / quality | `frontend/src/hooks/useApi.ts:77`, `useInsightSubscription.ts:47`, `useOpenQuestionsPolling.ts:128`, `frontend/src/components/tabs/ai-insights/CitationPill.tsx:91,225`, `SubscribeButton.tsx:62` | 13× `react-hooks/set-state-in-effect`, 8× `react-hooks/exhaustive-deps`, 1× `react-hooks/refs`, 1× `react-hooks/purity`. The `setState-in-effect` pattern is the most likely root cause of the repeat-fetch storms observed in `backend.log` (`GET /api/sites/?page_size=10000` and `GET /api/health` fired 4–6× per visible user action). | `cd frontend && npm run lint` → 26 errors, 7 warnings. |
| BR-16 | P1 | Observability | `logs/backend.log` (mtime 2026-05-14 22:02) | Canonical backend log file frozen since May 14, but cache mtimes prove crons are running today. Either log was rotated and the new file isn't in `logs/`, or the prod backend writes elsewhere. Operators can't tail anything fresh. | `ls -lt logs/`. |
| BR-17 | P1 | In-flight refactor | `git status` (122 staged files, +9,024 / −58,072) | 5 backend test files deleted without replacement: `test_open_questions_route.py`, `test_hypothesizer_factpack.py`, `test_hypothesizer_supply_demand_sections.py`, `test_phase_d_router_cutover.py`, `test_registry_v2.py`, `test_agentic_synthesis_v2.py`. `useOpenQuestionsPolling.ts` still references a now-deleted endpoint (BR-06). The branch must not be merged in its current state. | `git diff --stat HEAD`. |
| BR-18 | P2 | Data staleness | `backend/data/cache/filing_d158175d8k_htm.json` | Single 8-K cache file mtime 2026-05-19 06:00; nothing newer. Either no qualifying 8-Ks dropped, or the 8-K-targeted ingest path is silent-failing. Worth a sanity probe. | `ls -lt backend/data/cache/filing_*.json`. |
| BR-19 | P2 | Data staleness | `datasets/Energy Project Inventory*.xlsx`, `datasets/Data Dictionary*.xlsx` | 13 days since last refresh. Manually-refreshed reference data; document expected cadence. | `ls -l datasets/`. |
| BR-20 | P2 | Tooling | `backend/pyproject.toml` declares `ruff` as a dev dep | Not installed in the active env (`python3 -m ruff` → `ModuleNotFoundError`). No backend lint signal at all. | qa agent §"Backend lint" section. |
| BR-21 | P2 | Tooling | `backend/pyproject.toml` | No `mypy` / `pyright` declared or configured. Backend has zero static type signal. | Same. |
| BR-22 | P2 | UX honesty | `routers/anomalies.py:19,49-61` | `MOCK_DATA` env flag still wired — if anyone sets `MOCK_DATA=1` the route silently returns a fake VA permit spike with `confidence: 0.5`. No way for a UI badge to know it's mock. | Read source. |
| BR-23 | P2 | Data-driven 404 | `GET /api/coverage/{pillar}` for `pillar=water` | Returns `404 {"detail":"No coverage data found for pillar 'water'"}`. Not a code bug; reflects missing seed. But it's served at the same status code as a true not-found, which is brittle. | Route probe (§5). |
| BR-24 | P2 | Console noise | Repeated `GET /api/health` and `GET /api/sites/?page_size=10000` bursts in `logs/backend.log` (5–6 calls per visible user action) | Effect-driven over-polling. Tied to BR-15 `setState-in-effect` lint findings. Wastes scheduler bandwidth on the LL Stack health probe. | `grep -c "/api/health" logs/backend.log`. |

---

## 3. Missing features — prioritised against O&T framing

The product is being reoriented around "where can OCI win" / "where is OCI exposed." Missing features are scored by how directly they enable that framing.

### 3.1 P0 — blocks the O&T pivot

| ID | Missing feature | What's there now | What's needed | O&T axis |
|---|---|---|---|---|
| MS-01 | **OCI Share Trend page** — share-of-MW / share-of-permits / share-of-counterparty timeseries vs MSFT / GOOG / AMZN / META / CRWV. | `/api/{tab}/oci-share` is point-in-time only and only works for `power`+`permits`; gpu/nics/tsmc/triangulation hardcoded null; **zero UI consumers**. | New `oci/share-timeseries` endpoint, plus an "OCI Position" tab as the new default landing showing share Δ week-over-week + ranking change. | Both — denominator for every claim. |
| MS-02 | **Threat / Anomaly feed.** | `/api/anomalies/recent` exists (orphan); Anomaly table currently empty in dev. `anomaly_detection_nightly` cron runs at 02:30 UTC but no artifact to verify. | (a) Verify nightly job actually writes rows. (b) Surface as a "Threats this week" badge on the landing page + a dedicated Anomalies tab + push notifications for `z_score ≥ 3`. | **Threat.** |
| MS-03 | **Customer-concentration / counterparty exposure.** | `/api/companies/{id}/counterparties` + `/role-distribution` exist (orphans). `CounterpartyPieCard.tsx` exists but broken (BR-02). `docs/prds/counterparties-pies.md` is the PRD. | Wire CompaniesTab → counterparty pies. Add a "Customer Risk" view: for each major OCI customer, show their disclosed compute commitments to peers in the last 90 days. | **Threat** (customer poaching). |
| MS-04 | **Competitor capex deltas** — quarterly capex movement per hyperscaler, time-to-power deceleration signals. | `/api/edgar/frames/{concept}/{period}` returns XBRL frames (orphan). No UI. | Per-player capex curve chart, plus "delta vs prior 2 quarters" colorised. Pair with site-count / MW deltas to find pacing gaps. | **Both** — opportunity if peer X slows, threat if peer Y accelerates. |
| MS-05 | **Executive Brief landing page.** | `/api/brief/latest` returns a real `BriefRun` (10 in DB, last 2026-05-17); `WeeklyBriefCard.tsx` exists but not mounted in `App.tsx`/`TabNav.tsx`. Default landing is `DataCentersTab`. | Replace default landing with a brief view: this-week opportunity (1), this-week threat (1), top-3 insights, top-3 anomalies, fresh permit / 8-K diff. | **Both** — the entire framing in one screen. |
| MS-06 | **Earnings forward-looking guidance feed.** | EarningsTab scores 4 sentiment axes; doesn't surface what the CEO actually said about AI / power / capex commitments. AV Q2 transcript pipeline is broken (BR-09, BR-10). | Fix B4/B5 first; then a "Forward Guidance" view: per-ticker latest call, capex commentary, AI-spend language, sentiment Δ vs prior call. Required by `synthesis_rules.md` "Forward-looking guidance" hypothesis band. | **Threat** (peer escalates) / **Opportunity** (peer caveats). |

### 3.2 P1 — strengthens the O&T pivot

| ID | Missing feature | What's needed | O&T axis |
|---|---|---|---|
| MS-07 | **Neo-cloud / untenanted-capacity tracker.** Playbook calls this "THE MOST OCI-ACTIONABLE HYPOTHESIS." Today it lives only inside AI Insights prose. Needs a dedicated tab: ranked list of Crusoe / CoreWeave / Lambda / Aligned / Compass / CyrusOne / Stack / QTS / Vantage by untenanted MW × stage × geography. | New tab from `sites` filtered by `provider_name in (neo-cloud set) AND end_user_companies IS NULL`. Sort by stage + MW. | **Opportunity** (offtake). |
| MS-08 | **Region / ISO exclusion view.** Per playbook ("Peer X absorbed N% of [state]'s 2026 substation queue — OCI's [region] expansion blocked"). | Map: per-state queue saturation by peer × queue position × estimated time-to-power. | **Threat**. |
| MS-09 | **Vendor / supply lock-up signal.** GPU + HBM + optics commit-share by buyer. | Already partially in GPUSupplyTab + NICsOpticsTab + TSMC — needs a per-vendor "who absorbed how much capacity this quarter" cut. | **Threat** (supply contention). |
| MS-10 | **Press-releases recent feed.** `/api/press-releases/recent` is an orphan. | Wire as a small "What changed today" strip on the landing. | Both. |
| MS-11 | **Energy projects view.** `/api/energy-projects/` is an orphan; the L1 GW-by-state×company joins are computable but unsurfaced. | New L1 supply-availability tab. | Both. |
| MS-12 | **Per-site detail page.** `/api/sites/{aterio_dc_uid}` and `/role-summary` are orphans (only the list is consumed). | Site drill-in with timeline (events), role-summary, milestone history. Already half-built in `SiteDetail.tsx`. | Both. |
| MS-13 | **Power timeseries chart.** `/api/power/timeseries` and `/api/power/gw-summary` are orphans. | Add to PowerTab. | Both. |
| MS-14 | **Coverage / provenance badges.** `/api/coverage/*` (3 routes) all orphan. Tabs don't show "as-of" / "% real" / "% mock" anywhere. Triangulation tab is mislabelled MOCK (BR-12). | Standard `<CoverageBadge>` on every chart card, sourced from coverage endpoint. | Trust. |
| MS-15 | **Tracked Questions (Open Questions).** Hook + sidebar exist (`useOpenQuestionsPolling`, `TrackedQuestionsSidebar.tsx`); backend endpoint deleted on this branch (BR-06). | Decide: re-implement endpoint, or remove sidebar. Don't ship half. | Both. |
| MS-16 | **Satellite imagery integration.** `/api/satellite/`, `/api/satellite/sites` orphan. | Per-site phase-detection (Sentinel-2) panel on site detail view. | Both. |

### 3.3 P2 — improves framing but not gating

| ID | Missing feature | O&T axis |
|---|---|---|
| MS-17 | L2 (Computing Product) surface — $/GPU-hour and $/MW-month comparisons (the entire layer is absent per `docs/UX_GAPS_AND_FLOW_PROPOSAL.md` §3.6). | Opportunity (price pressure). |
| MS-18 | L5 (Capital & Timeline) view — time-to-power, depreciation-cycle, project-finance flow. Fragmented today across 3 tabs (per `UX_GAPS_AND_FLOW_PROPOSAL.md` §3.7). | Both. |
| MS-19 | MFU (Model FLOPs Utilization) metric — not in UI anywhere (`UX_GAPS_AND_FLOW_PROPOSAL.md` §1.3 calls it "the asymmetric lever"). | Opportunity (OCI's efficiency story). |
| MS-20 | LLC → parent resolution review queue UI. `POST /api/agent/llc-resolve/{permittee_id}` is an orphan handler. | Both (data quality). |
| MS-21 | Saved-insight subscription / digest delivery — `SubscribeButton.tsx` exists and the endpoint works, but no email/Slack/Teams delivery is wired. | Both (distribution). |
| MS-22 | Right-drawer "AI Insights about THIS chart" — UX_GAPS proposes this; today insights are isolated to their tab. | Both (context). |

---

## 4. Data freshness scorecard

Today is **2026-05-20**. Backend cache lives under `backend/data/cache/`. Aterio under `backend/data/aterio_archive/`. Static refs under repo root `datasets/`.

| Source | File pattern / table | Expected cadence | Last successful refresh | Status | Evidence |
|---|---|---|---|---|---|
| Alpha Vantage **earnings calendar** | `earnings_av_calendar.json` | Daily 06:45 UTC | 2026-05-20 06:45 UTC | ✅ FRESH | 1 file, 708 KB |
| Alpha Vantage **earnings transcripts (historical Q1/Q4)** | `earnings_av_transcript_*_{2025Q4,2026Q1}.json` | Daily when in-scope | 2026-05-19 06:49 UTC | ✅ FRESH | AEP Q1 70 KB · DUK Q1 37 KB · SO Q1 55 KB |
| Alpha Vantage **earnings transcripts (current Q2)** | `earnings_av_transcript_*_2026Q2.json` | Daily 06:45 UTC | 2026-05-20 06:50 UTC | 🟥 **FAILING SILENTLY** | 20 tickers, each 62–66 B; payload `{"transcript": []}`; empties cached → won't retry. **See BR-09.** |
| EDGAR **company submissions** | `submissions_XXXXXXX.json` | Daily 06:15 UTC | 2026-05-20 06:15 UTC | ✅ FRESH | 22 of 47 files modified today; sizes 280–330 KB |
| EDGAR **10-K/10-Q quarterly** | `real_quarterly_20260504/05/06.json` | Daily 06:15 UTC | 2026-05-19 06:15 UTC | ✅ FRESH | 3 rolling files, 2.8–4.3 MB |
| EDGAR **8-K filings** | `filing_*8k_htm.json` | Daily | 2026-05-19 06:00 UTC | ⚠️ 1 day stale | Only 1 file; either no qualifying 8-Ks or silent miss. Worth a manual probe. |
| Aterio **inventory** | `aterio_archive/{YYYY-MM-DD}/inventory/*.csv` | Daily 11:30 PT | 2026-05-20 18:30 UTC | ✅ FRESH | Daily directory present |
| Aterio **events** | `aterio_archive/{YYYY-MM-DD}/events/*.csv` | Daily 11:30 PT | 2026-05-20 18:30 UTC | ✅ FRESH | Daily directory present |
| **Anomalies** | DB `anomalies` table | Nightly 02:30 UTC | Unknown | ⚠️ UNVERIFIED | `GET /api/anomalies/recent` returns `[]` — either cron never wrote rows or table empty. **See MS-02.** |
| **County permits** | DB `building_permits` | Daily 06:30 UTC | Unknown | ⚠️ UNVERIFIED | No file artifacts. Live DB query needed. |
| **State permits** | DB `building_permits` (state) | Daily 07:00 UTC | Unknown | ⚠️ UNVERIFIED | Same. |
| **EPA ECHO air permits** | DB `generator_permits` (federal) | Daily 08:00 UTC | Unknown | ⚠️ UNVERIFIED | Same. |
| **Coverage rollup** | DB `data_coverage` | Hourly :00 | 2026-05-14 22:00 (last log) | ⚠️ UNVERIFIED post-May-14 | `coverage_refresh: heartbeat OK` last seen in old log. **See BR-16.** |
| **Weekly brief** | DB `brief_runs` | Sun 23:00 UTC | 2026-05-17 23:00 UTC | ✅ FRESH | `/api/brief/latest` → id=6, 10 rows in history |
| **AI Insights weekly run** | DB `ai_sessions` | Mon 09:00 UTC | 2026-05-18 09:00 UTC (expected) | ✅ FRESH | `/api/insights/latest` returns `status: complete`; confirmed by memory note `feedback_ai_insights_weekly_cadence` |
| **Static datasets** | `datasets/*.xlsx` | Quarterly manual | 2026-05-07 | ⚠️ 13 days, acceptable | Energy Project Inventory, Data Dictionary |
| **Backend raw scratch** | `backend/data/raw/test_permit.pdf` | Ad-hoc | 2026-04-29 | n/a (test fixture) | Single 2 KB test file |

**Summary:** 7 fresh, 1 acceptable-stale, 4 unverifiable (DB-backed, no log signal post-May-14), **1 P0 silent failure**.

---

## 5. Backend router health matrix

Result of `curl localhost:8000/<route>` against a freshly-started uvicorn (SCHEDULER_ENABLED=0, no auth) on this branch. Status code · consumer column from §5 + the routers agent's full matrix.

### 5.1 Routes consumed by a UI tab — should never break

| Method | Path | Status | Consumer | Notes |
|---|---|---|---|---|
| GET | `/api/sites/` | 200 | DataCentersTab | OK |
| GET | `/api/power/capacity` | 200 | PowerTab | OK |
| GET | `/api/power/announcements` | 200 | PowerTab | OK |
| GET | `/api/permits/` | 200 | PermitsTab | OK |
| GET | `/api/permits/building` | 200 | PermitsTab | OK |
| GET | `/api/companies/` | 200 | CompaniesTab | OK, but tab itself fails to build (BR-01) |
| GET | `/api/companies/aggregate` | 200 | CompaniesTab | OK, total_companies=1292, total_mw=109,280 |
| GET | `/api/companies/{id}` | 200 | CompaniesTab | OK |
| GET | `/api/companies/{id}/role-summary` | 200 | CompaniesTab | OK |
| GET | `/api/companies/{id}/sites` | 200 | CompaniesTab | OK |
| GET | `/api/companies/{id}/filings` | 200 | CompaniesTab | OK |
| GET | `/api/companies/{id}/earnings` | 200 | CompaniesTab | OK |
| GET | `/api/gpu/supply` | 200 | GPUSupplyTab | OK |
| GET | `/api/supply-chain/nics` | 200 | NICsOpticsTab | OK |
| GET | `/api/supply-chain/tsmc` | 200 | TSMCTab | OK |
| GET | `/api/triangulation/l1` | 200 | TriangulationTab | OK — tab still mis-labelled MOCK (BR-12) |
| GET | `/api/triangulation/l2` | 200 | TriangulationTab | OK |
| GET | `/api/sources/overview` | 200 | SourcesTab | OK |
| GET | `/api/earnings` | 200 | EarningsTab | OK — but Q2 corpus is empty (BR-09) |
| POST | `/api/insights/sessions` | (POST) | AIInsightsTab | OK per code path |
| GET | `/api/insights/sessions/{id}/stream` | (SSE) | AIInsightsTab | Not probed (long-poll) |
| GET | `/api/insights/latest` | 200 | AIInsightsTab + SavedInsightsHook | OK, session status=complete |
| GET | `/api/insights/saved` | 200 | SavedInsightsSection | OK |
| GET | `/api/insights/sessions` | 200 | PastRunsSection | OK |
| GET | `/api/insights/insights/{id}` | 404 (with zero-UUID) | InsightDetailPane | Expected 404 path |
| GET | `/api/insights/insights/{id}/chat` | 404 (with zero-UUID) | InsightChatDock | Expected |
| POST | `/api/insights/insights/{id}/chat` | (SSE) | InsightChatDock | OK per code |
| POST/DELETE | `/api/insights/insights/{id}/subscribe` | OK per code | SubscribeButton | OK |
| POST | `/api/qa/ask` | (SSE) | ChatPanel | OK |
| GET | `/api/health` | 200 | AIInsightsTab | `{status: ok, db: connected, llama_stack: connected, agents_active: 13}` |

### 5.2 Routes wired into the UI but with NO backend handler

| Method | Path | Status | Caller | Severity |
|---|---|---|---|---|
| GET | `/api/insights/open-questions` | **404** (no handler) | `useOpenQuestionsPolling.ts` → `TrackedQuestionsSidebar` | **P0 — BR-06** |
| GET | `/api/insights/health` | **404** (no handler) | `AIInsightsTab.tsx` | **P0 — BR-07** |

### 5.3 Backend routes implemented but with no UI consumer (orphans)

32 of 83 backend routes are orphans (38.6%). Prioritised by O&T relevance:

| Method | Path | Status | Why it matters for O&T pivot |
|---|---|---|---|
| GET | `/api/{tab}/oci-share` | 200 | **The headline OCI metric, with no UI surface.** Only `power`+`permits` are populated; gpu/nics/tsmc/triangulation hardcoded null. (MS-01) |
| GET | `/api/anomalies/recent` | 200 (empty) | **The threat half of O&T.** (MS-02) |
| GET | `/api/companies/{id}/counterparties` | 200 | **Customer-concentration / threat #2.** (MS-03) |
| GET | `/api/companies/{id}/role-distribution` | 200 | Same. |
| GET | `/api/edgar/frames/{concept}/{period}` | 200 / 404 | **Capex deltas / L5.** (MS-04) |
| GET | `/api/brief/latest` | 200 | **Executive landing.** (MS-05) |
| GET | `/api/brief/weekly/history` | 200 | Same. |
| POST | `/api/brief/run` | OK | Same. |
| GET | `/api/energy-projects/` | 200 | L1 supply view. (MS-11) |
| GET | `/api/press-releases/recent` | 200 | Daily-change strip. (MS-10) |
| GET | `/api/satellite/`, `/api/satellite/sites` | 200 | Per-site phase detection. (MS-16) |
| GET | `/api/sites/{id}`, `/api/sites/{id}/role-summary` | 200 | Per-site detail page. (MS-12) |
| GET | `/api/power/timeseries`, `/api/power/gw-summary` | 200 | Power trend. (MS-13) |
| GET | `/api/coverage/`, `/api/coverage/by-state/{s}`, `/api/coverage/{pillar}` | 200 / 404 | Provenance badges. (MS-14) |
| GET | `/api/events/` | 200 | Used server-side for site enrichment; could power a "what changed" timeline. |
| GET | `/api/earnings/{id}`, `/.../transcript-text` | 200 | Drill-in for forward-guidance view. (MS-06) |
| GET | `/api/permits/datacenter` | 200 | Datacenter-specific permits variant. |
| GET | `/api/sources/` | 200 | Legacy — `/overview` is the consumed one. Can be deprecated. |
| GET | `/api/triangulation/` | 200 (empty) | Root view; unused. |
| GET | `/api/agent/qa/conversations/{id}` | **501** | Stub. (BR-13) |
| POST | `/api/agent/llc-resolve/{id}` | OK | Review-queue handler with no UI. (MS-20) |
| GET | `/api/insights/insights/{id}/citations` | 200 / 404 | Citations are inlined in detail; can be consolidated. |
| GET | `/health` | 200 | k8s liveness — fine as orphan. |
| POST `/api/agent-tools/*` | Internal — used by InsightOrchestrator only, not tabs. Legitimate orphans. |

---

## 6. Test / lint / type-check / build results

### Backend
- **pytest:** 449 collected, **448 passed**, 1 failed, 0 errored, 0 skipped. 15.94 s.
  - FAIL: `tests/test_earnings_adapter.py::test_adapter_run_happy_path_writes_transcript_passages_and_audit` — `assert 0 == 1`. Root cause: `tiktoken` not installed; `earnings_chunker` logs `tiktoken_unavailable` and emits zero passages. **P1 → P0 by impact** because it disables earnings-corpus retrieval (BR-10).
- **DeprecationWarnings:** 3× Pydantic `regex=` → `pattern=` in `routers/companies.py:87,90,95` (BR-14).
- **ruff:** declared in `pyproject.toml [tool.uv]` but not installed in the active env. No lint signal. (BR-20)
- **mypy / pyright:** not configured. No type signal. (BR-21)
- **Import smoke:** `python3 -c "from main import app; print(len(app.routes))"` → `ok 79`. No startup errors.
- **Uvicorn smoke-start** (`SCHEDULER_ENABLED=0`): `/docs` 200, `/openapi.json` 200, `/api/health` 200 (`agents_active: 13`). Clean.

### Frontend
- **vitest:** 9 files, 38 passed, 1 todo, 0 failed. 3.77 s. Clean.
- **`tsc --noEmit`** (root `tsconfig.json`): **0 errors.**
- **`tsc -b`** (build mode walking `tsconfig.app.json`): **8 errors → build fails before `vite build` runs.** Files: `EarningsDetailModal.tsx` (×2), `CompaniesTab.tsx` (×2 — undefined `CompanyRow`), `PowerTab.tsx`, `InsightSidebar.test.tsx`, `CounterpartyPieCard.tsx`. **P0 — BR-01..BR-05.**
- **ESLint:** 33 problems (26 errors, 7 warnings). Predominant rule: `react-hooks/set-state-in-effect` (×13), `react-hooks/exhaustive-deps` (×8). Hotspots: `CitationPill.tsx:91,225`, `SubscribeButton.tsx:62`, `useApi.ts:77`, `useInsightSubscription.ts:47`, `useOpenQuestionsPolling.ts:128`. Likely root cause of the polling storms in `backend.log` (BR-15, BR-24).
- **Production build:** **does not produce a bundle** until BR-01..BR-05 are fixed.

### AI agent stack (separate review by subagent)
- Synthesis prompts (`backend/agents/insights/prompts/*.md`): current, dated-2026-aware, OCI O&T framing enforced (`synthesis_rules.md` lines 55–68), weekly cadence wired (`agentic_synthesis.py:195-209`), anti-repetition wired (`_RECENT_HEADLINE_LOOKBACK_DAYS = 28`).
- v2 cutover (commit `cf028ab`) is complete; v1 tools (`emit_chart`, `get_chart_data`) retained only for chat/triangulation flows, banned in synthesis (`synthesis_rules.md:50`).
- `created_by` discipline correct: `runner.py:524` uses `"scheduler"`; orchestrator passes through router-supplied filter without defaulting.
- TODOs in scope: 2 deferred non-blocking items (`mcp_server.py:622` Phase-4 brief wiring; `parent_resolver.py:9,648` parcel deeds Phase-2). **No critical TODOs.**
- **Verdict:** the synthesis pipeline IS ready for the O&T pivot. The failure modes are in (a) the corpus going in (BR-09/BR-10) and (b) the surfaces coming out (MS-01..MS-06), not in the synthesis itself.

---

## 7. Recommended fix order

Sequenced to (a) stop the bleed, (b) unblock the build, (c) light up the O&T framing, (d) clean up.

### Day 0 — stop the bleed (today)
1. **BR-08 (security).** Take the public Vite dev server down. Move to a reverse proxy with basic-auth or VPN. If a temporary public preview is required, restrict by IP allow-list and put it behind nginx with `Strict-Transport-Security` and a 401 default. Confirm no `.env` was scraped (check `~/.bash_history`, audit any embedded keys).
2. **BR-09 / BR-10.** `pip install tiktoken` in the backend env; rerun `pytest tests/test_earnings_adapter.py` to confirm. For BR-09 add an empty-payload guard: if `transcript == []` and the calendar shows the call has already happened, DO NOT cache → retry next run with backoff. If the call has not happened yet, cache with a short TTL (≤ 24 h).

### Day 1–3 — unblock release
3. **BR-01..BR-05.** Fix the 8 TS errors so `npm run build` produces a bundle:
   - `CompaniesTab.tsx:674,675` — define/import `CompanyRow` type (it was deleted in the 997-line refactor).
   - `CounterpartyPieCard.tsx:221` — drop the `sortValues` prop on `<Pie>` (not in Recharts).
   - `PowerTab.tsx:293` — update the discriminant string (`'archive'` → `'curated_archived'`).
   - Drop unused imports in `EarningsDetailModal.tsx`, `InsightSidebar.test.tsx`.
4. **BR-06.** Decide endpoint policy:
   - If "Tracked Questions" is staying: reimplement `GET /api/insights/open-questions` and restore `test_open_questions_route.py`.
   - If not: delete `useOpenQuestionsPolling.ts`, `TrackedQuestionsSidebar.tsx`, and the `OpenQuestion` type. Do not ship half (MS-15).
5. **BR-07.** Either add `GET /api/insights/health` (cheap), or have `AIInsightsTab` use `GET /api/health` directly.

### Week 1 — wire up the O&T framing
6. **MS-05.** Mount `WeeklyBriefCard.tsx` in `App.tsx` and change the default `TAB_CONFIG` from `datacenters` to a new `briefing` tab.
7. **MS-02.** Confirm `anomaly_detection_nightly` cron actually writes to `anomalies` — if rows are missing, fix the upstream join. Then add an Anomalies tab + a "Threats this week" strip on the new briefing tab.
8. **MS-01.** Either (a) backfill `gpu`/`nics`/`tsmc`/`triangulation` in `oci_share.py` so the existing endpoint is honest, or (b) explicitly remove those tabs from `_TAB_DEFAULTS` and add the missing share-timeseries endpoint. Then surface as a persistent header strip + dedicated "OCI Position" tab.
9. **MS-03.** Unblock CompaniesTab build (item 3), then wire `/api/companies/{id}/counterparties` + `/role-distribution` into the existing (now-broken) `CounterpartyPieCard`. PRD already exists at `docs/prds/counterparties-pies.md`.

### Week 2 — fill the rest
10. **MS-04.** EDGAR-frames capex chart (orphan handler is ready).
11. **MS-06.** Forward-guidance view from earnings (depends on BR-09/BR-10 fix).
12. **MS-07, MS-10, MS-11, MS-13.** Wire press-releases, neo-cloud tracker, energy-projects, power-timeseries tabs from existing orphan endpoints (low cost, high O&T value).
13. **BR-12.** Drop the MOCK label on TriangulationTab (it returns real data).
14. **MS-14.** Add `<CoverageBadge>` to every chart card (coverage endpoint already exists).

### Backlog (cleanup, not gating)
15. **BR-11.** Either remove the four no-data tabs from `oci_share.py` `_TAB_DEFAULTS` or implement them.
16. **BR-13.** Decide: implement `/api/agent/qa/conversations/{id}` or remove the route + UI references.
17. **BR-14.** Pydantic `regex=` → `pattern=`.
18. **BR-15.** Walk through the React-hooks lint errors; the `setState-in-effect` cluster is likely the root cause of polling storms (BR-24). Fixing this will reduce backend load too.
19. **BR-16.** Move `logs/backend.log` to a rotating file handler so operators can tail something fresh; or document where prod is logging.
20. **BR-17.** Do not merge `feat/save-and-history` until BR-01..BR-07 and BR-15 are resolved. The branch is in a half-refactor state.
21. **BR-19.** Document the quarterly cadence for `datasets/` reference files; set a calendar reminder.
22. **BR-20 / BR-21.** Install `ruff` in the backend env; add `mypy` to `pyproject.toml`.
23. **BR-22.** Remove the `MOCK_DATA=1` env hook from `anomalies.py` once a real anomaly feed lands.
24. **MS-15..MS-22.** Sequence per UX_GAPS_AND_FLOW_PROPOSAL.md and the O&T-revised IA.

---

## 8. Appendix — sources

- **Direct repo walk** of `backend/`, `frontend/`, `docs/`, `logs/`, `datasets/`, `backend/data/{cache,raw,aterio_archive}/`.
- **Router-vs-frontend matrix** from a deep crawl of all 23 backend routers and every `fetch(`/`axios`/`apiClient`/`use*` hook under `frontend/src/`.
- **Data-freshness scorecard** from `stat` / `ls -lt` on every cached artifact, cross-referenced with `backend/pipeline/runner.py` `JOB_CONFIG` and the AI Insights weekly cadence memory note.
- **Backend route probes** against a locally-started uvicorn (port 8765, SCHEDULER_ENABLED=0), 36 GET endpoints curl'd, statuses recorded.
- **Tests**: `pytest -q --tb=line` (449 tests, 1 fail). `vitest --run` (38 tests, 0 fail).
- **Lint**: `npx tsc --noEmit`, `npm run lint`, `npm run build`.
- **AI-agent prompt audit** of all `backend/agents/insights/prompts/*.md` and the synthesis / orchestrator / tools modules; cross-referenced against the four user memory notes (`feedback_devteam_claudecode_env`, `reference_llama_stack_openapi`, `feedback_no_claude_coauthor`, `feedback_ai_session_created_by`, `feedback_ai_insights_weekly_cadence`).
- **Git log** of the last 40 commits + the staged-but-uncommitted diff on `feat/save-and-history` (122 files, +9,024 / −58,072).

---

**Report file:** `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/AUDIT_GAPS_AND_BROKEN.md`
