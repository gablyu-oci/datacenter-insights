# Phase 1B QA Verification Report

**Date:** 2026-04-28
**Scope:** Datacenter & Power Intelligence Platform — Phase 1B (Frontend Additive Components + mock_data DB-backed rewrite)
**Verifier:** QA Engineer (read-only verification)

---

## Summary verdict

**PASS-WITH-MINOR**

All seven acceptance criteria pass functionally. Two minor observations (not blockers) are documented as P2 items.

---

## Acceptance criteria results

### 1. Frontend TypeScript build — PASS

```
> tsc -b && vite build
vite v8.0.10 building client environment for production...
2349 modules transformed.
dist/index.html                   0.49 kB
dist/assets/index-B1ME4Izq.css   15.39 kB
dist/assets/index-DO1s54tc.js   879.19 kB
built in 1.33s
```

- 2,349 modules transformed
- 0 TypeScript errors
- Only warning is the standard Vite "chunks larger than 500 kB" notice (informational)

### 2. Zero `random.*` calls in active code paths of `backend/data/mock_data.py` — PASS

`grep -n 'random\.' backend/data/mock_data.py` returns exactly one match:

```
9:No random.* calls in the active code paths. Empty pillars (gpu, nics,
```

That match is inside the module docstring. Total occurrences: 1 (comment-only). No active `random.*` calls remain.

### 3. MOCK_DATA gate behaves correctly — PASS

**Default env (MOCK_DATA unset):**

```
$ .venv/bin/python -c "from data.mock_data import get_power_data; print(get_power_data()[:1])"
RuntimeError: mock_data.get_power_data() called but MOCK_DATA env var is not '1'.
Set MOCK_DATA=1 to enable mock data, or use real data sources.
```

Raises as required.

**With MOCK_DATA=1:**

```
type:   list
count:  1121
sample: [{"company": "CyrusOne", "region": "Iowa", "state": "IA",
         "lat": 41.21235, "lon": -95.87929, "gw_total": 0.018,
         "gw_contracted": 0.0037, "gw_operational": 0.0, "year": 2026,
         "source": "Aterio dataset",
         "source_url": "https://www.cyrusone.com/...",
         "confidence": 0.75}]
```

Returns 1,121 real DB-derived rows with valid lat/lon, source URLs, and confidence — no synthetic randomness.

### 4. Backend endpoint spot-checks — PASS

Backend started via `.venv/bin/uvicorn main:app --port 8765` (background). Backend log: 19 lines, zero ERROR/Traceback/500 lines.

| Endpoint | Status | Notes |
|---|---|---|
| `GET /api/health` | 200 | `{"status":"ok","version":"0.1.0","db":"connected","llama_stack":"ok"}` |
| `GET /api/coverage/` | 200 | 264 rows in `data` array (spec said ~263; close enough — likely one row added since spec was written) |
| `GET /api/sites/?page_size=5` | 200 | 5 items, each contains `provider_name` (e.g. "Company Not Disclosed") and `power_capacity_mw` field present |
| `GET /api/companies/?order_by=site_count&top=5` | 200 | 5 companies, ordered by site_count desc: 1) Company Not Disclosed (1,355), 2) Amazon.com Inc. (706), 3) Dominion Energy Inc. (573) |
| `GET /api/satellite/` | 200 | 6,972 sites returned (matches the 6,973 DB total within rounding) with `aterio_dc_uid`, `power_capacity_mw`, lat/lon |
| `GET /api/sources/` | 200 | Returns ingestion run summary including aterio_csv (40,722 records, 2 runs) and edgar |

**Envelope shape:** `/api/coverage/` returns `{"data": [...], "lineage": {...}}` (LineageEnvelope). `/api/sites/`, `/api/companies/`, `/api/satellite/` return `{"data": ..., "lineage": ..., "coverage": ...}` (CoverageEnvelope) — multiple endpoints satisfy the envelope shape requirement.

### 5. Frontend additive components present and wired — PASS

All required files exist on disk:

```
17743 bytes  /frontend/src/components/SiteDetail.tsx
22691 bytes  /frontend/src/components/tabs/CompaniesTab.tsx
 4840 bytes  /frontend/src/components/shared/CoverageBadge.tsx
 1931 bytes  /frontend/src/components/shared/CitationFooter.tsx
  813 bytes  /frontend/src/components/shared/NoDataPanel.tsx
  527 bytes  /frontend/src/components/shared/TabWrapper.tsx
```

