# UX Spec: Save Toggle, Past Runs, and Saved Insights on the AI Insights Tab

**Status:** Draft, ready for engineering
**Owner:** Product Design
**Surface:** AI Insights tab (existing `SnapshotInsightFeed` + two new collapsible sections beneath it)
**Last updated:** 2026-05-13

This document specifies three additions to the AI Insights tab:

1. A working **Save** toggle on every `InsightCard` (replaces the placeholder `SubscribeButton` whose "V3 — coming soon" toast is being removed).
2. A **Past runs** collapsible section.
3. A **Saved insights** collapsible section.

Tokens referenced by name come from
`frontend/src/styles/insightTokens.ts`. No new tokens are introduced
unless explicitly noted at the end of the doc.

---

## 1. Information Architecture

The AI Insights tab is a single vertical stack on a `tokens.color.bg.page`
background. From top to bottom inside `TabWrapper`:

| Order | Block | Status |
|---|---|---|
| 1 | Pillar header (rendered by `TabWrapper`) | Existing |
| 2 | `SnapshotInsightFeed` (latest completed session) | Existing |
| 3 | `PastRunsSection` (collapsible) | **NEW** |
| 4 | `SavedInsightsSection` (collapsible) | **NEW** |

### Stacking and spacing

- Each block is full-width inside the tab's content column.
- Vertical gap between blocks: `tokens.spacing.s7` (32px).
- The two new sections share identical chrome so they read as a pair.
- There is no horizontal scroll anywhere; insight cards reflow inside
  the section just as they do in `SnapshotInsightFeed`.
- Z-order: nothing in these sections floats. The Save button is inline
  inside each card, not absolutely positioned.

### ASCII — whole tab, both new sections collapsed

```
+--------------------------------------------------------------------------+
|  TabWrapper header (pillar: "AI Insights")                               |
+--------------------------------------------------------------------------+
|                                                                          |
|  SnapshotInsightFeed                                                     |
|   ┌──────────────────────────────────────────────────────────────────┐   |
|   |  Run on 2026-05-13 09:02 UTC · 5 insights · focus: hyperscaler   |   |
|   |  ┌──────────────────────────┐  ┌──────────────────────────┐      |   |
|   |  | InsightCard              |  | InsightCard              |      |   |
|   |  | …                        |  | …                        |      |   |
|   |  | [bell-outline] Save      |  | [bell-filled]   Saved    |      |   |
|   |  └──────────────────────────┘  └──────────────────────────┘      |   |
|   |  ┌──────────────────────────┐  ┌──────────────────────────┐      |   |
|   |  | InsightCard              |  | InsightCard              |      |   |
|   |  └──────────────────────────┘  └──────────────────────────┘      |   |
|   └──────────────────────────────────────────────────────────────────┘   |
|                                                                          |
|  ── 32px gap ───────────────────────────────────────────────────────     |
|                                                                          |
|  [chevron ▸]  Past runs (12)                                             |
|                                                                          |
|  ── 32px gap ───────────────────────────────────────────────────────     |
|                                                                          |
|  [chevron ▸]  Saved insights (4)                                         |
|                                                                          |
+--------------------------------------------------------------------------+
```

---

## 2. Component States

### 2.1 Save button (inside each `InsightCard`)

Replaces today's `SubscribeButton`. Same slot in the card footer, same
horizontal alignment. Icon: `Bell` from `lucide-react` (already used by
the existing `SubscribeButton`, confirmed via repo grep — no new
dependency).

