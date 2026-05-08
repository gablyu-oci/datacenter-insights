# UX/UI Spec: Counterparty Pies (CompanyDetailPanel)

**Owner:** Product Designer | **Status:** Draft | **Date:** 2026-05-08
**Source PRD:** `docs/prds/counterparties-pies.md` | **Arch:** `docs/architecture/counterparties-pies-arch.md` | **Research:** `docs/research/counterparties-pies-research.md`

## User Flow
1. User clicks a row in the Companies table -> `CompanyDetailPanel` opens (existing behavior).
2. User scrolls past Capacity Summary -> Role Distribution -> Sites-by-State.
3. User reaches the new "Counterparties" section, sees two pies (Buyers, Sellers) sharing a single fetched payload.
4. User toggles "Sites | MW" on either card independently; pie + legend re-render client-side, no refetch.
5. User hovers a slice -> Recharts tooltip shows `{name}: {value}`. User closes panel to return to the table.

## Layout (Wireframe)
Inserted as a new section in `CompanyDetailPanel` content area, **after Sites-by-State, before Filings**. Section width matches the panel content column (max 700px - 40px padding = 660px). On viewports where the panel inner width is `< 640px`, the two cards stack vertically.

```
+------------------------------------------------------------------+
|  COUNTERPARTIES                                                  |  <- 11px uppercase #94a3b8 header (matches "Capacity Summary")
+------------------------------------------------------------------+
| +----------------------------+  +----------------------------+   |
| | Buyers                     |  | Sellers                    |   |  <- Title 13px #e2e8f0 700
| | When this company is       |  | When this company is       |   |  <- Subtitle 11px #64748b
| | provider/developer         |  | end_user                   |   |
| | [ Sites | MW ]             |  | [ Sites | MW ]             |   |  <- Segmented toggle, 28px tall
| |                            |  |                            |   |
| |        ( donut )           |  |        ( donut )           |   |  <- 116px ResponsiveContainer
| |    outerR 48 / innerR 26   |  |    outerR 48 / innerR 26   |   |
| |                            |  |                            |   |
| | [#] Amazon          12     |  | [#] Vistra Energy   8      |   |  <- 2-col legend grid, 11px
| | [#] Microsoft       9      |  | [#] NextEra         5      |   |
| | [#] Other           4      |  | [#] Other           2      |   |  <- "Other" always last, grey
| +----------------------------+  +----------------------------+   |
|     flex: 1, minWidth: 0          flex: 1, minWidth: 0           |
+------------------------------------------------------------------+
```
Section container: `marginBottom: 20`, `gap: 12` between cards. Each card: `background:#1e293b`, `border:1px solid #334155`, `borderRadius:8`, `padding:12 14`, `minHeight:180px`.

## Component Specs

### CounterpartyPies (parent)
- Fetches `/api/companies/{id}/counterparties` once via `useApi`. Renders section header, then a flex row of two `CounterpartyPieCard`s (`flex-direction: row` desktop, `column` when container `< 640px` — use a CSS container query OR a `useResizeObserver` ref; if the codebase has neither precedent, use a window `matchMedia('(max-width: 720px)')` since the panel itself is centered and capped at 700px).
- Owns loading / error / empty-payload UI for the whole section (see States below).

### CounterpartyPieCard
Props: `{ side: "as_provider" | "as_end_user", title: "Buyers" | "Sellers", subtitle: string, data: SidePayload }`.
Local state: `metric: "sites" | "mw"` (default `"sites"`).

**1. Title row** — flex column, marginBottom 8.
- Title: `fontSize:13, fontWeight:700, color:#e2e8f0`.
- Subtitle: `fontSize:11, color:#64748b, marginTop:2`.

**2. Toggle row** — segmented 2-button control, marginBottom 10. **Precedent search:** no existing segmented control found in `CompaniesTab.tsx`, `PowerTab.tsx`, or `TriangulationTab.tsx`; spec is greenfield, hex codes below are authoritative.
- Wrapper: `display:inline-flex, background:#0f172a, border:1px solid #334155, borderRadius:6, padding:2`.
- Each `<button>`: `padding:4px 10px, fontSize:11, fontWeight:600, borderRadius:4, border:none, cursor:pointer, transition:none`.
- Active: `background:#3b82f6, color:#ffffff`. Inactive: `background:transparent, color:#64748b`. Hover (inactive only): `color:#94a3b8`.
- Disabled (empty side): both buttons `opacity:0.4, cursor:not-allowed`, no hover change.

**3. Donut** — `ResponsiveContainer width="100%" height={116}`.
- `<Pie outerRadius={48} innerRadius={26} dataKey="value" labelLine={false} sortValues={false} isAnimationActive={false}/>` (no on-slice labels, no `label` prop).
- Slice colors: top-7 cycle through `["#3b82f6","#22c55e","#f59e0b","#8b5cf6","#06b6d4","#ec4899","#f97316"]` (subset of `ROLE_COLOR_PALETTE` from `CompaniesTab.tsx:102`). "Other" `<Cell fill="#64748b"/>`, rendered LAST.
- Tooltip: reuse the dark style — `contentStyle:{background:"#0f172a", border:"1px solid #334155", borderRadius:8}, labelStyle:{color:"#e2e8f0"}, itemStyle:{color:"#94a3b8"}`. Format: `${name}: ${value}` where MW values use `toFixed(0) + " MW"` and Sites values use raw integers.

