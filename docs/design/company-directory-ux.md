# Company Directory — Filter Bar & Pagination UX Spec

Scope: adds a filter bar card above the existing Company Directory table card,
and a pagination bar at the foot of the table card. Reuses the visual language
already established in `frontend/src/components/tabs/CompaniesTab.tsx`. No new
tokens, no new dependencies.

---

## User Flow

1. User lands on Companies tab. Filter bar renders with empty defaults; table
   loads page 1 sorted by `site_count` desc.
2. User types in search input. After 250 ms debounce, request fires with the
   current filter set; previous rows stay visible at opacity 0.6 until new
   results land.
3. User changes Role dropdown / Public-Private segmented control / Min MW
   input. Each change resets page to 1 and refetches immediately (no debounce
   for selects/segmented; 250 ms debounce on number input keystrokes).
4. User clicks a sortable header. Sort direction toggles; page resets to 1.
5. User clicks a page tile or prev/next chevron. Table scrolls to top of
   table card; row click behavior (open `CompanyDetailPanel`) unchanged.
6. If filter combination yields zero rows, table area shows empty state with
   a clear-filters hint.

---

## Wireframes

```
+--------------------------------------------------------------------------+
| FILTER BAR CARD  (CARD_STYLE)                                            |
|                                                                          |
|  [Search company or ticker...   ] [Role: All v] [All|Public|Private]     |
|  [Min MW]                                                                |
+--------------------------------------------------------------------------+

+--------------------------------------------------------------------------+
| COMPANY DIRECTORY CARD  (CARD_STYLE)                                     |
|                                                                          |
|  Company Directory -- Click row to view details                          |
|                                                                          |
|  Company^   Ticker   Type   Roles            Sites    Total MW           |
|  ----------------------------------------------------------------------  |
|  Microsoft  MSFT     PUBLIC tenant developer 412      6,820              |
|  Google     GOOGL    PUBLIC owner tenant     287      4,210              |
|  ...                                                                     |
|                                                                          |
|  Showing 1-50 of 1,284            < 1  2  3 ... 26  >                    |
+--------------------------------------------------------------------------+
```

Wrap behavior at <720px:

```
[Search ............................. ]
[Role v]  [All|Public|Private]  [Min MW]
```

Pagination stack at <560px:

```
Showing 1-50 of 1,284
< 1 2 3 ... 26 >
```

---

## Component Specs

### 1. Filter Bar Card
- Wrapping container reuses `CARD_STYLE` (bg `#1e293b`, border `1px solid #334155`,
  border-radius 12, padding 20). Sits in its own card directly above the
  Company Directory table card.
- Layout: `display:flex; gap:10px; align-items:center; flex-wrap:wrap;`.
- All interactive controls share height **34px** for visual alignment.

#### 1a. Search input
- Wrapper: `position:relative; min-width:240px; flex:1 1 240px; max-width:360px;`.
- Leading icon: `<Search size={14} color="#94a3b8" />` absolute-positioned
  left 10px, vertically centered.
- Input: `height:34px; padding:0 12px 0 32px; background:#1e293b; border:1px solid #334155;
  border-radius:8px; color:#e2e8f0; font-size:13px;`.
- Placeholder color `#94a3b8`, text "Search company or ticker...".
- Debounce: 250 ms before firing the request. Resets page to 1.
- `aria-label="Search companies"`.

#### 1b. Role dropdown
- Native `<select>` (no new dependency).
- Style: `height:34px; padding:0 28px 0 10px; background:#1e293b; border:1px solid #334155;
  border-radius:8px; color:#e2e8f0; font-size:12px; appearance:none;`.
- Custom caret: `<ChevronDown size={12} color="#94a3b8" />` absolute right 8px.
- Options (hardcoded): `All`, `Operator`, `Owner`, `Tenant`, `Developer`, `Lessor`.
  - Add `// TODO: source role list from /api/companies/roles once endpoint exists`.
- Selecting a value resets page to 1.

#### 1c. Public/Private segmented control
- Container: `display:inline-flex; height:34px; border-radius:8px; overflow:hidden; gap:0;`.
- Three buttons in order: `All`, `Public`, `Private`.
- Each button: `height:34px; padding:0 14px; font-size:12px; font-weight:600;
  border:1px solid #334155; background:transparent; color:#94a3b8; cursor:pointer;`.
- Middle button shares left/right borders with neighbors (collapse with
  `margin-left:-1px`); first button rounds left corners, last rounds right.
