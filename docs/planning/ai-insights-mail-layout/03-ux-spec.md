# AI Insights — Sidebar + Detail Pane UX Spec

Scope: visual + interaction spec for `InsightSidebar` and `InsightDetailPane` inside the AI Insights tab. Functional layout is settled; this document pins down measurements, tokens, and states so the frontend agent can implement without guessing. Token references resolve against `frontend/src/styles/insightTokens.ts`.

## 1. Layout grid
- Container: `display: grid; gridTemplateColumns: '320px 1fr'; gap: tokens.spacing.s5 (=20px);`
- Breakpoint: `max-width: 1024px` collapses grid to `1fr`; sidebar renders above detail pane, full width.
- Both columns top-align.
- Sidebar: `position: sticky; top: 24px; alignSelf: flex-start; maxHeight: calc(100vh - 80px); overflowY: auto;` (independent scroll).
- Detail pane: `minWidth: 0` so it can shrink inside the grid track; no special overflow (page scroll is fine).

## 2. Sidebar group headers
- Reuse `Collapsible.tsx` verbatim (chevron + title + count + open/close already tokenised).
- Titles: `"Today"`, `"Saved"`, `"Past runs"`.
- Default open state:
  - Today: `true`
  - Saved: `savedCount > 0`
  - Past runs: `false`

## 3. SidebarRow (compact insight row)
- Element: `<button type="button">` (a11y).
- Padding: `10px 12px` (between `s2` and `s3`).
- Border-left: `3px solid transparent`; selected -> `tokens.color.brand.primary`.
- Background: transparent default; `tokens.color.bg.surfaceAlt` on hover AND when selected (intentionally identical — keep simple).
- Border-bottom: `1px solid tokens.color.border.weak` between rows.
- Typography: `tokens.typography.body`; color `tokens.color.text.primary` when selected, else `tokens.color.text.body`.
- Headline clamp (preferred): `display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;` (max 2 lines). Fallback if unstyled: single-line `whiteSpace: nowrap; overflow: hidden; textOverflow: ellipsis;`.
- Saved indicator (optional): lucide-react `Bell` (filled) at top-right, `size={11}`, color `tokens.color.brand.primary`. Hidden when not saved.
- `aria-current="true"` when selected.
- onClick fires `onSelect(insightId)`.

## 4. Past-run session row (parent of nested insights)
- Same row primitive; content swap: left = date label (e.g. `"Wed May 7 09:00 UTC"`), right = count chip (`"4 insights"`).
- Count chip: bg `tokens.color.brand.tintDark`, 1px border `tokens.color.brand.primary`, radius `tokens.radius.pill` (or `radius.sm` if pill absent), padding `2px 8px`, text `tokens.color.text.body`.
- Expand affordance: chevron rotates 90deg (Collapsible-style).
- Nested SidebarRows beneath get extra `paddingLeft: tokens.spacing.s4 (=16px)` indent.
- Multiple sessions can be expanded simultaneously (matches current `PastRunsSection`).

## 5. InsightDetailPane
- Wrap `<InsightCard ... />` in `<div style={{ minWidth: 0 }}>`.
- Forward all existing `InsightCard` props for the selected insight (body, chart, citations, etc.) — same wiring `SnapshotInsightFeed` uses today.
- Empty state (when `insight == null`):
  - Centered card.
  - Background: `tokens.color.bg.card`.
  - Border: `1px dashed tokens.color.border.weak`.
  - Padding: `tokens.spacing.s8`.
  - Copy: `"Pick an insight from the sidebar to read its detail."`
  - Text color: `tokens.color.text.caption`.
  - No icon in v1.

## 6. Visual tokens cheat sheet
| Purpose | Token | Hex |
|---|---|---|
| Selected accent (border-left) | `tokens.color.brand.primary` | `#3b82f6` |
| Selected row bg | `tokens.color.bg.surfaceAlt` | `#162032` |
| Hover row bg | `tokens.color.bg.surfaceAlt` | `#162032` |
| Default row text | `tokens.color.text.body` | `#e2e8f0` |
| Caption / empty-state text | `tokens.color.text.caption` | `#94a3b8` |
| Faint chip text | `tokens.color.text.faint` | `#64748b` |
| Count-chip bg | `tokens.color.brand.tintDark` | `#1e3a5f` |
| Count-chip border | `tokens.color.brand.primary` | `#3b82f6` |
| Row divider | `tokens.color.border.weak` | `#1e293b` |
| Empty-state card bg | `tokens.color.bg.card` | `#1e293b` |

## 7. Accessibility musts
- Each `SidebarRow` is a `<button>` with `aria-label="Select insight: <headline>"`.
- Use `aria-current="true"` on selected row (not `aria-selected` — buttons don't take it).
- Group headers retain `Collapsible`'s existing `aria-expanded` wiring.
- No new color combinations introduced; existing audited contrasts apply.

## 8. Out of scope (v1)
- Selection transition animations — swap in a single frame.
- Mobile polish below 1024px beyond the single-column fallback.
- Drag-to-resize sidebar.
- Keyboard navigation between rows (Tab order from native buttons is sufficient).