**4. Legend** — custom HTML, `display:grid, gridTemplateColumns:"1fr auto", columnGap:8, rowGap:4, marginTop:8`, `role="list"`. Each row: `role="listitem", display:flex, alignItems:center, gap:6, fontSize:11, color:#cbd5e1`.
- Swatch: `width:8, height:8, borderRadius:2, background:<sliceColor>, flexShrink:0`.
- Name: truncate to 18 chars; if longer, slice to 17 + `"..."`. `whiteSpace:nowrap, overflow:hidden`.
- Value: right-aligned, `color:#94a3b8, fontVariantNumeric:"tabular-nums"`. Sites = integer; MW = rounded integer + ` MW`.
- "Other" row: swatch `#64748b`, name `"Other"`, label suffix `"(${total_counterparties - 7} more)"` in `#64748b` 10px when applicable. Always rendered last regardless of value.

## Design Tokens (hex, inline-style ready)
| Role | Hex |
|---|---|
| Panel bg | `#0f172a` |
| Card bg | `#1e293b` |
| Border | `#334155` |
| Brand / active toggle | `#3b82f6` |
| Text primary | `#e2e8f0` |
| Text secondary | `#cbd5e1` |
| Text muted (subtitle, value) | `#94a3b8` |
| Text faint / Other / disabled | `#64748b` |
| Section header | `#94a3b8` (11px, 600, uppercase, letter-spacing 0.05em) |
| Categorical 1..7 | `#3b82f6 #22c55e #f59e0b #8b5cf6 #06b6d4 #ec4899 #f97316` |
| Radius (card) | 8 | Radius (toggle wrapper) | 6 | Radius (toggle btn) | 4 | Radius (swatch) | 2 |
| Spacing | 4 / 8 / 12 / 20 |
| Type scale | 10 / 11 / 13 (title) |

## Interaction States
| State | Visual |
|---|---|
| Loading (whole section) | Render section header + two card skeletons. Each card shows title row + disabled toggle + a centered `"Loading..."` at `color:#64748b, fontSize:12, height:116px`. |
| Loaded, populated | Spec above. |
| Loaded, side empty (`sites:[]`) | Title + subtitle visible. Toggle visible but **disabled** (`opacity:0.4, cursor:not-allowed, aria-disabled="true"`). Replace donut + legend with a single centered div, `height:120px, display:flex, alignItems:center, justifyContent:center, color:#64748b, fontSize:12` showing `"No buyers known"` / `"No sellers known"`. |
| Loaded, both sides empty | Whole section still renders (do not hide); each card shows its empty state. |
| Error | Section body replaced with `color:#ef4444, fontSize:13, padding:"20px 0", textAlign:"center"` reading `"Failed to load counterparties."` — matches `detError` pattern at `CompaniesTab.tsx:200`. |
| Toggle hover (enabled, inactive) | `color` shifts `#64748b -> #94a3b8`. No background change. |
| Toggle focus-visible | `outline:2px solid #3b82f6, outline-offset:2px`. |
| Slice hover | Recharts default opacity dim on siblings; no custom override. |

## Content / Copy
- Section header: `COUNTERPARTIES`
- Card titles: `Buyers`, `Sellers`
- Card subtitles: `When this company is provider/developer`, `When this company is end_user`
- Toggle labels: `Sites`, `MW`
- Empty: `No buyers known`, `No sellers known`
- Error: `Failed to load counterparties.`
- Tooltip value formatting: integers for Sites, `"### MW"` (no decimals) for MW.

## Accessibility Notes
- Toggle buttons: real `<button type="button">` with `aria-pressed={metric === "sites"}` / `aria-pressed={metric === "mw"}`. Group wrapper has `role="group" aria-label="Metric"`. Disabled state uses `disabled` attr + `aria-disabled="true"`.
- Pie SVG: pass `aria-label={`${title} distribution by ${metric === "sites" ? "sites" : "MW"} for ${companyName}`}` on the `ResponsiveContainer`'s child wrapper (Recharts does not forward props to the inner `<svg>`; wrap in a div with the aria-label and `role="img"`).
- Legend container: `role="list"`. Each row: `role="listitem"`. Swatches are `aria-hidden="true"` (color is decorative; name is the source of truth).
- Color is never the only signal — every legend row has a text name and a numeric value.
- Focus order: first toggle button -> second toggle button -> (skip pie SVG, not interactive) -> next section. Tab order matches DOM order.
- Color contrast: `#cbd5e1` on `#1e293b` = 11.6:1 (AAA). `#94a3b8` on `#1e293b` = 6.6:1 (AA). `#64748b` on `#1e293b` = 4.0:1 (AA Large only — used only for 11px+ subtitles and disabled/Other where reduced emphasis is intentional).
- Reduced motion: Recharts animation already disabled (`isAnimationActive={false}`).

## Anti-goals (out of scope)
- No animations beyond Recharts default (and we explicitly disable pie animation).
- No tooltips on legend rows.
- No clickable slices, no clickable legend rows, no drill-through to a counterparty detail panel.
- No card-layout redesign of the parent panel; this section is additive only.
- No persistence of `metric` selection across panel open/close.
