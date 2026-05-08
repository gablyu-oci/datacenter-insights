# AI Insights v2 — "Tracked Questions" Sidebar Design Spec

**Status:** Draft  ·  **Date:** 2026-05-07  ·  **Owner:** Product Design
**Phase:** D (frontend cutover) of the AI Insights v2 redesign
**Scope:** UI/UX spec for the right-rail sidebar that surfaces the agent's open-questions journal in the AI Insights tab.

This spec is implementation-ready. It defers to the existing visual language (`insightTokens`, `InsightCard.tsx`, `SnapshotInsightFeed.tsx`) and prescribes only what is new.

References:
- Backend route: `GET /api/insights/open-questions` (parses `.openclaw/workspace/MEMORY.md`; see `ai_insights_v2_spec.md` §4.4)
- Journal mechanics: `ai_insights_v2_spec.md` §4.3 (OpenClaw native memory, `category="open_questions"`)
- Existing parent: `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx`
- Token source of truth: `frontend/src/styles/insightTokens.ts` (`tokens.color`, `tokens.typography`, `tokens.spacing`, `tokens.radius`)

---

## 1. User Flow

### 1.1 Primary flow — durable awareness

```
User opens AI Insights tab
  └─ Sidebar mounts on right rail (default-open on >=xl)
       ├─ Hook fires GET /api/insights/open-questions
       ├─ Skeleton (3 cards) shows for <=300ms
       └─ List paints, sorted by status > materiality > recency
            ├─ User scans header pills (status counts)
            ├─ User clicks a card -> expands to full latest_note
            └─ Polling pings every 30s; pulsing dot appears during fetch

User starts a Run-again session in the main feed
  └─ Sidebar continues polling; new entries appear after dreaming sweep
       (entries promoted to MEMORY.md may take until next nightly pass)
       └─ Sidebar tooltip clarifies: "Updated nightly via memory consolidation."
```

### 1.2 Secondary flow — manual refresh

```
User suspects a fresh entry exists (e.g. just finished a session)
  └─ Clicks Refresh icon in sidebar header
       ├─ Hook bypasses 30s timer, fires immediately
       ├─ Pulsing dot animates during request
       └─ List re-renders; if unchanged, no visible motion
```

### 1.3 Mobile / narrow flow

```
User on <xl viewport
  └─ Sidebar is collapsed by default
       └─ Tab header shows a "Tracked questions ({n})" pill button
            └─ Click -> full-width drawer slides in from right
                 ├─ Backdrop (rgba(0,0,0,0.4))
                 ├─ Esc / backdrop click / X button closes
                 └─ aria-modal="true", focus trapped inside drawer
```

### 1.4 Empty / error / cold-start flow

```
First load, no MEMORY.md or no open_questions section
  └─ Empty state copy: "No tracked questions yet -- they appear after the agent's first session."
       └─ No CTA (the user does not own creation here)

Network / 5xx
  └─ Inline error banner inside the sidebar card list area:
       "Couldn't load tracked questions. [Retry]"
       └─ Retry triggers same fetch as manual refresh
```

---

## 2. Layout & Placement

### 2.1 Position in `AIInsightsTab.tsx`

The tab body becomes a 2-column CSS grid at `>=xl` (1280px):

```
xl+ layout (default-open sidebar)
+--------------------------------------------------------+--------------+
| <main column: SessionRunner / SnapshotInsightFeed>     | <sidebar>    |
|   max-width: 880px                                     |  width: 340  |
|   flex: 1 1 auto                                       |  sticky      |
+--------------------------------------------------------+--------------+

<xl layout (drawer)
+-----------------------------------------------------------------------+
| <main column>                                                          |
|   The "Tracked questions ({n})" pill in the tab header opens the      |
|   drawer over the page.                                                |
+-----------------------------------------------------------------------+
```