| State | Icon | Label | Bg | Border | Text color | Tooltip | aria-pressed | Disabled |
|---|---|---|---|---|---|---|---|---|
| `unsaved` (default) | `Bell` outline, 14px, `tokens.color.text.caption` | `Save` | transparent | `tokens.color.border.default` | `tokens.color.text.muted` | "Save this insight" | `false` | no |
| `unsaved-hover` | `Bell` outline, `tokens.color.brand.primaryHover` | `Save` | `tokens.color.bg.surfaceAlt` | `tokens.color.brand.primary` | `tokens.color.text.body` | "Save this insight" | `false` | no |
| `saved` | `Bell` filled, 14px, `tokens.color.brand.primary` | `Saved` | `tokens.color.brand.tintDark` | `tokens.color.brand.primary` | `tokens.color.text.primary` | "Saved — click to remove" | `true` | no |
| `saved-hover` | `Bell` filled, `tokens.color.brand.primaryHover` | `Saved` | `tokens.color.brand.tintDark` | `tokens.color.brand.primaryHover` | `tokens.color.text.primary` | "Saved — click to remove" | `true` | no |
| `saving` (POST in flight, optimistic shows target state) | icon as target state | label as target state | as target state | as target state | as target state | "Saving…" | reflects target | yes (`opacity 0.6`) |
| `error-reverting` | icon snaps back to pre-click state | label snaps back | as pre-click state | as pre-click state | as pre-click state | "Save failed — try again" | as pre-click | briefly yes, then re-enabled when toast appears |

Filled vs outline: lucide-react's `Bell` is outline by default; the
filled state is rendered as the same `Bell` with `fill` set to
`tokens.color.brand.primary`. No new icon import needed.

Icon size: `14` (matches existing TabNav and `SubscribeButton` icon
sizes — confirmed in `frontend/src/components/tabs/CompaniesTab.tsx`
which imports `lucide-react` icons at this scale).

Label typography: `tokens.typography.caption` (12px / 400).

Button padding: `tokens.spacing.s1 tokens.spacing.s2` (4px 8px).
Gap between icon and label: `tokens.spacing.s1` (4px).
Border radius: `tokens.radius.md` (6px).

Transition: `tokens.motion.transitionColor` and
`tokens.motion.transitionBg` (color 0.15s, background 0.1s).

### 2.2 Past runs section header

Renders as a `<button>` spanning the section's full width.

| State | Chevron | Label | Count | Bg | Border |
|---|---|---|---|---|---|
| `collapsed-with-count` | right-pointing (0°) | `Past runs` `tokens.typography.subtitle` `tokens.color.text.body` | `(12)` in `tokens.color.text.caption` | transparent | bottom: `1px solid tokens.color.border.weak` |
| `collapsed-loading-count` | right-pointing | `Past runs` | `(…)` in `tokens.color.text.faint` | transparent | bottom: `1px solid tokens.color.border.weak` |
| `expanded` | rotated 90° down | `Past runs` `tokens.color.text.primary` | `(12)` in `tokens.color.text.caption` | `tokens.color.bg.surfaceAlt` | bottom: `1px solid tokens.color.border.default` |
| `empty` | right-pointing (disabled aesthetic) | `Past runs` `tokens.color.text.caption` | `(0)` in `tokens.color.text.faint` | transparent | bottom: `1px solid tokens.color.border.weak` |

Hover (any non-empty state): bg `tokens.color.bg.surfaceAlt`, label
shifts to `tokens.color.text.primary`.
Focus ring: `2px solid tokens.color.brand.primary`, offset 2px.
Header padding: `tokens.spacing.s3 tokens.spacing.s4` (12px 16px).

### 2.3 Past run row

| State | Visual |
|---|---|
| `default` | bg `tokens.color.bg.card`, border `1px solid tokens.color.border.weak`, radius `tokens.radius.md` |
| `hover` | bg `tokens.color.bg.surfaceAlt`, border `1px solid tokens.color.border.default`, cursor pointer |
| `expanded` | row sticks at top of its expansion; below it a region containing the session's `InsightCard`s; row border-bottom becomes `tokens.color.brand.primary` 2px to visually anchor |
| `loading` (insights fetch in flight) | row visible; below it three `InsightCard` skeletons in the same grid that `SnapshotInsightFeed` uses |
| `error` | row visible; below it an inline error block (see §6) |

