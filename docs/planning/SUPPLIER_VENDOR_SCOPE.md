**Author:** Orchestrator (research run, agents: researcher + architect) | **Date:** 2026-04-30 | **Status:** Draft v1.0

## Scope

Curate the vendor universe behind the **Supplier Insights** dropdown (3 tabs: GPU Supply / NICs & Optics / TSMC) before we run a vendor-mode SEC extractor and rewire the per-tab routers. Today only 5 vendors are in `VENDOR_FILERS` (NVIDIA, Broadcom, Coherent, Lumentum, TSMC); user has already added AMD. This doc proposes a curated list of **3–7 vendors per tab**, restricted to public SEC filers (10-K / 10-Q / 20-F / 6-K), free data only.

The companion **Architectural Context** appendix at the end of this doc enumerates the code surfaces that will be touched when the list lands (no code changes in this run).

Constraints applied:
- Public SEC filers only — private companies (Cerebras, Groq, SambaNova, Tenstorrent, Rebellions, Furiosa) are out.
- Foreign filers OK if they actually file with EDGAR (20-F or 6-K). Korea-only / Taiwan-only / China-only listings are out.
- Free data only.
- Max 7 per tab — curation, not exhaustiveness.

---

## Category 1 — GPU Supply (datacenter AI accelerator silicon)

Anchor signal: **datacenter AI accelerator segment revenue, trended quarterly 2024–2026.**