- **Insertion point:** sibling-right of the existing main column wrapper inside `AIInsightsTab.tsx`, after `<SessionRunner />` / `<SnapshotInsightFeed />`. The current single-column layout is wrapped in a new flex/grid container.
- **Width:** `340px` (token: `--sidebar-width`). Range guidance: 320–360px; pick 340 for parity with `InsightCard` spacing.
- **Gap:** `s.s6` (24px) between main column and sidebar.
- **Sticky:** sidebar root uses `position: sticky; top: <tab-header-height + s.s4>;` so it stays in view as the main feed scrolls. Internal list scrolls if its content overflows `calc(100vh - top - s.s4)`.
- **Internal scroll:** sidebar root is a flex column. Header is `flex: 0 0 auto`, list area is `flex: 1 1 auto; overflow-y: auto; overscroll-behavior: contain`.
- **Default-open breakpoint:**
  - `>=xl` (1280px): default-open, persistent in the layout.
  - `<xl`: default-closed; drawer trigger lives in the tab header.
  - State persisted in `localStorage` under key `ai-insights-sidebar-open` (boolean). Default true on `>=xl`, false on `<xl`.

### 2.2 Collapse-to-rail (xl+) — optional secondary state

When the user toggles the sidebar closed at `>=xl`, the sidebar collapses to a 40px-wide vertical rail showing only:

- The Refresh icon (top)
- A vertical "Tracked questions" rotated label
- A pip count badge

Click anywhere on the rail re-expands. This state is persisted alongside the open/closed boolean.

### 2.3 Mobile drawer

- Trigger: `<button>` rendered in the AIInsightsTab header row (next to "Run again"). Label: `Tracked questions` with a count badge `({n})`. Button is **only rendered at `<xl`**.
- Drawer specs:
  - `position: fixed; right: 0; top: 0; bottom: 0; width: min(420px, 92vw);`
  - `transform: translateX(100%)` -> `translateX(0)` on open; transition `200ms ease-out`.
  - Backdrop: full-screen `rgba(0,0,0,0.4)`, fades in 150ms.
  - Close affordances: top-right X button, Esc key, backdrop click.
  - `role="dialog" aria-modal="true" aria-labelledby="tq-drawer-title"`.
  - Focus trap: focus moves to the close button on open; restored to the trigger on close.

---

## 3. Wireframes (ASCII)

### 3.1 Default-open sidebar (xl+)

```
+----------------------------------------------------+
| Tracked questions       [.] [refresh]   [<]        |  <- header (44px tall)
| 7 watching . 2 confirmed . 1 stale . 3 disproved   |  <- summary line
+----------------------------------------------------+
| +------------------------------------------------+ |
| | q_crusoe-wy-uncontracted        [WATCHING]     | |  <- card
| | 720MW Wyoming, 360MW construction, no          | |
| | offtaker -- watch for 8-K naming hyperscaler   | |
| | (*) high                              3d ago   | |
| +------------------------------------------------+ |
| +------------------------------------------------+ |
| | q_msft-az-phase3                [CONFIRMED]    | |
| | 2026-05-06: 10-Q confirms 480MW phase 3        | |
| | (*) medium                            6h ago   | |
| +------------------------------------------------+ |
| +------------------------------------------------+ |
| | q_qts-virginia-rampdown         [DISPROVED]    | |
| | originally flagged 2026-05-02; permit data     | |
| | shows expected pause not cancellation          | |
| | (*) low                              12d ago   | |
| +------------------------------------------------+ |
| ...                                                |
+----------------------------------------------------+
```

Legend:
- `[.]` = polling pulse dot (visible only while a fetch is in flight).
- `[refresh]` = manual refresh button (lucide `RefreshCw`).
- `[<]` = collapse-to-rail toggle (lucide `ChevronRight` rotated; on `<xl` this becomes the close X for the drawer).
- `(*)` = materiality dot (red / amber / slate per §6.3).

### 3.2 Card expanded state (Enter / Space / click)

```
+------------------------------------------------+
| q_crusoe-wy-uncontracted        [WATCHING]     |
| 720MW Wyoming, 360MW construction, no          |
| offtaker -- watch for 8-K naming hyperscaler.  |
| Latest evidence note (2026-05-07): +120MW      |
| DC-2 stage=construction; still no offtaker     |
| in EDGAR.                                      |
| (*) high                              3d ago   |
+------------------------------------------------+
```

Expanded shows the full `latest_note` (no 2-line clamp), padded the same.

### 3.3 Collapsed-to-rail state (xl+, sidebar closed)

