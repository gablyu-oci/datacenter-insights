# Power Contract Announcements — Table UX Brief

## Acceptance Criteria

1. **Filter bar modernized**: replace raw `<select>` with styled dropdowns matching the dark theme (rounded, subtle border, hover/focus states, chevron icon, consistent height); add a search input (buyer/seller/headline) and a "Clear filters" affordance.
2. **Buyer cell de-emphasized**: remove the colored pill background behind the buyer name; render as plain typographic text. Keep ATERIO/EDGAR pill intact.
3. **New "Source" column**: dedicated column rendering ATERIO vs SEC EDGAR pill (moved out of the buyer cell), sortable and filterable.
4. **New "Seller" column**: surface `seller` between Buyer and Headline; truncate with tooltip on overflow; "—" when null.
5. **Status column fixed**: Aterio rows show `plant_phase_stage` (Operating=green, Construction=amber, Planned/Announced=blue, Cancelled=red); EDGAR rows show `form_type` (8-K=violet, 10-K/10-Q=slate). Legend in header tooltip.
6. **Sortable headers** on Capacity, Announced, Buyer — most users scan by size/recency.
7. **Source-type filter pill row** (All / Aterio / EDGAR) with live counts — makes the 166/27 split legible.
8. **Empty + loading states**: skeleton rows on load; "No deals match filters" with reset CTA — avoids dead table.
9. **Row hover + zebra striping**: improves scanability across ~193 rows.
10. **External link icons** on `source_url`/`edgar_url` open in new tab with `rel="noopener"`.

## Out of Scope
KPI tiles, bar chart, line chart, KPI cards above table; backend/API changes; virtualization; pagination redesign; mobile layout.

## Rollback
Frontend-only change. If build breaks: `git checkout main -- frontend/src/components/tabs/PowerTab.tsx`.
