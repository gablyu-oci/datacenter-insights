# Datacenter & Power Intelligence Platform
## AI Agent Requirements Specification

> **Note:** This document is superseded by the PRD (`PRD.md`) and the `docs/planning/` structure for detailed requirements. The content below is retained as legacy reference but the PRD and `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md` are authoritative.

---

## 1. System Overview

The system is an **AI-driven intelligence platform** (not a static digest) designed to provide **actionable insights for OCI strategy** by aggregating, analyzing, and triangulating:

- Datacenter power contracting & geographic expansion  
- GPU supply chain & deployment signals  
- Cross-layer infrastructure constraints (power vs compute vs buildout)

The platform must support continuous ingestion, normalization, analysis, and visualization of multi-source data.

---

## 2. Core Intelligence Pillars

### 2.1 Power & Datacenter Expansion Intelligence

#### Functional Requirements

AI agents must:

- Extract and normalize:
  - Power contracts (GW scale)
  - Company attribution (Microsoft, AWS, GCP, Meta, OCI — OCI is a full participant in every pillar)
  - Geographic metadata (country, state, county, site-level)
- Aggregate side-by-side competitive views of power capacity
- Track temporal changes in power procurement

#### Data Sources

- SEC EDGAR filings  
- Utility agreements (public)  
- Datacenter aggregators  
- Permit data sources (county records, APIs)

#### Derived Insights

- Power capacity by company and geography  
- Competitive positioning vs hyperscalers  
- Identification of constrained regions  

#### Agent Responsibilities

- Filing Parser Agent → Extract power-related disclosures  
- Geo Mapping Agent → Normalize location data  
- Aggregation Agent → Compute GW totals and trends  

---

### 2.2 GPU Supply Chain Intelligence

#### Functional Requirements

AI agents must:

- Extract:
  - GPU shipments (e.g., NVIDIA)
  - Revenue-to-unit estimates
  - Inventory vs deployed GPUs
- Track upstream constraints:
  - TSMC manufacturing & packaging capacity
- Track deployment proxies:
  - NIC shipments
  - Optical transceivers

#### Data Sources

- Earnings reports & transcripts  
- Financial filings  
- Industry analysis sources  

#### Derived Insights

- Estimated GPUs shipped vs deployed  
- Inventory gap (shipped vs active)  
- Deployment validation via networking/optics signals  

#### Agent Responsibilities

- Earnings Parsing Agent → Extract structured metrics  
- Inference Agent → Convert revenue → unit estimates  
- Supply Chain Correlation Agent → Link GPUs, NICs, optics, TSMC  

---

## 3. Cross-Pillar Intelligence: Triangulation Engine

### Objective

Determine whether power availability matches compute deployment capacity.

### Multi-Layer Model

| Layer | Description |
|------|------------|
| Layer 1 | Contracted power (GW) |
| Layer 2 | Estimated deployed GPUs (power draw × utilization) |
| Layer 3 | NICs & optics (deployment validation) |
| Layer 4 | County permit data (construction ground truth) |

### Functional Requirements

AI agents must:

- Compute:
  - Power required for deployed GPUs  
  - Gap between contracted power and compute demand  
- Identify:
  - Overbuild (excess GPUs vs power)  
  - Underutilization (unused power)  
- Provide explainable outputs linked to sources  

### Agent Responsibilities

- Triangulation Model Agent → Multi-layer modeling  
- Validation Agent → Cross-check signals  
- Explainability Agent → Source traceability  

---

## 4. Data Ingestion & Processing Architecture

### 4.1 Ingestion Pipelines

#### Power Pillar
- SEC EDGAR ingestion
- Permit data ingestion (weekly, county-level)
- External APIs
- Aterio datacenter inventory CSV (73 cols, primary site seed — see 00-DECISIONS-AND-CONSTRAINTS.md §3)

#### GPU Pillar
- Earnings transcript ingestion
- Financial filings parsing
- Industry dataset ingestion
- Financial Modeling Prep transcripts ($29-99/mo) + LLM extraction

#### Satellite Data
- Sentinel-2 via Google Earth Engine (free, 10m, Phase 1). Planet Labs / Maxar deferred.
- Cost and cadence optimization