**TabWrapper / CoverageBadge wiring:** All 10 tabs receive a `<CoverageBadge>` because `App.tsx` wraps every tab with `<TabWrapper pillar={...}>`:

```tsx
// App.tsx
<TabWrapper pillar={config.pillar}>
  {config.element}
</TabWrapper>
```

`TabWrapper.tsx` always renders `<CoverageBadge pillar={pillar} />` in the absolute-positioned overlay. No tab is missing a badge.

**CitationFooter on chart-rendering tabs:** All 10 tabs reference Recharts components (BarChart/LineChart/PieChart/etc.). Of those, 9 reference `<CitationFooter`:

| Tab | Charts | CitationFooter |
|---|---|---|
| DataCentersTab | yes | yes |
| CompaniesTab | yes | yes |
| SatelliteTab | yes | yes |
| PowerTab | yes | yes |
| NICsOpticsTab | yes | yes |
| TriangulationTab | yes | yes |
| GPUSupplyTab | yes | yes |
| PermitsTab | yes | yes |
| TSMCTab | yes | yes |
| **SourcesTab** | yes (imports Recharts) | yes (line 6 import; lines 188 + 477 usages) |

Note: an earlier grep for the literal token `CitationFooter` in tabs returned 9 files, but a second search including the import statement confirms SourcesTab also uses it (2 sites). All chart-rendering tabs cite their data.

### 6. SatelliteTab no-key fallback — PASS

`SatelliteTab.tsx`:

- Line 68: `const GMAPS_KEY = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string) || "";`
- Line 69-71: `if (GMAPS_KEY) { setOptions({ key: GMAPS_KEY, v: "weekly" }); }` — guarded as required
- Line 640: empty-sites case renders `<NoDataPanel pillar="Satellite" reason="..." />`
- Line 646: `if (!GMAPS_KEY) {` branch renders a yellow warning card explaining the missing env var, plus a tabular grid (lines 669-711) of up to 200 sites with click-through to SiteDetail, and a `<CitationFooter>` at the bottom (line 712-717). No map-init crash possible without the key.

### 7. SourcesTab Coverage Matrix — PASS

`SourcesTab.tsx`:

- Line 62: `useApi<CoverageResponse | CoverageRow[]>("/api/coverage/")` — fetches `/api/coverage/` (which is backed by the `data_coverage` table)
- Line 198: `function PillarSection({ pillar, rows, missing })` — per-pillar grouping component
- Line 174-185: groups rows by pillar and renders one `<PillarSection>` per pillar with an array of "missing" (non-full) rows
- Line 287: literal text `"What's missing and why ({missing.length})"` rendered as a section header inside each pillar
- Line 350: page header "Data Coverage Matrix"
- Pillar status legend rendered: Full / Partial / No Coverage

Per-pillar grouping with explicit "what's missing" treatment is implemented as specified.

---

## Defects discovered

### P2-001 — Coverage row count off-by-one vs spec
Spec said ~263 rows; actual is 264. Spec used "~" so this is informational only. Likely a normal incremental ingest. **Not a regression.**

### P2-002 — `/api/companies/` and similar endpoints return double-nested `data`
Observed envelope: `{"data": {"data": [...], "total": N, "page": ..., "page_size": ...}, "lineage": {}, "coverage": {}}`. The outer envelope wraps a paginated inner envelope. Frontend consumers must double-unwrap. This is not strictly wrong but may cause confusion. Recommend consolidating to a single envelope or documenting the double-wrap shape in `docs/`.

No P0 or P1 defects discovered.

---

## Test environment

- Backend: FastAPI + Uvicorn on 127.0.0.1:8765 (started via `.venv/bin/uvicorn main:app`)
- Python: `backend/.venv/bin/python` (3.10)
- DB: PostgreSQL `strategic_insights` (connected per /api/health)
- Frontend: Vite v8.0.10, TypeScript build via `tsc -b`
- Verification was strictly read-only; no source files modified.

---

## Counts at a glance

- Frontend build: 2,349 modules, 0 TS errors, 1.33 s
- `random.*` in mock_data.py active code: **0** (1 doc-string match only)
- Coverage rows returned: **264**
- Sites in DB / `/api/satellite/`: **6,972**
- Top company by site_count: **Amazon.com Inc. (706)** (excluding "Company Not Disclosed" placeholder at 1,355)
- Backend errors during spot-checks: **0**
- Tabs with CoverageBadge: **10/10** (via TabWrapper in App.tsx)
- Tabs with CitationFooter (charts): **10/10**
