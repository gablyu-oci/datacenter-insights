# Power Contract Announcements — Table Design Spec

## 1. Column Order + Widths (1280px viewport, horizontal-scroll friendly)

| # | Column   | Min | Max  | Behavior                          | Sortable |
|---|----------|-----|------|-----------------------------------|----------|
| 0 | Expand   | 28  | 28   | fixed, icon only                  | no       |
| 1 | Buyer    | 140 | 180  | fixed, truncate + tooltip         | yes      |
| 2 | Seller   | 140 | 200  | flex, truncate + tooltip, "—" null| yes      |
| 3 | Headline | 320 | 1fr  | flex, truncate (1 line)           | no       |
| 4 | Capacity | 96  | 96   | fixed, right-aligned, "MW" suffix | yes      |
| 5 | Energy   | 110 | 130  | fixed, chip                       | yes      |
| 6 | Status   | 120 | 140  | fixed, semantic pill, centered    | yes      |
| 7 | Source   | 96  | 96   | fixed, pill, centered             | yes      |
| 8 | Announced| 104 | 104  | fixed, right-aligned (YYYY-MM-DD) | yes      |

Total min ≈ 1154px; horizontal scroll engages below 1200px.

## 2. Filter Bar (single row, dark, 56px tall, padding 12/16, gap 10, border-bottom #1e293b)

```
[ search 320w ] [ Buyer ▾ chips ] [ Energy ▾ chips ] [ All 193 | Aterio 166 | EDGAR 27 ]   [ Clear filters ]
```

- Inputs/dropdowns: height 32, radius 6, bg #0f172a, border #334155, text #cbd5e1, placeholder #64748b. Focus ring 2px #38bdf8 (offset 0).
- Search: leading magnifier icon 14px #94a3b8, padding-left 30. Matches buyer/seller/headline.
- Multi-selects render selected values as removable chips inside the trigger (radius 4, bg #1e293b, text #cbd5e1, ×-button #94a3b8 → #f8fafc on hover).
- Source toggle: segmented control, active segment bg #1e293b border #38bdf8 text #f8fafc; inactive text #94a3b8. Counts in #64748b.
- Clear filters: ghost button, text #94a3b8 → #f8fafc on hover, only enabled when any filter active.

## 3. Source Column

Pill, centered. Padding 2px 8px, radius 999, font 10px / weight 700 / letter-spacing 0.4, uppercase.
- ATERIO: bg `#f9731622`, text #f97316, no border.
- SEC EDGAR: bg `#3b82f622`, text #3b82f6, no border.

## 4. Status Column

Same pill geometry as Source but radius 4 (rectangular, smaller-feeling) and font 10px / weight 600 (not uppercase). Bg `${color}22`, text `${color}`.

- Aterio `plant_phase_stage`: Operating/Active #10b981, Construction #f59e0b, Announcement/Planned #38bdf8, Cancelled #ef4444, Delayed #f97316, default #64748b.
- EDGAR `form_type`: 8-K #8b5cf6, 10-K #64748b, 10-Q #94a3b8.

Header tooltip lists the legend. Empty value renders muted "—" #475569.

## 5. Buyer Cell — 3px Left-Edge Row Stripe

Choice (a). A 3px full-height stripe on the row's leftmost cell (color = COMPANY_COLORS[buyer], fallback #475569 for non-hyperscalers). Justification: across 193 rows a row-edge stripe creates a vertical rhythm the eye groups by company without consuming horizontal space or competing with the Energy/Status/Source pills, which a dot-prefix would visually crowd. Buyer text renders as plain #f8fafc, weight 600, 12px.

## 6. Sort Affordance

Inactive sortable headers: stacked up/down chevrons (8px) #475569, margin-left 4. Active column: single directional chevron in #f8fafc. Non-sortable (Headline, Source) render no chevron. Header hover bg #1e293b, cursor pointer; `aria-sort` set on active.

## 7. Row Treatment

Row height 44px (was 48). Zebra: even rows #0b1220, odd rows #0f172a. Hover bg #1e293b (overrides zebra). Expand caret is a single right-chevron that rotates 90° clockwise when open (transition 120ms ease-out). Header row sticky (`position: sticky; top: 0; z-index: 2`) with bg #0f172a and border-bottom #334155.

## 8. Empty + Loading States

- Empty: centered, 64px vertical padding. Inbox-style icon (lucide `Inbox`, 32px, #475569). Heading "No deals match these filters" #cbd5e1 14px / 600. Sub "Try clearing filters or widening capacity range." #64748b 12px. Button "Clear filters" (ghost, border #334155, text #cbd5e1, 32h, radius 6).
- Loading: 8 skeleton rows at 44px. Each cell renders a rounded rectangle (radius 4, height 12, width 60–80% of cell). Shimmer: 1.4s linear-gradient sweep #1e293b → #334155 → #1e293b. `prefers-reduced-motion`: static #1e293b block.

## Accessibility

Headers as `<button>` inside `<th>` with `aria-sort="ascending|descending|none"`. Filter bar landmarks `role="search"`. Pills include `title` and `aria-label` (e.g. "Source: SEC EDGAR"). Focus ring 2px #38bdf8 on every interactive. Stripe color is decorative; buyer name remains the textual identifier for screen readers.

---

Spec file: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/power_table_design_spec.md`