---

### 4.2 Processing Requirements

AI agents must:

- Normalize heterogeneous datasets  
- Perform entity resolution (company, site, geography)  
- Maintain time-series datasets  
- Detect anomalies and changes  

---

### 4.3 Update Frequency

- Permits: Weekly  
- Filings/Earnings: Event-driven  
- Satellite imagery: Periodic  

---

## 5. Dashboard & UX Requirements

### 5.1 Multi-Tab Interface

Required tabs:

1. Power
2. Satellite View
3. GPU Supply
4. NICs & Optics
5. TSMC
6. Permits
7. Triangulation
8. Sources
9. Energy Supply (new — sourced from Aterio Energy Project Inventory, §3.4)
10. Events Timeline (new — sourced from Aterio Data Dictionary Events sheet, §3.3)

---

### 5.2 Interaction Requirements

- Every data point must link to its original source  
- Support:
  - Drill-down analysis  
  - Cross-tab filtering  
  - Time-based comparisons  

---

### 5.3 Visualization Requirements

#### Power Tab
- Geographic heatmaps (GW capacity)  
- Competitive comparison charts  

#### Satellite Tab
- Datacenter site visualization  
- Change detection over time  

#### Triangulation Tab
- Gap analysis (power vs compute)  

---

## 6. Satellite Intelligence Requirements

AI agents must:

- Map datacenter sites to coordinates  
- Retrieve satellite imagery over time  
- Detect:
  - Construction starts  
  - Expansion progress  
- Link imagery to:
  - Permits  
  - Power contracts  

---

## 7. Data Traceability & Source Integrity

### Requirements

- Every metric must:
  - Be traceable to primary source  
  - Include citation metadata  
- Maintain:
  - Source confidence levels  
  - Versioned data lineage  

---

## 8. Initial Prototype Scope (Phase 1)

### Must Deliver

- Power Map:
  - At least 3 companies (MSFT, AWS, GCP)  
  - County permit overlay  
- Basic triangulation model  
- Earnings parsing pipeline (NVIDIA, TSMC, hyperscalers)  

---

## 9. Resolved Decisions

All design questions have been resolved. See `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md` §1 for the authoritative list.

| # | Decision | Resolution |
|---|---|---|
| 1 | **Postgres hosting** | Self-hosted on this OCI VM. No managed service. |
| 2 | **SEC EDGAR API usage** | Leverage official `data.sec.gov` REST APIs (no auth, free, JSON). |
| 3 | **OCI inclusion** | OCI is a full participant in every pillar with %-share KPI. |
| 4 | **Deploy target** | This OCI compute instance via systemd or `start.sh`. |
| 5 | **Auth** | No auth in v1. Internal-only, trusted-network. |
| 6 | **Geographic scope** | Phase 1: Northern Virginia (Loudoun + Prince William). |
| 7 | **OCI-specific tracking** | OCI included as peer alongside MSFT/AWS/GCP/Meta. |
| 8 | **Vendor integrations** | Shovels.ai ($599/mo), FMP ($29-99/mo), all else $0. |

---

## 10. Non-Functional Requirements

### Scalability
- Handle large, multi-source datasets  

### Accuracy
- Financial-grade parsing accuracy  
- Transparent assumptions  

### Explainability
- All outputs must be auditable and source-linked  

### Extensibility
- Modular agent architecture  

---

## 11. Suggested Agent Architecture

| Agent | Responsibility |
|------|----------------|
| Filing Parser Agent | Extract SEC filing data |
| Earnings Parsing Agent | Parse transcripts |
| Geo Mapping Agent | Normalize location data |
| Supply Chain Agent | Track GPUs, NICs, optics |
| Permit Monitoring Agent | Track construction signals |
| Satellite Analysis Agent | Image processing |
| Triangulation Agent | Cross-layer modeling |
| Explainability Agent | Source traceability |
| Dashboard API Agent | Serve data to UI |

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

> This document is superseded by the PRD and `docs/planning/` structure. All decisions, tech-stack choices, dataset references, EDGAR API patterns, and UX rules conform to `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md` (locked 2026-04-28). See that file for authoritative resolution of all open questions.