```
+-----+
| [R] |   <- refresh button
|     |
| T   |
| r   |   <- "Tracked questions" rotated 90deg
| a   |
| c   |
| k   |
| e   |
| d   |
|     |
| (7) |   <- total open count badge
|     |
| [>] |   <- expand toggle
+-----+
  40px
```

### 3.4 Mobile drawer

```
+---------------------------- (backdrop) -------+
|                                               |
|             [main feed dimmed]                |
|                                               +-------------------+
|                                               | Tracked questions |
|                                               |   [.] [refresh][X]|
|                                               +-------------------+
|                                               | 7w . 2c . 1s . 3d |
|                                               +-------------------+
|                                               | +---------------+ |
|                                               | | q_crusoe...   | |
|                                               | | ...           | |
|                                               | +---------------+ |
|                                               | ...               |
|                                               +-------------------+
```

### 3.5 Loading / error / empty states

```
LOADING (skeletons)               ERROR                          EMPTY
+--------------------------+      +--------------------------+   +--------------------------+
| ##########  ####         |      | Couldn't load tracked    |   |                          |
| ################         |      | questions.               |   |   (icon: search)         |
| #####             ###    |      |                          |   |                          |
+--------------------------+      | [Retry]                  |   |   No tracked questions   |
+--------------------------+      +--------------------------+   |   yet -- they appear     |
| ##########  ####         |                                     |   after the agent's      |
| ################         |                                     |   first session.         |
| #####             ###    |                                     |                          |
+--------------------------+                                     +--------------------------+
+--------------------------+
| ##########  ####         |
| ################         |
| #####             ###    |
+--------------------------+
```

---

## 4. Component Specs

### 4.1 `TrackedQuestionsSidebar.tsx` (root)

**Role:** owns layout, polling lifecycle, header, list render, and state machine (loading / error / empty / data).

**Composition:**

```
<aside aria-labelledby="tq-title" role="complementary">
  <header>
    <h2 id="tq-title">Tracked questions</h2>
    <PollingDot active={isFetching} />
    <button aria-label="Refresh tracked questions"><RefreshCw/></button>
    <button aria-label="Collapse sidebar"><ChevronRight/></button>
  </header>

  <p role="status" aria-live="polite">
    {countsByStatus rendered as inline summary}
  </p>

  <ul aria-live="polite" aria-busy={isLoading}>
    {state === "loading" -> <SkeletonList count={3} />}
    {state === "error"   -> <InlineError onRetry={refetch} />}
    {state === "empty"   -> <EmptyState />}
    {state === "ready"   -> sortedQuestions.map(q => <TrackedQuestionCard q={q} />)}
  </ul>
</aside>
```

**Container styles:**

| Property | Value |
|---|---|
| `width` | `340px` (open) / `40px` (collapsed rail) |
| `background` | `c.bg.card` |
| `border` | `1px solid c.border.default` |
| `borderRadius` | `r.xl` |
| `padding` | `s.s4` (header + list); list items get `s.s3` between |
| `gap` | `s.s3` between header / summary / list |
| `display` | `flex; flex-direction: column` |
| `position` | `sticky` (xl+) / `fixed` (mobile drawer) |

**Header heights:** 44px target. Refresh + collapse buttons are 32x32 ghost icon buttons (no fill, hover -> `c.bg.surface`).

### 4.2 `TrackedQuestionCard.tsx`

**Role:** render one question row.

**Layout:** vertical stack inside a single rounded card.

```
+---------------- card (border-radius: r.lg, padding: s.s3) ----------------+
| header: id (mono, ellipsis)            <gap: auto>      <StatusPill>      |
| body:   latest_note (2 lines clamp; expand on click)                      |
| footer: (dot) materiality label                <gap: auto>   3d ago       |
+---------------------------------------------------------------------------+
```

**Tokens:**

| Element | Token |
|---|---|
| Background | `c.bg.card` |
| Border | `1px solid c.border.default` |
| Border-radius | `r.lg` |
| Padding | `s.s3` |
| Gap between rows | `s.s2` (8px) |
| ID font | `t.mono.fontFamily`, `t.meta.fontSize`, color `c.text.muted` |
| Body font | `t.body.fontSize`, color `c.text.body`, line-height 1.4 |
| Body clamp | `display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;` |
| Footer font | `t.meta.fontSize`, color `c.text.caption` |