Row left-to-right layout:

| Slot | Content | Token |
|---|---|---|
| Date | `Mon, May 12` (uses session `completed_at` UTC, rendered in user's locale) | `tokens.typography.body` `tokens.color.text.body` |
| Insight count badge | `5 insights` pill | `tokens.typography.caption` `tokens.color.brand.tintDark` bg, `tokens.color.brand.primary` border, `tokens.color.text.primary` text |
| Focus tag | e.g. `Hyperscalers` | `tokens.typography.caption` `tokens.color.bg.surfaceAlt` bg, `tokens.color.border.default` border, `tokens.color.text.muted` text |

Row padding: `tokens.spacing.s3 tokens.spacing.s4`.
Row vertical gap: `tokens.spacing.s2` (8px) between rows.

### 2.4 Saved insights section header

Identical state machine and visual spec as **2.2 Past runs header**,
with the label `Saved insights`. The count `(N)` is the total number
of currently-saved insights.

### 2.5 Saved insight row

A bare `InsightCard` — no additional row chrome. The card itself has
its own Save button (from §2.1), which when toggled off causes the row
to leave this list.

Removal animation (cheap path): `opacity 1 → 0` over 150ms with
`ease-out`, then DOM removal. Honors `prefers-reduced-motion: reduce`
by skipping the fade (instant removal).

---

## 3. Visual Specs

All values reference `tokens` from
`frontend/src/styles/insightTokens.ts` unless otherwise noted.

### 3.1 Typography map

| Element | Token |
|---|---|
| Section header label | `tokens.typography.subtitle` (14 / 500) |
| Section header count | `tokens.typography.caption` (12 / 400) |
| Past run row — date | `tokens.typography.body` (13 / 400) |
| Past run row — insight count badge | `tokens.typography.caption` (12 / 400) |
| Past run row — focus tag | `tokens.typography.caption` (12 / 400) |
| Save button label | `tokens.typography.caption` (12 / 400) |
| Empty-state body | `tokens.typography.body` |
| Inline error | `tokens.typography.caption` |

### 3.2 Spacing map

| Where | Token |
|---|---|
| Gap between SnapshotInsightFeed and PastRunsSection | `tokens.spacing.s7` (32) |
| Gap between PastRunsSection and SavedInsightsSection | `tokens.spacing.s7` (32) |
| Section header padding (vertical · horizontal) | `s3 · s4` (12 · 16) |
| Row padding | `s3 · s4` |
| Row-to-row gap | `s2` (8) |
| Expanded region top padding | `s4` (16) |
| Expanded region bottom padding | `s5` (20) |
| Save button padding | `s1 · s2` (4 · 8) |
| Save button icon → label gap | `s1` (4) |
| Skeleton row vertical gap | `s2` (8) |

### 3.3 Color map (default / hover / active)

| Element | Default | Hover | Active/Expanded |
|---|---|---|---|
| Section header bg | transparent | `bg.surfaceAlt` | `bg.surfaceAlt` |
| Section header label | `text.body` | `text.primary` | `text.primary` |
| Section header count | `text.caption` | `text.muted` | `text.muted` |
| Section header divider (bottom border) | `border.weak` | `border.default` | `border.default` |
| Past run row bg | `bg.card` | `bg.surfaceAlt` | `bg.surfaceAlt` |
| Past run row border | `border.weak` | `border.default` | `border.default` + bottom 2px `brand.primary` |
| Past run row text | `text.body` | `text.primary` | `text.primary` |
| Save button (unsaved) | `text.muted` on transparent | `text.body` on `bg.surfaceAlt`, border `brand.primary` | n/a |
| Save button (saved) | `text.primary` on `brand.tintDark`, border `brand.primary` | same bg, border `brand.primaryHover` | n/a |
| Inline error text | `semantic.danger` | — | — |
| Empty-state text | `text.caption` | — | — |

### 3.4 Icon sizes

- Chevron: 14px, color matches the header label's current state.
- Bell (Save button): 14px. Outline = lucide default. Filled = same
  `Bell` element with `fill` prop set to `tokens.color.brand.primary`.
- Both icons confirmed available without new imports — `Bell` and
  `ChevronDown` / `ChevronRight` are already imported in
  `CompaniesTab.tsx` and `SubscribeButton.tsx` respectively.

### 3.5 Chevron rotation

Use a single icon (`ChevronRight` from lucide-react) and rotate it
90° clockwise on expand:

```
collapsed:   transform: rotate(0deg);    // points right ▸
expanded:    transform: rotate(90deg);   // points down  ▾
transition:  transform 150ms ease-out;
```

Honor `prefers-reduced-motion: reduce` → set `transition: none`.

### 3.6 Radii and shadows

- Row radius: `tokens.radius.md` (6).
- Save button radius: `tokens.radius.md`.
- Expanded region radius: none (it flows below the row).
- No shadows on rows or section headers. (Existing app convention —
  shadow tokens are reserved for modals/popovers/FABs.)

---

## 4. Empty States

| Where | Copy | Visual |
|---|---|---|
| Past runs section, `N === 0` | `No past runs yet — kick off an AI session to see history here.` | Inside a 1px `tokens.color.border.weak` dashed bordered box, padding `tokens.spacing.s5 tokens.spacing.s4`, text `tokens.color.text.caption`. Header still renders with `(0)`; clicking it expands and reveals this box. |
| Saved insights section, `N === 0` | `No saved insights yet — tap the bell on any insight to save it.` | Same container as above. |

Empty states never include emojis and never include illustrations.

---

## 5. Loading States

### 5.1 Past runs — skeleton row

Used while the `/api/ai-insights/sessions` list is loading.

```
┌──────────────────────────────────────────────────────────────┐
│  ▓▓▓▓▓▓▓▓▓▓     ▓▓▓▓▓▓▓▓▓        ▓▓▓▓▓▓▓                     │
│  date shimmer   count shimmer    tag shimmer                 │
└──────────────────────────────────────────────────────────────┘
```

- Three skeleton rows by default.
- Skeleton fill uses `tokens.motion.skeletonGradient` with
  `tokens.motion.skeletonAnimation`.
- Row dimensions match a real row exactly so there is zero layout
  shift on resolve.

### 5.2 Past run row → expanded session insights — skeleton card

Same dimensions and grid as the cards in `SnapshotInsightFeed`. Three
card-shaped skeletons by default. Reuses the skeleton tokens above.

### 5.3 Save button — in-flight

- No spinner.
- The optimistic UI has already toggled the icon and label to the
  target state.
- Apply `opacity: 0.6` and `pointer-events: none` to the button until
  the request resolves (or 4s timeout, whichever comes first).
- On success: restore opacity to 1, re-enable.
- On error: revert state, restore opacity, show toast (§6).

### 5.4 Section header — count loading

Header shows `(…)` (literal ellipsis in parens), text color
`tokens.color.text.faint`. Replaced by `(N)` once the count resolves.

---

## 6. Error States

| Where | Copy | Visual |
|---|---|---|
| Save POST failure | `Couldn't save — try again.` | Toast, bottom-right, `tokens.color.semantic.danger` left border 3px, bg `tokens.color.bg.card`, padding `s3 s4`, auto-dismiss 4s. |
| Unsave DELETE failure | `Couldn't update — try again.` | Same toast pattern. |
| Past runs list load error | `Couldn't load past runs.` followed by a `Retry` text button | Inline block inside the expanded section. Container: `tokens.color.bg.card`, `1px solid tokens.color.semantic.danger`, `tokens.radius.md`, padding `s3 s4`. Retry button: text-only, `tokens.color.brand.primary`, hover `tokens.color.brand.primaryHover`. |
| Single session insights load error (inside an expanded past-run row) | `Couldn't load this session's insights.` + `Retry` | Same inline block, scoped to the expanded region only. |

Toast container uses `tokens.shadow.popover`.

---

## 7. Microcopy Table

Every user-facing string in this feature, ready to paste into an i18n
catalog. Sentence case throughout; no emojis.

| Key | String | Where |
|---|---|---|
| `save.label.unsaved` | `Save` | Save button label, unsaved |
| `save.label.saved` | `Saved` | Save button label, saved |
| `save.tooltip.unsaved` | `Save this insight` | Save button tooltip, unsaved |
| `save.tooltip.saved` | `Saved — click to remove` | Save button tooltip, saved |
| `save.tooltip.saving` | `Saving…` | Save button tooltip while POST/DELETE in flight |
| `save.toast.errorSave` | `Couldn't save — try again.` | Toast on POST failure |
| `save.toast.errorUnsave` | `Couldn't update — try again.` | Toast on DELETE failure |
| `pastRuns.header.label` | `Past runs` | Section header |
| `pastRuns.header.countPending` | `(…)` | Count placeholder while lazy-fetching |
| `pastRuns.empty` | `No past runs yet — kick off an AI session to see history here.` | Empty state body |
| `pastRuns.error.load` | `Couldn't load past runs.` | Inline error body |
| `pastRuns.error.retry` | `Retry` | Inline retry button |
| `pastRuns.row.insightCount` | `{N} insights` (use `1 insight` when N=1) | Insight count badge |
| `pastRuns.row.focusFallback` | `General` | Focus tag when session focus is null |
| `pastRuns.row.aria` | `Expand session from {date}` / `Collapse session from {date}` | aria-label on the row button |
| `pastRuns.sessionError` | `Couldn't load this session's insights.` | Inline error inside expanded row |
| `savedInsights.header.label` | `Saved insights` | Section header |
| `savedInsights.header.countPending` | `(…)` | Count placeholder |
| `savedInsights.empty` | `No saved insights yet — tap the bell on any insight to save it.` | Empty state body |
| `savedInsights.error.load` | `Couldn't load saved insights.` | Inline error body |
| `section.aria.expand` | `Expand {label}` | aria-label when collapsed |
| `section.aria.collapse` | `Collapse {label}` | aria-label when expanded |

---

## 8. Interaction Notes

### 8.1 Multi-expand vs single-expand inside Past runs

**Recommendation: allow multiple past-run rows to be expanded at once.**
Rationale:
- Less surprising — the user does not lose context when they open a
  second row.
- The insights for each session are cached after first fetch, so the
  cost of multiple expansions is negligible.
- It mirrors the OS-level mental model of a file tree.

### 8.2 Expand/collapse animation

- Duration: 150ms.
- Easing: `ease-out`.
- Property: `max-height` from `0` to `auto` (use a measured pixel
  height fallback for browsers without `interpolate-size: allow-keywords`).
- Honor `prefers-reduced-motion: reduce` → no transition; toggle is
  instant.
- Matches the existing pattern in `CompaniesTab.tsx` where
  `CompanyDetailPanel` opens via simple state flip without bespoke
  animation; we add the 150ms timing here because rows have header
  chrome that benefits from the cue.

### 8.3 Keyboard

| Element | Key | Action |
|---|---|---|
| Save button (`<button>`) | `Space` / `Enter` | Toggle saved state |
| Section header (`<button>`) | `Enter` / `Space` | Toggle expanded |
| Past run row (`<button>`) | `Enter` / `Space` | Toggle row expanded |
| `Retry` (inline error) | `Enter` / `Space` | Re-issue the failed fetch |
| Tab order | — | Save buttons appear inside each card in DOM order; section headers come after the last card of the snapshot feed; past run rows are tabbable only when their section is expanded |

### 8.4 Focus management

- Toggling a section open does not move focus — focus stays on the
  header so a keyboard user can collapse it again immediately.
- Toggling a past run row open does not move focus to the first
  insight; focus stays on the row.
- Save action: focus stays on the Save button. The `aria-pressed`
  value changes, which AT will announce.

### 8.5 Accessibility attributes

| Element | Attribute |
|---|---|
| Save button | `aria-pressed={saved}` , `aria-label` falls back to "Save this insight" / "Saved — click to remove" (only used when the visible label is hidden, e.g. icon-only future variant) |
| Section header | `aria-expanded={open}`, `aria-controls="{section-id}-region"` |
| Section region | `id="{section-id}-region"`, `role="region"`, `aria-labelledby="{section-id}-header"` |
| Past run row | `aria-expanded={open}`, `aria-controls="session-{id}-region"` |
| Toasts | `role="status"` (non-blocking) for success, `role="alert"` for the error toasts in §6 so they are announced immediately |
| Live region for count | The section header's count is wrapped in `aria-live="polite"` so the screen reader announces it when it resolves from `(…)` to `(N)` |

---

## 9. Out of Scope (Explicit)

- **No mobile / responsive polish.** Desktop only (≥1024px). No
  layout changes below that width; the sections will still render but
  are not stress-tested for narrow viewports.
- **No per-user view.** Bookmarks are global to this prototype
  instance. If two analysts use the tool, they see the same saved
  list. A future user model is its own design effort.
- **No bulk actions.** No "select all," no "unsave all," no
  multi-select within Saved insights or Past runs.
- **No sorting or filtering controls** inside Past runs beyond the
  default "newest first" order. No date pickers, no focus filters,
  no search box.
- **No editing of saved insights.** Bookmark is binary (saved /
  unsaved); no notes, no tags, no folders.
- **No deep-linking** to a specific past run or saved insight via URL
  hash. The sections always open collapsed on page load.
- **No drag-to-reorder** in either list.
- **No keyboard shortcut** to save (e.g. `S`). Buttons only.

---

## 10. ASCII Wireframes

### 10.1 Whole tab — both new sections collapsed

```
+================================================================================+
| AI Insights                                                          [pillar]  |
+================================================================================+
|                                                                                |
|  Latest snapshot — 2026-05-13 09:02 UTC · focus: Hyperscalers · 5 insights     |
|  ┌──────────────────────────┐  ┌──────────────────────────┐                    |
|  | InsightCard A            |  | InsightCard B            |                    |
|  | …                        |  | …                        |                    |
|  | [○ Bell] Save            |  | [● Bell] Saved           |                    |
|  └──────────────────────────┘  └──────────────────────────┘                    |
|  ┌──────────────────────────┐  ┌──────────────────────────┐                    |
|  | InsightCard C            |  | InsightCard D            |                    |
|  | [○ Bell] Save            |  | [○ Bell] Save            |                    |
|  └──────────────────────────┘  └──────────────────────────┘                    |
|  ┌──────────────────────────┐                                                  |
|  | InsightCard E            |                                                  |
|  | [○ Bell] Save            |                                                  |
|  └──────────────────────────┘                                                  |
|                                                                                |
|  ── 32px gap ────────────────────────────────────────────────────              |
|                                                                                |
|  ▸  Past runs (12)                                                             |
|  ───────────────────────────────────────────────────────────────────           |
|                                                                                |
|  ── 32px gap ────────────────────────────────────────────────────              |
|                                                                                |
|  ▸  Saved insights (4)                                                         |
|  ───────────────────────────────────────────────────────────────────           |
|                                                                                |
+================================================================================+
```

### 10.2 Past runs section expanded with one row also expanded (3 InsightCards)

```
+================================================================================+
|                                                                                |
|  ▾  Past runs (12)                                                             |
|  ═══════════════════════════════════════════════════════════════════           |
|                                                                                |
|  ┌──────────────────────────────────────────────────────────────────────────┐  |
|  | ▾  Mon, May 12        [5 insights]                  [Hyperscalers]      |  |
|  └──────────────────────────────────────────────────────────────────────────┘  |
|     └─── expanded session region ──────────────────────────────────────────    |
|     ┌──────────────────────────┐  ┌──────────────────────────┐                 |
|     | InsightCard              |  | InsightCard              |                 |
|     | [○ Bell] Save            |  | [● Bell] Saved           |                 |
|     └──────────────────────────┘  └──────────────────────────┘                 |
|     ┌──────────────────────────┐                                               |
|     | InsightCard              |                                               |
|     | [○ Bell] Save            |                                               |
|     └──────────────────────────┘                                               |
|                                                                                |
|  ┌──────────────────────────────────────────────────────────────────────────┐  |
|  | ▸  Sun, May 11        [4 insights]                  [Power constraints] |  |
|  └──────────────────────────────────────────────────────────────────────────┘  |
|  ┌──────────────────────────────────────────────────────────────────────────┐  |
|  | ▸  Sat, May 10        [6 insights]                  [Neo-clouds]        |  |
|  └──────────────────────────────────────────────────────────────────────────┘  |
|  ┌──────────────────────────────────────────────────────────────────────────┐  |
|  | ▸  Fri, May 9         [5 insights]                  [General]           |  |
|  └──────────────────────────────────────────────────────────────────────────┘  |
|                                                                                |
|  ... ( 8 more rows ) ...                                                       |
|                                                                                |
+================================================================================+
```

### 10.3 Saved insights section expanded with 4 InsightCards

```
+================================================================================+
|                                                                                |
|  ▾  Saved insights (4)                                                         |
|  ═══════════════════════════════════════════════════════════════════           |
|                                                                                |
|  ┌──────────────────────────┐  ┌──────────────────────────┐                    |
|  | InsightCard              |  | InsightCard              |                    |
|  | (saved from May 12 run)  |  | (saved from May 10 run)  |                    |
|  | …                        |  | …                        |                    |
|  | [● Bell] Saved           |  | [● Bell] Saved           |                    |
|  └──────────────────────────┘  └──────────────────────────┘                    |
|                                                                                |
|  ┌──────────────────────────┐  ┌──────────────────────────┐                    |
|  | InsightCard              |  | InsightCard              |                    |
|  | (saved from May 7 run)   |  | (saved from May 3 run)   |                    |
|  | …                        |  | …                        |                    |
|  | [● Bell] Saved           |  | [● Bell] Saved           |                    |
|  └──────────────────────────┘  └──────────────────────────┘                    |
|                                                                                |
+================================================================================+
```

When a user clicks the filled bell on any saved card in §10.3, that
card fades out over 150ms (or instantly under reduced-motion) and the
grid reflows. The header count drops from `(4)` to `(3)` and that
transition is announced via the polite live region on the count.

---

## 11. Proposed New Tokens

None. Every value above maps to an existing entry in
`tokens` (`color`, `radius`, `spacing`, `typography`, `shadow`,
`motion`). If implementation discovers a gap, file it back into
`DESIGN_TOKENS_AUDIT.md` rather than inlining a literal.

---

## 12. Implementation Handoff Notes (non-binding)

- The Save button replaces `SubscribeButton`. Delete the
  "V3 — coming soon" toast at that site as part of the same change.
- Use the existing `InsightCard` component verbatim in both new
  sections — do not fork it.
- The grid that `SnapshotInsightFeed` uses for its card layout should
  be extracted to a thin shared layout primitive so all three
  surfaces (snapshot, expanded past run, saved list) align pixel-wise.
- `useApi` should back the past-runs list fetch and the per-session
  insights fetch; results are cached for the lifetime of the tab
  mount so re-expanding a row is free.
- Lazy-fetch the past-runs count on first mount so the header can
  render `(N)` quickly even before the user expands the section.