- Active state: `background:#3b82f6; color:#ffffff; border-color:#3b82f6;`.
- `aria-pressed="true|false"` per button.

#### 1d. Min MW number input
- `<input type="number" min="0" step="50" />`.
- Style: `width:110px; height:34px; padding:0 10px; background:#1e293b; border:1px solid #334155;
  border-radius:8px; color:#e2e8f0; font-size:13px; placeholder:"Min MW";`.
- Placeholder color `#94a3b8`. 250 ms debounce on keystrokes.
- `aria-label="Minimum total megawatts"`.

### 2. Table Header Sort Affordance
- Sortable headers (`Company`, `Ticker`, `Sites`, `Total MW`): existing
  `cursor:pointer; user-select:none;` retained. When that column is the active
  sort field, render `<ChevronUp size={10}/>` (asc) or `<ChevronDown size={10}/>`
  (desc) inline at `margin-left:3px`. No chevron when column is inactive.
- Non-sortable headers (`Type`, `Roles`): render plain `<th>` with
  `cursor:default`, no chevron, no click handler. Same `#64748b` color and
  10/14 padding as today.
- Note: `Ticker` becomes server-sortable in this iteration (was not sortable
  in the current build). All other styling stays identical to current header
  row in `CompaniesTab.tsx`.

### 3. Pagination Bar
- Lives **inside** the table card, directly below the `<table>` and above
  `<CitationFooter />`. Top margin 16, top border `1px solid #1e293b`,
  padding-top 12.
- Layout: `display:flex; justify-content:space-between; align-items:center; gap:12px;`.

#### 3a. Left — result count
- Text: `Showing {from}-{to} of {total.toLocaleString()}`.
- Style: `color:#94a3b8; font-size:12px;`.
- `from = (page-1)*page_size + 1`, `to = min(page*page_size, total)`.

#### 3b. Right — page tiles
- Container: `display:flex; align-items:center; gap:4px;`.
- Prev chevron: 28x28 tile rendering the character `<`. Disabled when `page===1`.
- Next chevron: 28x28 tile rendering `>`. Disabled when `page===lastPage`.
- Number tiles: up to 7 visible slots using this window algorithm:
  - Always show page 1 and `lastPage`.
  - Show current page and its immediate neighbors.
  - Replace gaps with a non-interactive tile labeled `...` (same size,
    `cursor:default`, no hover).
  - Examples: pages 1..5 -> `1 2 3 4 5`. Page 13 of 26 ->
    `1 ... 12 13 14 ... 26`. Page 26 of 26 -> `1 ... 23 24 25 26`.
- Tile base style: `width:28px; height:28px; border-radius:6px; font-size:12px;
  font-weight:600; display:inline-flex; align-items:center; justify-content:center;
  border:1px solid #334155; background:#1e293b; color:#94a3b8; cursor:pointer;`.
- Active tile: `background:#3b82f6; color:#ffffff; border-color:#3b82f6;`.
- Inactive hover: `background:#22304a;` (matches existing row hover).
- Disabled prev/next: `opacity:0.4; cursor:not-allowed; pointer-events:none;`.
- Each numeric tile: `aria-label="Go to page N"`; active tile also
  `aria-current="page"`. Prev/Next: `aria-label="Previous page"` /
  `"Next page"`.

---

## Design Tokens (reused — do not invent)

| Token            | Value       | Usage                                   |
|------------------|-------------|-----------------------------------------|
| `--card-bg`      | `#1e293b`   | filter card, inputs, tiles              |
| `--page-bg`      | `#0f172a`   | tab background (unchanged)              |
| `--border`       | `#334155`   | inputs, tiles, segmented buttons        |
| `--border-soft`  | `#1e293b`   | bottom border above pagination row      |
| `--text`         | `#e2e8f0`   | typed input text                        |
| `--text-muted`   | `#94a3b8`   | placeholder, "Showing X-Y of N"         |
| `--text-dim`     | `#64748b`   | non-sortable header text                |
| `--accent`       | `#3b82f6`   | active segmented button, active tile    |
| `--success`      | `#4ade80`   | PUBLIC badge text (unchanged)           |
| `--neutral`      | `#a8a29e`   | PRIVATE badge text (unchanged)          |
| `--row-hover`    | `#22304a`   | tile hover, row hover                   |

Type ramp: 10px uppercase labels / 11-12px secondary / 13px input text /
font-weights 500-700 per existing component.