**Header right-aligns the StatusPill.** ID is left, with `text-overflow: ellipsis` and `min-width: 0` so the pill never wraps.

**Click behavior:** the entire card is a `<button>` (or `<div role="button" tabIndex={0}>` if button styling is too heavy). Click / Enter / Space toggles `expanded` local state. When `expanded`, line clamp is removed.

**Hover:** `border-color: c.border.strong; background: c.bg.surface;` transition 120ms.
**Focus-visible:** `outline: 2px solid c.brand.primary; outline-offset: 2px;`.
**Active:** `transform: translateY(0)` (no shift) but background deepens to `c.bg.surfaceMuted`.

### 4.3 `StatusPill.tsx`

**Role:** reusable badge for the four statuses. Used in the card header, in the count summary (with a number prepended), and conceivably elsewhere.

**Props:**

```ts
interface StatusPillProps {
  status: "watching" | "confirmed" | "disproved" | "stale";
  /** Optional leading number (e.g. "7") to make a count chip. */
  count?: number;
  size?: "sm" | "md";  // default "sm"
}
```

**Size sm:** height 20px, padding 0 8px, font `t.meta.fontSize`, mono.
**Size md:** height 24px, padding 0 10px, font `t.body.fontSize`.
**Border-radius:** `r.full` (pill).
**Label:** uppercase status text. Always rendered (color is never the only signal — see §8 a11y).

### 4.4 `useOpenQuestionsPolling.ts` (hook)

**Role:** owns network lifecycle.

**Returns:**

```ts
interface UseOpenQuestionsPollingResult {
  data: OpenQuestion[] | null;
  isLoading: boolean;       // first-load only
  isFetching: boolean;      // any in-flight fetch (drives the pulse)
  error: Error | null;
  refetch: () => void;      // manual refresh
  lastFetchedAt: Date | null;
}
```

**Behavior:**

- Mounts: kick a fetch immediately. `isLoading=true` only on the first.
- Sets a 30,000ms `setInterval`; each tick triggers `refetch` if `document.visibilityState === "visible"`.
- Listens for `visibilitychange`. When tab returns to visible after >=30s away, fire a fetch immediately, then resume interval.
- AbortController on unmount and on each new fetch (cancels the previous in-flight request).
- Keeps the prior `data` in place during a refetch (no flicker).
- Error policy: a failed refetch sets `error` but does not clear `data`. The UI shows an error banner *plus* the stale list, with a `lastFetchedAt` timestamp tooltip on the polling dot.

---

## 5. Component API Contracts (TypeScript)

```ts
// shared with backend
export type OpenQuestionStatus = "watching" | "confirmed" | "disproved" | "stale";
export type OpenQuestionMateriality = "low" | "medium" | "high";

export interface OpenQuestion {
  id: string;             // e.g. "q_crusoe-wy-uncontracted"
  status: OpenQuestionStatus;
  materiality: OpenQuestionMateriality;
  latest_note: string;
  last_seen_iso: string;  // ISO8601
}

// TrackedQuestionsSidebar.tsx
export interface TrackedQuestionsSidebarProps {
  /** Controlled-open mode for the AIInsightsTab parent. If omitted, the sidebar
   *  manages its own open/closed state via localStorage. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** When true, renders as a fixed-position drawer instead of a sticky rail. */
  variant?: "rail" | "drawer";
  /** Override for testing — injects a custom hook result. */
  __testHookResult?: UseOpenQuestionsPollingResult;
}

// TrackedQuestionCard.tsx
export interface TrackedQuestionCardProps {
  question: OpenQuestion;
  /** Defaults to false; parent may pass true to start expanded (e.g. deep link). */
  defaultExpanded?: boolean;
  /** Called on click/keypress; parent may use to log analytics. */
  onSelect?: (id: string) => void;
}

// StatusPill.tsx
export interface StatusPillProps {
  status: OpenQuestionStatus;
  count?: number;
  size?: "sm" | "md";
  className?: string;
}

// useOpenQuestionsPolling.ts
export interface UseOpenQuestionsPollingOptions {
  /** Override poll interval (ms). Default 30_000. */
  intervalMs?: number;
  /** Override base URL (defaults to import.meta.env.VITE_API_BASE_URL || ""). */
  baseUrl?: string;
  /** Disable polling entirely (still allows manual refetch). */
  enabled?: boolean;
}

export interface UseOpenQuestionsPollingResult {
  data: OpenQuestion[] | null;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  refetch: () => void;
  lastFetchedAt: Date | null;
}

export function useOpenQuestionsPolling(
  opts?: UseOpenQuestionsPollingOptions,
): UseOpenQuestionsPollingResult;
```