| Vendor | CIK | Form | Relevant segment / line item | What the disclosure looks like (1-line example from a recent filing) | Confidence |
|---|---|---|---|---|---|
| **NVIDIA** *(in scope)* | 0001045810 | 10-K | "Compute & Networking" → Data Center | Already curated; Data Center revenue dominates 10-K segment table. | High |
| **AMD** *(user added)* | 0000002488 | 10-K | "Data Center" reportable segment | Data Center segment revenue disclosed quarterly; Instinct MI300/MI350 ramp called out in MD&A. | High |
| **Intel** | 0000050863 | 10-K / 10-Q | "Data Center and AI" (DCAI) reportable segment | "DCAI revenue of $5.1B in Q1 2026 grew 22% year-over-year." (Q1'26 release, Intel IR) | High |
| **Alphabet** *(TPU — press-tracked, not EDGAR-extractable)* | 0001652044 | 10-K | Google Cloud (TPU not separately disclosed) | TPU revenue rolled into Google Cloud segment; flag in UI as "non-EDGAR signal — track via press." | Low |
| **Amazon** *(Trainium / Inferentia — press-tracked)* | 0001018724 | 10-K | AWS (custom silicon not disclosed) | No segment line item; track Trainium2 deployments via press releases. | Low |
| **Microsoft** *(Maia / Cobalt — press-tracked)* | 0000789019 | 10-K | Mentioned qualitatively in 10-K risk/strategy sections; no segment break-out | Track via press. | Low |
| *(open slot — Cerebras post-IPO)* | — | S-1 filed | n/a until effective | Promote when IPO closes. | n/a |

**Who's missing and why:** Cerebras (S-1 filed but not yet effective — promote on IPO), Groq, SambaNova, Tenstorrent, Rebellions, Furiosa — all private, excluded per scope. Hyperscaler in-house silicon (TPU / Trainium / Maia) is intentionally listed at **Low** confidence: the 10-K does not break it out, so the EDGAR extractor will return zero meaningful rows. Recommend surfacing these three as "press-only" sources alongside the EDGAR-extracted vendors, not relying on the extractor.

CIK verification:
- Intel: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000050863>
- Intel 10-K (FY2024): <https://www.sec.gov/Archives/edgar/data/50863/000005086325000009/intc-20241228.htm>
- Alphabet: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001652044>
- Amazon: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001018724>
- Microsoft: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000789019>

---

## Category 2 — NICs & Optics (networking silicon + optical transceivers feeding AI clusters)

Anchor signal: **AI / data-center networking revenue, optical transceiver revenue (where disclosed separately).**

| Vendor | CIK | Form | Relevant segment / line item | What the disclosure looks like (1-line example) | Confidence |
|---|---|---|---|---|---|
| **Broadcom** *(in scope)* | 0001730168 | 10-K | "Semiconductor Solutions" → Networking | Already curated; AI networking ASICs + Tomahawk/Jericho switch silicon called out in MD&A. | High |
| **Marvell Technology** | 0001835632 | 10-K | "Data Center" end market | "Data center revenue surged to $1.4B in Q4 FY25, +78% YoY; AI accounts for over half of data center revenue." | High |
| **Coherent** *(in scope)* | 0000820318 | 10-K | "Networking" / Datacom transceivers | Already curated. | High |
| **Lumentum** *(in scope)* | 0001633978 | 10-K | "Cloud & Networking" | Already curated; EML lasers for 800G/1.6T. | High |
| **Credo Technology** | 0001807794 | 10-K *(fiscal year ends April)* | Product family revenue (AECs, Optical, SerDes) | "Q2 FY26 revenue $268.0M, +272% YoY; AECs to hyperscale data center customers drive growth; top 3 customers = 88% of revenue." | High |
| **Astera Labs** | 0001736297 | 10-K | Single product line (PCIe/CXL retimers, Scorpio fabric) | "FY2025 revenue $852.5M, +115% YoY; one customer >70% of revenue." | High |
| **Fabrinet** | 0001408710 | 10-K | "Optical communications" — datacom vs telecom split | "Datacom revenue grew >120% for the year; 800G products for AI are biggest contributor; Nvidia ~35% of FY revenue." (FY25 10-K) | High |
| *(consider as watchlist)* Arista Networks | 0001596532 | 10-K | Product revenue (no AI line item) | "AI back-end networking goals exceeded" — narrative only; recommend press watchlist not EDGAR extraction. | Medium |
| *(consider as watchlist)* Cisco | 0000858877 | 10-K | "AI infrastructure orders" (CFO-disclosed metric, not GAAP) | "$1.3B AI infrastructure orders in Q1 FY26; ~$3B AI infra revenue expected FY26" — earnings-call commentary, not 10-K line. | Medium |

**Who's missing and why:** Innolight, Eoptolink, Accelink, HG Genuine — Chinese-listed only, excluded per scope. MaxLinear, Semtech — too small / not primarily AI-driven. Ciena (CIEN, CIK 0000936395) — has DCI exposure and recently acquired Nubis (Oct 2025), but no AI line-item break-out; treat as watchlist. **Arista and Cisco are intentionally NOT in the curated 7**: Arista has no segment break-out for AI, and Cisco's AI-orders figures are CFO commentary, not GAAP line items — both fail the "extractor will get a clean number" test. They belong in a press-tracked watchlist alongside the hyperscaler silicon row.

CIK verification:
- Marvell: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001835632>
- Astera Labs S-1/A: <https://www.sec.gov/Archives/edgar/data/1736297/000119312524062817/d285484ds1a.htm>
- Astera Labs Q4'24 release: <https://www.sec.gov/Archives/edgar/data/1736297/000173629725000001/q424exhibit991.htm>
- Credo S-1: <https://www.sec.gov/Archives/edgar/data/1807794/000162828022000095/credotechnologygroups-1.htm>
- Fabrinet 10-K FY25: <https://www.sec.gov/Archives/edgar/data/1408710/000140871025000039/fn-20250627.htm>
- Arista Q3 2025 release: <https://www.sec.gov/Archives/edgar/data/1596532/000159653225000284/ex991q325-earningsrelease.htm>
- Cisco: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000858877>

---

## Category 3 — Foundry & Advanced Packaging

Anchor signal: **leading-edge wafer (3nm/5nm) capacity AND CoWoS-class advanced packaging utilization** — these jointly gate Nvidia/AMD shipments.

| Vendor | CIK | Form | Relevant segment / line item | What the disclosure looks like (1-line example) | Confidence |
|---|---|---|---|---|---|
| **TSMC** *(in scope)* | 0001046179 | 20-F (+ 6-K monthlies) | "High Performance Computing" (HPC) platform | Already curated; HPC platform revenue is the prime leading-edge / CoWoS proxy. | High |
| **Intel** *(Foundry segment)* | 0000050863 | 10-K / 10-Q | "Intel Foundry" reportable segment (since Q1'24) | "Intel Foundry revenue $4.5B in Q4 2025; external foundry revenue $222M in the quarter." | High |
| **GlobalFoundries** | 0001709048 | 20-F | End-market mix incl. "Communications & Datacenter" | FY2024 20-F filed March 2025; quarterlies $1.585B → $1.830B; Communications & Datacenter end-market broken out. | High |
| **Amkor Technology** | 0001047127 | 10-K | "Advanced Products" vs "Mainstream Products" | "FY2025 net sales $6,708M; Advanced Products $5,556M (82.8%); 2.5D/HDFO expected to nearly triple in 2026." | High |
| **ASE Technology Holding** | 0001122411 | 20-F (+ 6-K) | "ATM" → LEAP (Leading-Edge Advanced Packaging) sub-line | "LEAP services rose to US$1.6B (13% of revenue) in 2025, from $0.6B prior." | High |
| **ASML** | 0000937966 | 20-F (+ 6-K) | Net sales by end-market (Logic vs Memory) | "Logic net sales driven by leading-edge foundry growth in support of strong AI demand; Memory momentum from HBM and DDR5." | High |
| **Applied Materials** | 0000006951 | 10-K | "Semiconductor Systems" — advanced packaging sub-narrative | "Advanced packaging business expected to double to $3B+ over next few years; HBM and 2.5D/hybrid bonding called out." (Q4 FY25) | High |
| *(equipment watchlist)* Lam Research | 0000707549 | 10-K | "Systems" with HBM/advanced packaging narrative | "Advanced packaging business expected to grow >40% in 2026; HBM4/HBM4E electroplating + TSV etch leadership." | Medium |
| *(equipment watchlist)* KLA Corp | 0000319201 | 10-K | "Semiconductor Process Control" (AI/advanced node language) | "FY2025 revenues $12.16B; key enabler of AI ecosystem across foundry/logic, memory, advanced packaging." | Medium |

**Who's missing and why:**
- **Samsung Electronics** has a CIK (0000879316) but does **not** file 10-K or 20-F on EDGAR — only 144A/exempt-issuer filings exist; ADRs trade OTC (SSNLF). **Cannot be tracked via EDGAR.** Track via Samsung IR / Korean DART, flag in UI as "non-EDGAR".
- **SK Hynix** — same issue (Korean-listed only). Track via DART/IR. Critical for HBM signal but unreachable from EDGAR.
- **UMC** (CIK 0001033767) is a 20-F filer but trailing-edge mix; not AI-relevant.
- **SMIC, Hua Hong** — Chinese-listed, excluded.
- **Tower Semiconductor** (CIK 0000928876) — 20-F filer but specialty-analog focus, not AI.
- **Powertech, KYEC, SPIL** — Taiwan-listed only; no SEC filings.
- **BE Semiconductor (Besi)** — hybrid-bonder leader, EU-listed only; no 20-F.

CIK verification:
- Intel Foundry segment (in 10-K): <https://www.sec.gov/Archives/edgar/data/50863/000005086325000009/intc-20241228.htm>
- GlobalFoundries: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001709048>
- Amkor 10-K FY24: <https://www.sec.gov/Archives/edgar/data/1047127/000104712724000019/amkr-20231231.htm>
- ASE 20-F FY24: <https://www.sec.gov/Archives/edgar/data/1122411/000119312524085380/d434934d20f.htm>
- ASML: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000937966>
- Applied Materials: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000006951>
- Lam Research: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000707549>
- KLA: <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000319201>
- Samsung Electronics (no 20-F): <https://www.sec.gov/edgar/browse/?CIK=879316>

---

## RECOMMENDED FINAL LIST per category (priority order)

### Category 1 — GPU Supply (3 EDGAR-extracted + 3 press-tracked)
1. **NVIDIA** — anchor; Data Center segment is the canonical AI demand signal.
2. **AMD** — Instinct MI300/MI350 ramp directly competes; Data Center segment cleanly disclosed.
3. **Intel** — DCAI segment now reports separately; Gaudi 3 + Falcon Shores trajectory is a competitive read for OCI.
4. **Alphabet (TPU)** — press-only; flag as "non-EDGAR signal."
5. **Amazon (Trainium / Inferentia)** — press-only.
6. **Microsoft (Maia)** — press-only.
7. *(reserved)* — Cerebras post-IPO.

### Category 2 — NICs & Optics (final 7, all EDGAR-extractable)
1. **Broadcom** — anchor; AI networking ASICs + Tomahawk/Jericho.
2. **Marvell Technology** — custom silicon for hyperscalers + Inphi optical DSPs; clean Data Center end-market disclosure.
3. **Coherent** — datacom transceivers, vertical optics.
4. **Lumentum** — datacom transceivers, EML lasers for 800G/1.6T.
5. **Credo Technology** — AECs are pure AI-cluster signal; Q-over-Q growth tracks hyperscaler order patterns.
6. **Astera Labs** — pure-play AI rack-scale connectivity (PCIe/CXL retimers, Scorpio fabric).
7. **Fabrinet** — optical contract manufacturer; Nvidia exposure (~35%) is a leading indicator for Nvidia datacom shipments.

(Arista and Cisco intentionally **not** in curated 7 — see Category 2 narrative above; treat as press-tracked watchlist.)

### Category 3 — Foundry & Packaging (final 7)
1. **TSMC** — anchor; HPC platform revenue.
2. **Intel** *(Foundry segment)* — only Western leading-edge alternative; 18A ramp + external customer wins.
3. **GlobalFoundries** — trailing-edge but Communications & Datacenter end-market disclosed.
4. **Amkor Technology** — US-listed OSAT; Advanced Products line cleanly tracks 2.5D/HDFO ramp.
5. **ASE Technology Holding** — Taiwan OSAT leader; LEAP sub-line is a clean AI packaging disclosure.
6. **ASML** — gating equipment for HBM and leading-edge logic; Logic/Memory split is informative.
7. **Applied Materials** — HBM and advanced packaging called out in MD&A.

(Lam Research and KLA listed as **Equipment watchlist** — same signal as AMAT, optional add if a sub-panel is built.)

### Tab-rename recommendation: **Rename "TSMC" → "Foundry & Packaging"**

The signal we actually care about (leading-edge wafer capacity AND CoWoS-class advanced packaging) is disclosed across at least four distinct companies — TSMC, Intel Foundry, Amkor, ASE — none of whom alone tells the full story. CoWoS is the gating constraint on Nvidia/AMD shipments, and TSMC's CoWoS capacity is supplemented by Amkor and ASE's competing 2.5D/HDFO offerings. Equipment makers (ASML, AMAT) are leading indicators 6–12 months ahead of foundry revenue. Keeping the tab named "TSMC" undersells the analytical scope.

**Recommended tab structure:**
- **Foundry sub-section:** TSMC, Intel Foundry, GlobalFoundries
- **OSAT / Packaging sub-section:** Amkor, ASE
- **Equipment leading-indicator panel:** ASML, Applied Materials (optional: Lam, KLA)

Note from the Architectural Context (below): the UI label for tab 3 is **already** "Wafer Production & Supply" (not "TSMC") — but the tab id, route slug (`tsmc`), response type, and component name still say `tsmc`. The label-only rename is partly done; the slug rename is a separate, larger touch list.

---

## Warnings / Gotchas (for the implementer next sprint)

1. **Astera Labs customer concentration** (>70% from one customer in 2025) means quarterly volatility is huge — explain in any UI rendering of their growth chart, or it will look misleading.
2. **Credo's fiscal year ends in April** — their "FY2026 Q2" is roughly calendar Q3 2025. Normalize all charts to calendar quarters before comparing across vendors.
3. **Intel's segment definition changed in Q1 2025** (NEX folded into CCG and DCAI). Pre-2025 DCAI numbers in raw 10-Q tables are not directly comparable to post-Q1'25 numbers. Pull the restated retrospective table when seeding history.
4. **Intel Foundry external revenue is tiny** ($222M in Q4'25 of $4.5B total Foundry); most is intersegment. Don't compare gross "Intel Foundry" revenue head-to-head with TSMC; only the *external* line is apples-to-apples, and even that includes Altera deconsolidation noise.
5. **Samsung and SK Hynix are unreachable via EDGAR** (no 20-F). Add a UI affordance for "non-EDGAR vendors" so users don't think the data is missing due to a bug.
6. **Cisco's $1.3B–$3B AI infra figures are forward-looking guidance from earnings calls**, not 10-K/10-Q line items. Distinguish "MD&A line item" from "earnings-call commentary" or you'll mis-tag confidence.
7. **Fabrinet's Nvidia concentration disclosure** moves quarter-to-quarter; treat it as a relationship signal, not a stable revenue line.
8. **ASML files 20-F annually but issues quarterly results via 6-K** — make sure the EDGAR extractor handles 6-K, not just 10-Q/20-F, to capture quarterly cadence. Same for TSMC monthly revenue 6-Ks.
9. **Arista does not break out AI** in any standard segment line item — labeling them "High" confidence would be wrong; keep at Medium and lean on management commentary, or treat as press watchlist.
10. **Cerebras IPO watch** — S-1 publicly filed; promote to Category 1 when effective.

---

## Architectural Context (from System Architect, 2026-04-30)

This appendix records the code surfaces that will be touched when this curated list is implemented next sprint. **Read-only research; nothing has been changed.**

### Current `VENDOR_FILERS` shape

- **File:** `backend/agents/edgar_agent.py` (lines 59–65)
- **Shape:** flat `dict[str, str]` — display name → zero-padded SEC CIK
- **Today:**
  ```python
  VENDOR_FILERS = {
      "Broadcom":  "0001730168",
      "Coherent":  "0001140536",
      "Lumentum":  "0001633978",
      "NVIDIA":    "0001045810",
      "TSMC":      "0001046179",
  }
  ```
- **Fields per entry today:** `display_name` (key) and `cik` (value). No segment tag, no tab-category, no form-type, no notes, no power-relevance flag. Adjacent dicts (`ENERGY_COMPANIES`, `HYPERSCALERS`) follow the same shape; `None` is the convention for "private, no EDGAR" (see the `X-Energy` line).
- The three dicts merge into `TRACKED_FILERS = {**ENERGY_COMPANIES, **HYPERSCALERS, **VENDOR_FILERS}` (line 69).

### Downstream consumers

| Layer | Path | Behavior |
|---|---|---|
| 8-K fetcher | `backend/agents/edgar_agent.py::fetch_real_8k_deals_async` | Iterates `ENERGY_COMPANIES + HYPERSCALERS` only — **does NOT iterate `VENDOR_FILERS`** for 8-Ks (line 264). |
| Quarterly fetcher (10-K/10-Q) | `backend/agents/edgar_agent.py::fetch_real_quarterly_filings_async` | Iterates unified `TRACKED_FILERS` (line 566). `PER_FILER_CAP = 6`. Vendors appear only via this path. |
| LLM extractor | `backend/agents/edgar_extractor.py::run_llm_extraction_quarterly` | Power-only `is_power_related` gate. Will **reject most NIC/optics/foundry chip-supply disclosures** because the prompt explicitly enumerates "chip revenue or capex announcements" as `is_power_related = false`. Primary reason real-data NIC/Optics tab is empty today. |
| Storage | table `edgar_extractions` | Columns include `cik`, `accession_number`, `form_type`, `filing_date`, `edgar_url`, `capacity_mw`, `energy_source`, `buyer_raw`, `seller_raw`, `excerpt`, `parser_version`, `confidence`. **No `vendor_segment` / `tab_category` column.** |
| GPU router | `backend/routers/gpu.py` | Hard-codes `NVIDIA_CIK = "0001045810"` (line 26) and queries `EdgarExtraction.cik == NVIDIA_CIK`. |
| NICs/Optics + TSMC router | `backend/routers/supply_chain.py` | Hard-codes `BROADCOM_CIK / COHERENT_CIK / LUMENTUM_CIK / TSMC_CIK` (lines 28–31), partition sets `NIC_VENDORS = {BROADCOM_CIK}` and `OPTICS_VENDORS = {COHERENT_CIK, LUMENTUM_CIK}` (39–40), `VENDOR_CIK_TO_NAME` reverse map (33–37). TSMC is its own handler `_tsmc_response()`. |
| Frontend tabs | `frontend/src/components/tabs/{GPUSupplyTab,NICsOpticsTab,TSMCTab}.tsx` | Each calls a single endpoint via `useApi(...)`. Hard-coded KPI cards by vendor concept ("NVIDIA AI Revenue", "InfiniBand", "800G Optics", "3nm Wafer Starts"). |

### Tab → category mapping (today)

| Tab label (UI) | Frontend constant id | Backend endpoint(s) | Vendors today (CIKs) |
|---|---|---|---|
| GPU Supply | `gpu` | `GET /api/gpu/supply` | NVIDIA (0001045810) |
| NICs & Optics Supply | `nics` | `GET /api/nics` (legacy) and `GET /api/supply-chain/nics` | Broadcom (0001730168), Coherent (0001140536), Lumentum (0001633978) |
| Wafer Production & Supply | `tsmc` | `GET /api/tsmc` (legacy) and `GET /api/supply-chain/tsmc` | TSMC (0001046179) |

Dropdown lives in `frontend/src/components/layout/TabNav.tsx` (lines 12–16). Active-tab → component mapping in `frontend/src/App.tsx` `TAB_CONFIG` (lines 16–26). Both **hard-coded** — no server-driven config.

### Real vs mock data gating

- **Single env var:** `MOCK_DATA` (`backend/.env.example` line 8). Default `0` (real).
- **Per-router boolean:** each router top-of-file recomputes `MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"`.
- **Mock data source:** `backend/data/mock_data.py` exposes `get_gpu_data() / get_nics_optics_data() / get_tsmc_data()`.
- **Frontend "MOCK / LIVE" badge:** separate hard-coded `real` boolean per tab in `TabNav.tsx`. Today all three supplier tabs are flagged `real: false` even though routers serve real EDGAR data when `MOCK_DATA=0`. **The badge currently lies about supplier tabs** — fix when expansion lands.

### Per-vendor metadata fields the new `VENDOR_FILERS` entries MUST provide

To avoid another round of hard-coded CIK constants, each new entry should carry at minimum:

| Field | Why |
|---|---|
| `display_name` | Used as `company` in API response and FE cards. |
| `cik` (zero-padded 10-digit, or `None`) | Lookup key against `edgar_extractions.cik`; `None` already used for private (X-Energy). |
| `tab` (`gpu` / `nics_optics` / `foundry_packaging`) | Drives router partitioning. Today this lives in `NIC_VENDORS` set; needs to become data. |
| `segment` / sub-bucket | NICs vs optics share a tab; foundry vs packaging will share a tab post-rename. |
| `form_types` (default `("10-K", "10-Q")`) | TSMC files **20-F**; ASML, ASE, GlobalFoundries also need 20-F + 6-K. The current quarterly fetcher's `_QUARTERLY_FORMS = ("10-K", "10-Q")` (line 412) silently produces 0 rows for FPIs — already noted as known-gap in `supply_chain.py:228–233`. |
| `is_foreign_private_issuer` (bool) | Implied by `form_types` but explicit makes review easier. |
| `relevance_keywords` (optional) | Power-centric 8-K pre-filter (line 201–205) under-selects for chip / packaging / foundry. Either add per-vendor keyword lists or add a vendor-supply mode to the LLM gate. |
| `notes` | Free-text rendered in `states_excluded_with_reason` block when no rows materialize. |

A reasonable canonical shape (implementer's call):

```python
@dataclass(frozen=True)
class VendorFiler:
    display_name: str
    cik: str | None
    tab: Literal["gpu", "nics_optics", "foundry_packaging"]
    segment: str  # "gpu", "nic", "optics", "foundry", "packaging", "equipment"
    form_types: tuple[str, ...] = ("10-K", "10-Q")
    is_fpi: bool = False
    keywords: tuple[str, ...] = ()
    notes: str = ""
```

### Risks / refactors to flag (NOT to fix in expansion)

1. **8-K fetcher skips `VENDOR_FILERS`** — line 264. Vendor 8-Ks are never fetched. Out of scope but worth flagging.
2. **Power-only LLM gate** in `edgar_extractor.py` `SYSTEM_PREAMBLE` will reject most vendor disclosures. The classifier or gate needs a vendor-supply mode (or a parallel `vendor_supply_v1` parser_version writing to its own column/table). **This is the single biggest blocker** — adding 15 more vendors won't help until the classifier is vendor-supply-aware.
3. **20-F / 6-K support** — TSMC, ASML, ASE, GlobalFoundries are FPIs. Quarterly fetcher's form filter must accept 20-F + 6-K.
4. **`MOCK / LIVE` badge mismatch** — fix when expanding.
5. **Per-filer cap & cadence** — `PER_FILER_CAP = 6` × per-filer 0.12s sleep × multiple chunks may push quarterly fetch past sane background-task durations at 15–20 vendors. Estimate before scaling.
6. **Cache key collisions** — submissions cache is per-CIK (safe), but aggregate `real_quarterly_<since>.json` is keyed by `since` only. Stale until 12h TTL expires when membership changes mid-window. Document cache-bust expectation.
7. **`VENDOR_CIK_TO_NAME` reverse map** — derive from registry; don't hand-maintain.
8. **Hyperscaler/vendor overlap** — Apple appears in `PHASE2_RESEARCH.md` press-release list. If vendor list adds Apple-as-foundry-customer, the `**` merge into `TRACKED_FILERS` will silently dedupe by name.

### Tab rename ("TSMC" → "Foundry & Packaging") — surfaces touched

Label-only rename touches just `TabNav.tsx:15` (`label`). To rename the slug/code identifier:

- `frontend/src/components/layout/TabNav.tsx` — `SUPPLIER_TABS` id.
- `frontend/src/App.tsx` — `TAB_CONFIG` key (line 21).
- `frontend/src/components/tabs/TSMCTab.tsx` — file rename + default export.
- `frontend/src/types/index.ts` — `TSMCResponse / TSMCCapacity / TSMCPackaging` interface names.
- `backend/routers/supply_chain.py` — handler `_tsmc_response` and routes `/api/supply-chain/tsmc` and `/api/tsmc` (legacy alias used by `TSMCTab.tsx`).
- `backend/data/mock_data.py` — `get_tsmc_data()`.

**Cleanest path:** keep `tsmc` slug as backward-compat alias and add `/api/supply-chain/foundry-packaging` mounted on the same handler — mirror the legacy-vs-new dual-mount pattern at `supply_chain.py:44–45,257–265`. Don't break existing URLs in the expansion.

---

## Sources

EDGAR / IR primary:
- Intel EDGAR landing — <https://www.sec.gov/edgar/browse/?CIK=0000050863>
- Intel 10-K (FY2024) — <https://www.sec.gov/Archives/edgar/data/50863/000005086325000009/intc-20241228.htm>
- Intel operating segments — <https://www.sec.gov/Archives/edgar/data/50863/000005086325000009/R12.htm>
- Marvell — <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001835632>
- Astera Labs S-1/A — <https://www.sec.gov/Archives/edgar/data/1736297/000119312524062817/d285484ds1a.htm>
- Astera Labs Q4'24 release — <https://www.sec.gov/Archives/edgar/data/1736297/000173629725000001/q424exhibit991.htm>
- Credo S-1 — <https://www.sec.gov/Archives/edgar/data/1807794/000162828022000095/credotechnologygroups-1.htm>
- Fabrinet 10-K FY2025 — <https://www.sec.gov/Archives/edgar/data/1408710/000140871025000039/fn-20250627.htm>
- Arista Q3 2025 release — <https://www.sec.gov/Archives/edgar/data/1596532/000159653225000284/ex991q325-earningsrelease.htm>
- GlobalFoundries — <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001709048>
- Amkor 10-K (FY2023) — <https://www.sec.gov/Archives/edgar/data/1047127/000104712724000019/amkr-20231231.htm>
- ASE Technology 20-F — <https://www.sec.gov/Archives/edgar/data/1122411/000119312524085380/d434934d20f.htm>
- ASE 6-K — <https://www.sec.gov/Archives/edgar/data/1122411/000095010325013870/dp236570_6k.htm>
- ASML 2025 6-K — <https://www.sec.gov/Archives/edgar/data/937966/000162828026003701/pressreleasefinancialresul.htm>
- Samsung Electronics EDGAR landing (no 20-F) — <https://www.sec.gov/edgar/browse/?CIK=879316>
- KLA — <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000319201>
- Lam Research — <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000707549>
- Applied Materials — <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000006951>
- Cisco — <https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000858877>

Repository conventions referenced:
- `docs/planning/PHASE2_RESEARCH.md` — section / table / "Sources" formatting precedent.
- `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md` — header / status / table conventions.
- `docs/planning/03-PIPELINE-ARCHITECTURE.md` — Author / Date / Status header line.
