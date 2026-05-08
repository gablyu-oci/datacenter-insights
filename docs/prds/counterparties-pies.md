# PRD: Buyer/Seller Counterparty Pies on Companies Tab

**Owner:** PM (Strategic Insights) | **Status:** Draft | **Sprint:** 1 | **Date:** 2026-05-08

## Problem Statement
Analysts using the Companies tab today can see a company's site count and aggregate capacity, but cannot quickly answer the two questions that drive most competitive conversations: *"When this company builds, who buys?"* and *"When this company leases capacity, who sells to them?"* Today they must hand-pivot site-level association data in a separate notebook. A per-card counterparty visualization closes that gap and makes the Companies tab a self-serve view for buyer/seller relationships across the hyperscaler/developer ecosystem.

## Goals
- Surface, on each Companies tab card, the distribution of counterparties when the company acts as provider/developer vs. end_user/customer.
- Let analysts toggle between distinct-site count and MW-weighted views without leaving the card.
- Reuse existing data (`site_company_associations`, `sites`) and existing Recharts dependency; ship in one sprint.

## Non-Goals
- Redesigning the Companies tab layout or card chrome.
- Adding new ingestion or new role taxonomies.
- Touching the AI Insights v2 path, agentic synthesis, or any LLM tooling.
- Time-series / historical counterparty trends.

## User Stories

### US-1: Buyers-when-provider pie
*As a competitive analyst, I want to see who buys capacity from a developer (e.g., Crusoe, Tract) so that I can identify their top hyperscaler customers at a glance.*
- **AC:** Card renders a pie of end_user/customer counterparties across all sites where the card's company has role provider or developer; self-edges excluded; empty state shown when zero counterparties.

### US-2: Sellers-when-end_user pie
*As an OCI strategy lead, I want to see which developers sell to a hyperscaler (e.g., Meta, AWS, Microsoft) so that I can map their supply concentration.*
- **AC:** Second pie renders provider/developer counterparties across sites where the card's company has role end_user; rendered side-by-side with US-1.

### US-3: Sites vs MW toggle
*As an analyst, I want to flip between "sites" and "MW" so that I can distinguish breadth (many small deals) from depth (few large ones).*
- **AC:** Per-card toggle switches both pies between distinct-site count and MW sum. MW uses `site_company_associations.mw_share` when present, else `sites.power_capacity_mw`, else the row is excluded from the MW view (and noted in tooltip/legend).

### US-4: Counterparty endpoint
*As a frontend dev, I want one endpoint per company that returns both pies' data so that the card stays simple.*
- **AC:** `GET /api/companies/{id}/counterparties` returns `{ as_provider: [{company_id, name, sites, mw}], as_end_user: [...] }`, top 7 + `Other` bucket per side, works for Crusoe, Tract, Meta, AWS, Microsoft. Two regression tests: one populated, one empty.

## Success Metrics
- Endpoint returns non-empty `as_provider` or `as_end_user` for >= 80% of the top 25 companies by site count.
- p95 endpoint latency < 300 ms on local dev DB.
- Zero regressions in existing `/api/companies/*` tests; frontend `tsc --noEmit` clean.
- Qualitative: Karan can answer "top 3 buyers of Crusoe capacity" from the UI in < 10 seconds.

## Acceptance Criteria (Spec Verbatim)
a. New endpoint `GET /api/companies/{id}/counterparties` returns documented shape and works for at least 5 named companies (Crusoe, Tract, Meta, AWS, Microsoft).
b. Frontend Companies tab renders 2 pie charts per company card (or empty state), with working sites/MW toggle.
c. Pie slices color-coded from OCI brand palette; legend shows top entity names + `Other` aggregate when >7 counterparties.
d. Backend test suite stays green; add at least 2 regression tests for the new endpoint (populated + empty).
e. Frontend type-check passes (`npx tsc --noEmit`).
f. No backend regressions on existing `/api/companies/*` endpoints.

## Out of Scope
- Broad CompaniesTab refactor or card-layout redesign.
- Any change to AI Insights v2 path, prompts, or tools.
- Mutations to the `sites` table or schema migrations.
- New charting libraries; must use existing Recharts.
- New ingestion sources or role-mapping changes.

## Open Questions
- Should self-associations (company appearing on both sides of a site) ever count? Default: exclude.
- When `mw_share` and `power_capacity_mw` are both null, do we surface a "n MW unknown" footnote, or silently drop? Default: drop, footnote in legend.
- Color palette: confirm the OCI brand palette tokens already exposed in the SOUL theme cover >=8 distinct hues for top7 + Other.