**Endpoint contract** (consumed, not defined here):

```
GET /api/insights/open-questions
  -> 200 OpenQuestion[]
  -> 5xx { detail: string }
```

The hook treats a 200 with `[]` as the empty state, **not** an error.

---

## 6. Design Tokens

All tokens below either reuse `insightTokens` (preferred) or are documented additions. New additions are scoped to this sidebar and named with a `tq-` prefix; they are conventional Tailwind classes per the user's mandate in §3.

### 6.1 Spacing & radius (from `insightTokens`)

| Use | Token |
|---|---|
| Sidebar outer padding | `s.s4` (16px) |
| Card internal padding | `s.s3` (12px) |
| Card vertical gap (in list) | `s.s3` (12px) |
| Header to summary gap | `s.s2` (8px) |
| Sidebar border-radius | `r.xl` |
| Card border-radius | `r.lg` |
| Pill border-radius | `r.full` |

### 6.2 Typography

| Use | Token |
|---|---|
| Sidebar title `Tracked questions` | `t.title` (downshift one step if it clashes — `fontSize: 14px; fontWeight: 600`) |
| Card ID | `t.mono` family + `t.meta.fontSize` |
| Card body | `t.body.fontSize` |
| Card footer (relative time, materiality label) | `t.meta.fontSize` |
| Status pill label | `t.mono.fontFamily`, `t.meta.fontSize`, `letter-spacing: 0.04em`, uppercase |

### 6.3 Status palette — exact mappings (Tailwind classes)

These map 1:1 to the user's spec. Implementation MUST use these exact classes (or a CSS-in-JS equivalent reading from the same hex values).

| Status | Tailwind |
|---|---|
| `watching` | `text-blue-700 bg-blue-50 border-blue-200` |
| `confirmed` | `text-emerald-700 bg-emerald-50 border-emerald-200` |
| `disproved` | `text-slate-600 bg-slate-100 border-slate-200` |
| `stale` | `text-amber-700 bg-amber-50 border-amber-200` |

Border-width is `1px` for all four. Pill text is uppercase, mono.

### 6.4 Materiality dot

A 8x8 circle rendered before the materiality text label. Color only — text is the source of truth.

| Materiality | Dot color |
|---|---|
| `high` | `bg-red-500` (Tailwind `#EF4444`) |
| `medium` | `bg-amber-500` (Tailwind `#F59E0B`) |
| `low` | `bg-slate-400` (Tailwind `#94A3B8`) |

Rendered as `<span aria-hidden="true" className="inline-block w-2 h-2 rounded-full bg-{color} mr-1.5" />` followed by the lowercase label `high` / `medium` / `low`.

### 6.5 Polling pulse dot

| Property | Value |
|---|---|
| Size | 8x8 |
| Color (idle, no recent fetch) | not rendered |
| Color (fetching) | `c.brand.primary` |
| Animation | `pulse` keyframes (2s, ease-in-out, infinite); reduced-motion -> static dot at 60% opacity |
| Position | inline before the title or in the header right cluster |

### 6.6 Skeleton

| Property | Value |
|---|---|
| Block bg | `c.bg.surface` |
| Highlight bg | `c.bg.surfaceMuted` (or `rgba(0,0,0,0.04)` if not in tokens) |
| Animation | shimmer keyframes (1.5s linear infinite); reduced-motion -> static |
| Card height | matches collapsed card height (~84px) |

---

## 7. Interaction States

### 7.1 Sidebar header