---

## Interaction States

| Element              | Default                          | Hover                | Focus (keyboard)                          | Active / Selected                       | Disabled                                  |
|----------------------|----------------------------------|----------------------|-------------------------------------------|------------------------------------------|-------------------------------------------|
| Search input         | bg `#1e293b`, border `#334155`   | border `#475569`     | outline 2px `#3b82f6` offset 0            | n/a                                      | n/a                                       |
| Role select          | as default                       | border `#475569`     | outline 2px `#3b82f6`                     | n/a                                      | n/a                                       |
| Segmented button     | text `#94a3b8`, border `#334155` | bg `#22304a`         | outline 2px `#3b82f6`                     | bg `#3b82f6`, text `#fff`                | n/a                                       |
| Min MW input         | as search                        | border `#475569`     | outline 2px `#3b82f6`                     | n/a                                      | n/a                                       |
| Sort header (active) | text `#cbd5e1` + chevron         | text `#e2e8f0`       | outline 2px `#3b82f6`                     | chevron up/down                          | n/a                                       |
| Page tile            | bg `#1e293b`, text `#94a3b8`     | bg `#22304a`         | outline 2px `#3b82f6` offset 1            | bg `#3b82f6`, text `#fff`                | opacity 0.4, cursor `not-allowed`         |
| Table (refetching)   | full opacity                     | n/a                  | n/a                                       | opacity 0.6, `pointer-events:none`       | n/a                                       |

**Loading state**: while a new filter/page request is in flight, do NOT swap
to a spinner. Keep the previously rendered rows visible and apply
`opacity:0.6; pointer-events:none;` to the `<table>` element only. Pagination
controls remain interactive so a user can change their mind mid-flight; the
in-flight request is cancelled / superseded by the next one.

**Empty state**: when `total === 0`, replace `<tbody>` with a centered block:
- Outer: `padding:48px 20px; text-align:center;`
- Line 1: "No companies match these filters." — color `#94a3b8`, font-size 13px.
- Line 2: "Try clearing the search or widening the MW threshold." — color
  `#64748b`, font-size 11px, margin-top 6.
- Optional inline button "Clear filters" — same styling as inactive page
  tile, padding `4px 10px`, fontSize 12, resets all four filter fields and
  page to 1.

---

## Responsive Notes

- `>=720px`: filter bar single row, controls flex-wrap as needed.
- `<720px`: filter bar wraps onto two rows. Search takes full width on row 1;
  Role + segmented + Min MW share row 2. `flex-wrap:wrap` already handles
  this — no media query required.
- `<560px`: pagination bar stacks vertically. Achieve via
  `flex-wrap:wrap; row-gap:8px;` on the pagination row container so the
  "Showing X-Y of N" line lands first, page tiles below.
- Page tile count compresses naturally because the ellipsis algorithm caps
  visible numeric tiles at 7 regardless of width.

---

## Accessibility Notes

- Search input: `aria-label="Search companies"`. Pair with a visually hidden
  `<label>` for AT users if the lucide `Search` icon is the only visual cue.
- Role select: native `<select>` exposes role/state automatically; ensure
  `<label htmlFor>` (visually hidden) reads "Filter by role".
- Segmented control: render as `<button type="button">` elements (not radio
  inputs) with `aria-pressed` reflecting selection. Group inside a
  `role="group"` container with `aria-label="Filter by ownership type"`.
- Min MW: `aria-label="Minimum total megawatts"`, `inputmode="numeric"`.
- Sort headers: add `aria-sort="ascending" | "descending" | "none"` on each
  `<th>` reflecting current state.
- Pagination: prev/next get `aria-label="Previous page"` /
  `"Next page"`; numeric tiles get `aria-label="Go to page {n}"`; current
  page also carries `aria-current="page"`. Ellipsis tiles are
  `aria-hidden="true"` and not focusable (`tabindex="-1"`).
- Focus order: search -> role -> segmented (3 stops) -> min MW -> sortable
  headers left-to-right -> rows -> prev -> page tiles -> next.
- Color contrast: `#94a3b8` on `#1e293b` measures ~4.6:1 (AA for body text).
  Active tile `#ffffff` on `#3b82f6` is ~4.5:1 (AA). PUBLIC/PRIVATE badges
  unchanged from current implementation.
- Live region: wrap "Showing X-Y of N" in `aria-live="polite"` so screen
  readers announce the new result count after a filter/page change.