| State | Visual |
|---|---|
| Idle | Title, count summary, refresh icon, collapse icon. |
| Polling (fetch in flight) | Pulse dot visible to left of refresh icon. Refresh icon stays clickable. |
| Manual refresh pressed | Refresh icon rotates 360deg over 600ms (`@keyframes spin`) once, then stops. Reduced-motion -> no rotation, brief 150ms opacity dip to 0.5. |
| Refresh hover | Background `c.bg.surface`. |
| Refresh focus-visible | Outline `2px solid c.brand.primary`, offset 2px. |
| Refresh disabled | Only while a fetch is in flight from a previous click — opacity 0.5, cursor not-allowed; prevents double-fire. |

### 7.2 Card

| State | Visual |
|---|---|
| Default | Border `c.border.default`, bg `c.bg.card`. |
| Hover | Border `c.border.strong`, bg `c.bg.surface`. Cursor pointer. |
| Focus-visible | Outline `2px solid c.brand.primary`, offset 2px (replaces hover border). |
| Active (mousedown) | bg `c.bg.surfaceMuted`. |
| Expanded | Body line-clamp removed; chevron-down icon flips to chevron-up at the right end of the footer. |
| Updated since last poll | Background flashes `c.brand.tintDark` for 800ms, then fades back. (Detected by id+last_seen_iso diff between poll cycles.) Reduced-motion -> small "updated" dot at top-right for 4s, no fade. |

### 7.3 Status pill

| State | Visual |
|---|---|
| Default | Per §6.3 mapping. |
| In count summary | Same colors, `count` prefix, comma-separated by status (only shown when count>0). |

### 7.4 Refresh / collapse buttons

Standard ghost icon buttons:

- 32x32 hit target
- 16x16 icon
- Default: `color: c.text.muted; background: transparent`
- Hover: `background: c.bg.surface`
- Focus-visible: outline as above
- Disabled: opacity 0.5

### 7.5 Inline error

```
+-------------------------------------------+
| (!) Couldn't load tracked questions.      |
| {reason if available, max 1 line}         |
| [Retry]                                   |
+-------------------------------------------+
```

- Border: `1px solid c.semantic.warning`
- Background: `c.semantic.warningTint` (or `rgba(245, 158, 11, 0.08)` if not in tokens)
- Retry button: secondary style, height 28px, label `Retry`. Clicking calls `refetch()`.

### 7.6 Empty state

- Icon: lucide `Inbox` or `MessageCircleQuestion`, 24x24, color `c.text.faint`.
- Heading: `No tracked questions yet`
- Subcopy: `They appear after the agent's first session.`
- Centered, vertical stack, padding `s.s5`. No CTA.

### 7.7 Drawer (mobile)

| State | Visual |
|---|---|
| Closed | Drawer off-screen (`translateX(100%)`). Trigger button visible in tab header. |
| Opening | 200ms `ease-out` translateX to 0; backdrop fades to `rgba(0,0,0,0.4)` over 150ms. |
| Open | Focus trapped; Esc / X / backdrop click closes. |
| Closing | Reverse of opening (200ms / 150ms). Focus restored to trigger. |

---

## 8. Accessibility Notes

- **Landmarks.** Root is `<aside role="complementary" aria-labelledby="tq-title">`. Title `<h2 id="tq-title">Tracked questions</h2>`.
- **Live regions.**
  - List `<ul>` carries `aria-live="polite" aria-busy={isLoading}`. New / changed cards announce as they arrive.
  - The count summary line carries `role="status"` so the screen reader hears e.g. "7 watching, 2 confirmed" on first paint.
  - Polling itself is silent (no announcement on each 30s tick) — only meaningful list changes are surfaced via the live region's mutation.
- **Color is never the only signal.**
  - Status pill always renders text (`WATCHING`, `CONFIRMED`, `DISPROVED`, `STALE`).
  - Materiality dot is paired with the literal text `high` / `medium` / `low`.
  - Updated-since-last-poll flash is paired with a (visually-hidden) text update in the live region: e.g. "q_crusoe-wy-uncontracted updated".
- **Keyboard.**
  - TAB order: refresh button -> collapse button -> first card -> ... -> last card.
  - Cards: `Enter` and `Space` toggle expanded. `Tab` to leave.
  - Drawer: focus trap with `Tab` / `Shift+Tab`; `Esc` closes.
  - Visible focus ring (outline `2px solid c.brand.primary`, offset 2px) on every interactive element.
- **Reduced motion.** All animations gated on `@media (prefers-reduced-motion: reduce)`:
  - Pulse dot becomes static at 60% opacity.
  - Refresh icon does not spin.
  - Drawer slide becomes an instant show/hide (still uses opacity 0 -> 1 over 80ms for backdrop only).
  - Card update flash becomes a 4s dot indicator instead of a fading background.
- **Hit targets.** All buttons >=32x32. Card hit area covers the full card.
- **Text size.** No copy below 12px (`t.meta.fontSize`). ID column uses mono at 12px for scan parity with `InsightCard` provenance footer.
- **Contrast.** All four status palettes pass WCAG AA on `bg-card` (verified pairs: `text-blue-700 on bg-blue-50` >= 7:1, `text-emerald-700 on bg-emerald-50` >= 7:1, `text-slate-600 on bg-slate-100` >= 5:1, `text-amber-700 on bg-amber-50` >= 5:1).
- **Drawer dialog semantics.** `role="dialog" aria-modal="true" aria-labelledby="tq-drawer-title"`. The title `<h2>` inside is the labelledby target.
- **Skeletons.** Marked `aria-hidden="true"`; the `aria-busy="true"` on the `<ul>` does the announcing.
- **Error banner.** `role="alert"` so it announces immediately when it appears. The Retry button has an explicit `aria-label="Retry loading tracked questions"`.

---

## 9. Sorting & Grouping

### 9.1 Default sort (no UI to change it in V2)

Multi-key sort, all in a single `Array.prototype.sort` comparator:

1. **Status order:** `watching` (0) -> `confirmed` (1) -> `stale` (2) -> `disproved` (3).
2. **Materiality order:** `high` (0) -> `medium` (1) -> `low` (2).
3. **Recency:** `last_seen_iso` desc (newest first).

```ts
const STATUS_RANK: Record<OpenQuestionStatus, number> = {
  watching: 0, confirmed: 1, stale: 2, disproved: 3,
};
const MATERIALITY_RANK: Record<OpenQuestionMateriality, number> = {
  high: 0, medium: 1, low: 2,
};

function compareQuestions(a: OpenQuestion, b: OpenQuestion): number {
  const s = STATUS_RANK[a.status] - STATUS_RANK[b.status];
  if (s !== 0) return s;
  const m = MATERIALITY_RANK[a.materiality] - MATERIALITY_RANK[b.materiality];
  if (m !== 0) return m;
  return Date.parse(b.last_seen_iso) - Date.parse(a.last_seen_iso);
}
```

### 9.2 Grouping

**No visible group separators in V2.** The sort itself produces visually-clustered status bands (all watching cards appear contiguously, etc.). Adding labelled section headers is a V3 ask.

### 9.3 No filter UI in V2

No status filter, no materiality filter, no search box. Lean. The count summary in the header doubles as a quick read of the distribution.

---

## 10. Polling

### 10.1 Mechanics

- Interval: **30 seconds**.
- Driver: `setInterval` started on mount, cleared on unmount.
- First fetch: fired immediately on mount (does not wait 30s).
- AbortController cancels any in-flight request when a new one starts (prevents stale data overwrite if a slow request finishes after a fast one).

### 10.2 Visibility-aware

```ts
useEffect(() => {
  function onVisibility() {
    if (document.visibilityState !== "visible") {
      // pause: clear interval; do nothing else.
      clearInterval(timerRef.current);
      timerRef.current = null;
    } else {
      // resume: fire one fetch immediately, then restart interval.
      refetch();
      timerRef.current = setInterval(refetch, 30_000);
    }
  }
  document.addEventListener("visibilitychange", onVisibility);
  return () => document.removeEventListener("visibilitychange", onVisibility);
}, [refetch]);
```

### 10.3 Manual refresh

- Button in the header (`RefreshCw` icon).
- Click -> `refetch()` immediately; resets the interval timer to "now + 30s".
- Disabled while `isFetching` to prevent double-fire.

### 10.4 Backoff on persistent error

- After 3 consecutive failed fetches, the interval stretches to 60s, then 120s. Any successful fetch resets to 30s. (Soft, opt-in nice-to-have; not a blocker for V2.)

### 10.5 What does NOT trigger a poll

- New session start in the main feed: the journal entry is not promoted to MEMORY.md until OpenClaw's nightly dreaming pass. The sidebar should NOT artificially refetch on session-finalize, because there is nothing yet to read. Tooltip on the polling dot (or refresh icon) clarifies: `"Updated nightly via memory consolidation."`

---

## 11. Content / Copy Guidelines

| Surface | Copy |
|---|---|
| Title | `Tracked questions` |
| Drawer trigger label | `Tracked questions ({n})` |
| Status labels (pill) | `WATCHING` / `CONFIRMED` / `DISPROVED` / `STALE` (uppercase) |
| Materiality labels (footer) | `high` / `medium` / `low` (lowercase) |
| Empty heading | `No tracked questions yet` |
| Empty subcopy | `They appear after the agent's first session.` |
| Error heading | `Couldn't load tracked questions.` |
| Error retry | `Retry` |
| Refresh button aria | `Refresh tracked questions` |
| Collapse button aria | `Collapse tracked questions sidebar` (or `Expand` when collapsed) |
| Polling dot tooltip | `Updated nightly via memory consolidation. Last fetched {relative time}.` |
| Card date format | Relative: `<60s -> "just now"`, `<60m -> "{n}m ago"`, `<24h -> "{n}h ago"`, `<30d -> "{n}d ago"`, otherwise ISO date `YYYY-MM-DD`. |

Voice: terse, factual, lowercase where conventional. No emojis. Mirror the tone of `InsightCard` provenance footer.

---

## 12. File Structure

```
frontend/src/components/tabs/ai-insights/tracked-questions/
  TrackedQuestionsSidebar.tsx     <- root
  TrackedQuestionCard.tsx         <- per-question card
  StatusPill.tsx                  <- shared pill
  EmptyState.tsx                  <- empty (or reuse the existing ai-insights/EmptyState if shape fits)
  InlineError.tsx                 <- local to this folder
  SkeletonList.tsx                <- 3 placeholder cards
  PollingDot.tsx                  <- pulsing dot
  index.ts                        <- barrel export

frontend/src/hooks/
  useOpenQuestionsPolling.ts      <- polling hook
```

Parent integration touches only:

- `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx` — wraps the existing main column in a flex/grid container and mounts `<TrackedQuestionsSidebar />`. Adds the mobile drawer trigger button to the tab header.

---

## 13. Out of Scope (for V2 / Phase D)

- Filter UI by status / materiality.
- Search within tracked questions.
- Deep-linking from a question card to the originating insight (the journal entry does not currently store the insight id; revisit if persist_insight starts emitting `open_question_id` consistently).
- Manual mutation from the sidebar (mark as confirmed/disproved/stale by the user). The journal is agent-owned in V2.
- Full timeline view of a question's history across sessions. V2 shows only `latest_note`.
- Cross-tab sync via BroadcastChannel.

---

## 14. Acceptance Checklist (for the implementing engineer)

- [ ] Sidebar mounts on `>=xl` screens by default-open; renders as drawer on `<xl`.
- [ ] Width 340px; sticky; scrolls internally when content overflows viewport.
- [ ] Polls `GET /api/insights/open-questions` on a 30s interval; pauses when tab hidden.
- [ ] Manual refresh button forces an immediate fetch and resets interval.
- [ ] Sort order matches §9.1 exactly (status -> materiality -> recency desc).
- [ ] Status pill colors match §6.3 Tailwind classes verbatim.
- [ ] Materiality dot colors match §6.4 (red / amber / slate).
- [ ] Card body clamps to 2 lines; expands on click / Enter / Space.
- [ ] Loading skeleton is 3 placeholder cards; visible only on first load.
- [ ] Error banner has `role="alert"` and a Retry button; does not clear stale data.
- [ ] Empty state copy matches §11 exactly.
- [ ] List has `aria-live="polite" aria-busy={isLoading}`.
- [ ] All interactive elements have visible focus rings and aria labels.
- [ ] Reduced-motion variants honored on pulse, spin, drawer slide, update flash.
- [ ] localStorage key `ai-insights-sidebar-open` persists open/closed state.
- [ ] Keyboard: TAB through cards; Enter/Space expands; Esc closes drawer.
- [ ] Contrast checked on all four status palettes against `bg-card`.

---

**End of spec.**
