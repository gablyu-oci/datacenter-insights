# UX Spec: Earnings Calls Tab + CompanyDetailPanel Section

**Status:** Approved for implementation
**Owner:** Product Design
**Engineering plan:** `/home/ubuntu/.claude/plans/i-want-to-include-dynamic-summit.md` (Parts 3.2 – 3.4)
**PRD:** `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/prd/earnings_transcripts.md`
**Last updated:** 2026-05-12

This spec is implementation-oriented. A frontend engineer should be able
to build the tab and the CompanyDetailPanel section without making
visual/UX decisions. Where a decision is left intentionally open, it is
marked **OPEN**.

---

## 1. Information Architecture

### TabNav placement
- New tab is appended to the `AFTER_SUPPLIER` array in
  `frontend/src/components/layout/TabNav.tsx`.
- It sits **after** `sources` is **wrong** — re-read: per plan Part 3.3,
  append to `AFTER_SUPPLIER`. Final order in that array:
  1. `permits` (Country Permits)
  2. `companies` (Companies)
  3. `triangulation` (Triangulation, MOCK)
  4. `sources` (Data Sources)
  5. **`earnings` (Earnings Calls, NEW, real)**

  Note: if product later prefers the tab to read before `triangulation`
  for visual grouping with `companies`, that is a one-line move; the
  baseline placement for v1 is "last in the array" per the plan.

### Tab entry
```ts
{ id: "earnings", label: "Earnings Calls", icon: Mic, real: true }
```
- Icon: `Mic` from `lucide-react`, rendered at `size={14}` to match the
  other tab icons.
- `real: true` so no MOCK badge appears.

### App routing
`frontend/src/App.tsx` `TAB_CONFIG` gets:
```ts
earnings: { component: EarningsTab, pillar: "Earnings Transcripts" }
```
`TabWrapper` consumes `pillar` for the page-level header.

### Cross-tab navigation
- A click on a company name or ticker badge inside an EarningsTab card
  does **not** deep-link to the Companies tab in v1 (out of scope).
- A click on a row inside `CompanyDetailPanel > Earnings Calls` opens
  the same expanded modal that EarningsTab uses (the modal component is
  shared — see Section 4).

---

## 2. User Flow

### Primary flow: scan recent calls
1. User clicks **Earnings Calls** in TabNav.
2. EarningsTab loads with default state: `call_date DESC`, no filters,
   page 1 (20 cards).
3. User scans sentiment badges across the grid to spot bullish/cautious
   calls of the week.
4. User clicks a card → expanded modal opens with structured highlights.
5. User reads quotes, optionally clicks `transcript_url` for the full
   source, then closes the modal (Esc, backdrop click, or close button)
   → returns to the same scroll position in the feed.

### Secondary flow: company-specific brief
1. User goes to **Companies** tab, opens a company.
2. In `CompanyDetailPanel`, scrolls past Filings to **Earnings Calls**.
3. Sees timeline rows (newest first).
4. Clicks a row → same expanded modal opens (Section 4).

### Filter flow
1. User selects 2 companies in the multi-select.
2. Selects `2026Q1` in the quarter dropdown.
3. Toggles sentiment axis to `AI demand: bullish`.
4. Feed re-fetches with `?ticker=NVDA,MSFT&quarter=2026Q1&sentiment_axis=ai_demand&sentiment=bullish`.
5. User clicks **Clear filters** → returns to default view.

---

## 3. EarningsTab Wireframe (desktop ≥ 1024px)

```
+----------------------------------------------------------------------+
| TabWrapper header  (pillar: "Earnings Transcripts")                  |
+----------------------------------------------------------------------+
| HEADER BANNER  (gradient #0a1628 → #0f2240, same as CompaniesTab)    |
|  [Mic 16px #3b82f6]  Earnings Calls  [N calls tracked badge]         |
+----------------------------------------------------------------------+
| FILTER BAR  (sticky-top within the tab pane, background #1e293b)     |
|  ┌──────────────────────┐ ┌──────────────┐ ┌─────────────────────┐  |
|  │ Companies (multi)  ▾ │ │ Quarter   ▾  │ │ Sentiment axis    ▾ │  |
|  │ NVDA · MSFT · GOOGL  │ │ 2026Q1       │ │ AI demand : bullish │  |
|  └──────────────────────┘ └──────────────┘ └─────────────────────┘  |
|                                                  [Clear filters]    |
+----------------------------------------------------------------------+
| FEED  (3-column CSS grid, gap 16px)                                  |
|                                                                      |
|  +------------------+  +------------------+  +------------------+   |
|  |  [NVDA] NVIDIA   |  |  [MSFT] Microsft |  |  [GOOGL] Alphabet|   |
|  |  Q1 FY26 · 5/21  |  |  Q3 FY26 · 4/24  |  |  Q1 FY26 · 4/29  |   |
|  |                  |  |                  |  |                  |   |
|  |  AI: ●bullish    |  |  AI: ●bullish    |  |  AI: ●cautious   |   |
|  |  PWR:●cautious   |  |  PWR:●bearish    |  |  PWR:●bullish    |   |
|  |  CAPX:●bullish   |  |  CAPX:●bullish   |  |  CAPX:●bullish   |   |
|  |                  |  |                  |  |                  |   |
|  |  "Demand for     |  |  "We are power-  |  |  "Capex steps up |   |
|  |  Blackwell is    |  |  constrained in  |  |  meaningfully in |   |
|  |  insane..."      |  |  multiple..."    |  |  the back half." |   |
|  |                  |  |                  |  |                  |   |
|  |  --- citation -- |  |  --- citation -- |  |  --- citation -- |   |
|  |  Alpha Vantage   |  |  Alpha Vantage   |  |  Alpha Vantage   |   |
|  |  Retrieved 5/22  |  |  Retrieved 4/25  |  |  Retrieved 4/30  |   |
|  +------------------+  +------------------+  +------------------+   |
|                                                                      |
|  ... up to 20 cards per page ...                                     |
|                                                                      |
|                     [ Load more  (page 2 of N) ]                     |
+----------------------------------------------------------------------+
```

### Responsive breakpoints
| Width | Columns | Filter bar |
|---|---|---|
| ≥ 1280 | 3 | Inline single row |
| 768–1279 | 2 | Inline, may wrap |
| < 768 | 1 | Stacked vertically; quarter + sentiment collapse into a single "Filters ▾" toggle |

Implementation note: use CSS `grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))` with `gap: 16px`. This gives 1/2/3 columns organically without explicit media queries beyond the filter-bar collapse.

### Empty / loading / error states (tab-level)

**Loading (initial fetch):**
```
+----------------------------------------------------------------------+
|                                                                      |
|                       Loading earnings calls…                        |
|                       (color #3b82f6, 14px)                          |
|                                                                      |
+----------------------------------------------------------------------+
```
Match `function Loader()` pattern from CompaniesTab.

**Empty (zero transcripts after filters):**
```
+----------------------------------------------------------------------+
|   ┌──────────────────────────────────────────────────────────────┐  |
|   |  [Mic 24px #64748b]                                          |  |
|   |  No earnings calls match these filters.                      |  |
|   |  Try widening the quarter range or clearing the company      |  |
|   |  multi-select.                                               |  |
|   |                                          [ Clear filters ]   |  |
|   └──────────────────────────────────────────────────────────────┘  |
+----------------------------------------------------------------------+
```
Container: `CARD_STYLE` with `textAlign: center`, `padding: 60px 20px`,
muted icon (`#64748b`).

**Empty (zero transcripts overall — first run, no data yet):**
Replace the second sentence with: "The earnings adapter runs daily at
06:45 UTC and writes new transcripts within ~48h of a call."

**Error (API failure):**
Use `<ErrorPanel>` exactly like CompaniesTab does on line 476.

---

## 4. Card + Expanded Modal Specs

### 4.1 Card (feed item)

Structure (top to bottom):

```
┌─────────────────────────────────────────────────────┐  ← onClick opens modal
│ [NVDA]  NVIDIA Corp                           [Q1]  │  row 1: header
│ Wed, May 21 2026                                    │  row 2: call date
│                                                     │
│ AI demand     ● Bullish                             │  row 3a: sentiment
│ Power         ● Cautious                            │  row 3b
│ DC capex      ● Bullish                             │  row 3c
│                                                     │
│ "Demand for our Blackwell platform is insane —      │  row 4: top quote
│  we expect significant ramp through FY26."          │     (≤140 chars + …)
│   — Jensen Huang, CEO                               │  row 5: speaker
│                                                     │
│ ─────────────────────────────────────────────────── │  divider
│ Source: Alpha Vantage  ·  Retrieved 2026-05-22      │  CitationFooter
└─────────────────────────────────────────────────────┘
```

Component-level details:

- **Container:** `CARD_STYLE` from CompaniesTab (`background:#1e293b`,
  `border:1px solid #334155`, `borderRadius:12px`, `padding:20px`).
  Adds `cursor:pointer` and an `onMouseOver`/`onMouseOut` background
  shift to `#22304a` (matches the filings-row hover in CompanyDetailPanel).
- **Ticker badge:** small chip, `padding:1px 7px`, `borderRadius:4px`,
  `fontSize:10px`, `fontWeight:600`, `background:#0f172a`,
  `border:1px solid #1d4ed8`, `color:#60a5fa`. Same shape as the
  "N companies tracked" pill in CompaniesTab's header banner.
- **Company name:** `color:white`, `fontSize:14px`, `fontWeight:600`.
  Truncate with `text-overflow:ellipsis` if it overflows.
- **Quarter chip:** same chip style as ticker badge but
  `color:#94a3b8`, `border:1px solid #334155`. Placed right-aligned.
- **Call date:** `color:#94a3b8`, `fontSize:11px`. Format
  `"EEE, MMM d yyyy"` — implement with `Intl.DateTimeFormat("en-US",
  {weekday:"short", month:"short", day:"numeric", year:"numeric"})`.
- **Sentiment row (3 of them):** label is left-aligned, dot + value
  right-aligned. See Section 5 for the badge spec.
- **Top quote:** `color:#cbd5e1`, `fontSize:12px`, `lineHeight:1.5`,
  `fontStyle:italic`. Hard truncate at 140 chars at the API level
  (backend already returns a `top_quote` field per PRD). If client must
  truncate, use `text.length > 140 ? text.slice(0,137).trimEnd() + "…" : text`.
- **Speaker attribution:** `color:#64748b`, `fontSize:11px`,
  `marginTop:6px`, prefixed by an em dash (`— `).
- **CitationFooter:** reuse `<CitationFooter sources={["Alpha Vantage"]}
  retrievedAt={card.retrieved_at} sourceUrl={card.transcript_url} />`.
  Confidence intentionally omitted (the LLM-extraction confidence is a
  per-mention attribute, not a card-level one).

### 4.2 Expanded modal

Triggered by card click (and by row click in CompanyDetailPanel).
Component name: `<EarningsTranscriptModal transcriptId={id} onClose={…} />`.

Structure follows CompanyDetailPanel's modal in CompaniesTab almost
exactly (same wrapper, same overlay, same close-button position).

```
+======================================================================+
||  [NVDA] NVIDIA Corp · Q1 FY26 · Wed May 21 2026             [ × ]  ||
||  AI:●Bullish  PWR:●Cautious  CAPX:●Bullish  Overall:●Bullish       ||
+======================================================================+
||                                                                    ||
||  ── GUIDANCE ──────────────────────────────────────────────────    ||
||  Revenue growth      +Strong sequential acceleration through FY26  ||
||  Capex outlook       Q2 datacenter capex steps up materially       ||
||  ┌──────────────────────────────────────────────────────────────┐  ||
||  │ "We expect Q2 revenue of approximately $28 billion, plus or  │  ||
||  │  minus 2 percent, with continued sequential growth driven by │  ||
||  │  Blackwell ramp."                                            │  ||
||  │   — Colette Kress, CFO  ·  prepared_remarks                  │  ||
||  └──────────────────────────────────────────────────────────────┘  ||
||                                                                    ||
||  ── CAPEX MENTIONS  (4) ───────────────────────────────────────    ||
||  $25B  ─ datacenter buildout for FY26                              ||
||  ┌──────────────────────────────────────────────────────────────┐  ||
||  │ "Our top customers are pulling forward capex…"               │  ||
||  │   — Jensen Huang, CEO  ·  q_and_a                            │  ||
||  └──────────────────────────────────────────────────────────────┘  ||
||  ... more capex entries ...                                        ||
||                                                                    ||
||  ── AI & POWER  (7) ───────────────────────────────────────────    ||
||  [AI]   "Demand for inference is structurally larger than..."      ||
||         — Jensen Huang, CEO  ·  prepared_remarks                   ||
||  [PWR]  "Grid interconnect timelines remain the binding..."        ||
||         — Colette Kress, CFO  ·  q_and_a                           ||
||  ...                                                               ||
||                                                                    ||
||  ── COMPETITIVE  (2) ──────────────────────────────────────────    ||
||  vs AMD       cautious   "We respect AMD but our software moat..." ||
||  vs Custom    bullish    "Hyperscaler ASICs are complementary..."  ||
||                                                                    ||
||  ── MW CAPACITY  (3) ──────────────────────────────────────────    ||
||  800 MW  ·  Phoenix AZ  ·  "...announced 800 megawatts in AZ..."   ||
||  ...                                                               ||
||                                                                    ||
||  ── Footer ────────────────────────────────────────────────────    ||
||  [ Open full transcript on Alpha Vantage ↗ ]                       ||
||  Retrieved 2026-05-22 · Extractor v1.0.0 · Speakers 7 · Words 9821 ||
+======================================================================+
```

#### Modal container
- Reuse the exact JSX pattern from `CompanyDetailPanel`
  (`frontend/src/components/tabs/CompaniesTab.tsx` lines 136–161):
  fixed overlay, `rgba(0,0,0,0.75)` + `backdropFilter:blur(3px)`,
  `padding:24px`, click-on-backdrop closes.
- Inner panel: `background:#0f172a`, `border:1px solid #334155`,
  `borderTop:3px solid #3b82f6`, `borderRadius:14px`,
  `maxWidth:760px` (slightly wider than the 700px company modal because
  quote blocks need horizontal room), `maxHeight:85vh`, two-region
  flex with a scrolling body.

#### Header (sticky)
- Row 1: ticker badge + company name + quarter chip + call date,
  same atoms as the card header. Close button (`X` from lucide,
  size 14, top-right).
- Row 2: 4 sentiment badges horizontally (AI / Power / DC capex /
  Overall). The 4th badge — `Overall` — appears only in the modal,
  not on the feed card.

#### Section anatomy
Every section follows the same pattern:

1. **Section label** — uppercase, `fontSize:11px`, `fontWeight:600`,
   `letterSpacing:0.05em`, `color:#94a3b8`, `marginBottom:10px`. Mirror
   line 238 of CompaniesTab. Append `(N)` count if N > 1.
2. **Optional summary row** (Guidance only) — 2-column key/value list,
   key in `#64748b` 11px, value in `#cbd5e1` 12px.
3. **Quote blocks** — each is a `<blockquote>`-styled card:
   - `background:#0f172a`, `border:1px solid #1e293b`,
     `borderLeft:3px solid #3b82f6`, `borderRadius:6px`,
     `padding:10px 14px`, `margin:6px 0`.
   - Quote text: `fontFamily:"ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"`,
     `fontSize:12px`, `lineHeight:1.55`, `color:#e2e8f0`.
   - Attribution line below quote: `color:#64748b`, `fontSize:11px`,
     `marginTop:6px`. Format: `— {speaker} · {section}` where
     `section` ∈ `prepared_remarks | q_and_a`. If `speaker` is null,
     render `— (speaker unknown)`.

#### Section-specific layouts

- **Guidance:** summary key/value row (revenue_growth, capex_outlook)
  + a single `raw_quote` block. If `raw_quote` is null, render only
  the summary rows.
- **Capex mentions:** each entry shows `[dollar_amount]` as a green
  chip (`background:#052e16`, `border:1px solid #16a34a`,
  `color:#4ade80`, same as the public/private chip in CompaniesTab)
  + a short `context` string + the quote block.
- **AI & Power mentions:** each entry leads with a small theme chip
  (`[AI]` / `[DC]` / `[PWR]` / `[GRID]` color-coded — see Section 5)
  + quote block.
- **Competitive mentions:** each entry is one row with
  `mentioned_company` (link-styled, but not actually linked in v1),
  a sentiment badge (bullish/cautious/bearish), and the quote block.
- **MW capacity mentions:** each entry shows `{mw_value} MW · {location}`
  in white 14px, then the quote block.

#### Sections hidden when empty
If an array field is empty in the API response, hide the entire section
(do not render an empty header). Per PRD US-3 AC.

#### Modal footer
- Link `Open full transcript on Alpha Vantage ↗` — `color:#3b82f6`,
  `fontWeight:600`, opens `transcript_url` in a new tab (`target=_blank
  rel=noreferrer`). Disabled (gray, no underline, no href) when
  `transcript_url` is null; show a tooltip "Transcript URL not
  available for this call".
- Meta line: `Retrieved {date} · Extractor v{version} · Speakers {n}
  · Words {n}`. `color:#64748b`, `fontSize:11px`.

#### Modal loading & error
- **Loading body:** `color:#3b82f6`, centered "Loading transcript…",
  `padding:40px 0`. The shell (header + close button) renders
  immediately from data already passed via props (ticker, company,
  quarter, call_date, three sentiments) so the user has visual
  continuity. Only the detailed sections are deferred.
- **Error body:** inline `<ErrorPanel variant="inline" />` with
  retry that re-calls `/api/earnings/{transcript_id}`.

---

## 5. Design Tokens

### 5.1 Surface palette (matches existing app)
| Token | Value | Used for |
|---|---|---|
| `--bg-app` | `#0f172a` | tab pane, modal background |
| `--bg-card` | `#1e293b` | card surface |
| `--bg-card-hover` | `#22304a` | card hover |
| `--bg-quote` | `#0f172a` | quote block background |
| `--border-default` | `#334155` | card / panel border |
| `--border-quiet` | `#1e293b` | divider lines |
| `--accent-blue` | `#3b82f6` | primary accent, active tab, quote bar |
| `--accent-blue-soft` | `#60a5fa` | links and ticker badge text |

### 5.2 Sentiment color tokens
| Sentiment | Dot / accent | Background pill | Border pill | Text on pill |
|---|---|---|---|---|
| `bullish` | `#16a34a` | `#052e16` | `#16a34a` | `#4ade80` |
| `cautious` | `#f59e0b` | `#1c1409` | `#f59e0b` | `#fbbf24` |
| `bearish` | `#dc2626` | `#2a0a0a` | `#dc2626` | `#f87171` |
| `not_mentioned` | `#64748b` | `#0f172a` | `#334155` | `#94a3b8` |

(Bullish background/border re-use the public/private green from
CompaniesTab line 207 for cross-app consistency.)

### 5.3 Theme chips for AI & Power mentions
| Theme | Background | Border | Text |
|---|---|---|---|
| `AI` | `#1e1b4b` | `#6366f1` | `#a5b4fc` |
| `datacenter` (DC) | `#0c1a3d` | `#3b82f6` | `#93c5fd` |
| `power` (PWR) | `#1c1917` | `#f59e0b` | `#fbbf24` |
| `grid` | `#1a1410` | `#dc2626` | `#fca5a5` |

### 5.4 Typography
| Use | Family | Size | Weight | Color |
|---|---|---|---|---|
| Card company name | inherit (system sans) | 14px | 600 | `#ffffff` |
| Card call date | inherit | 11px | 400 | `#94a3b8` |
| Card top quote | inherit, italic | 12px | 400 | `#cbd5e1` |
| Section label (modal) | inherit, uppercase | 11px | 600 | `#94a3b8` |
| Quote text | monospace stack | 12px | 400 | `#e2e8f0` |
| Modal meta line | inherit | 11px | 400 | `#64748b` |

Use `letterSpacing:0.05em` on uppercase section labels (matches
CompaniesTab convention).

### 5.5 Spacing scale
Use existing app conventions: `4 · 6 · 8 · 10 · 12 · 14 · 16 · 20 · 24`.
Card padding `20px`, modal padding `16px 20px`, section gap `20px`
between sections in the modal, quote-block vertical margin `6px`.

### 5.6 Shadows
| Token | Value |
|---|---|
| Modal | `0 24px 80px rgba(0,0,0,0.6)` (matches CompanyDetailPanel) |
| Card hover (optional) | none — only background shift |

### 5.7 Radii
- Cards: `12px`
- Chips / badges: `4px`
- Quote blocks: `6px`
- Modal: `14px`

---

## 6. Sentiment Badge Component

Reusable: `<SentimentBadge axis="ai_demand" value="bullish" size="sm" />`.

### Variants
- `size="sm"` — used in cards. Renders dot + value as compact pill.
  Dot diameter 6px. Pill: `padding:1px 7px`, `borderRadius:4px`,
  `fontSize:10px`, `fontWeight:600`, `textTransform:uppercase`,
  `letterSpacing:0.04em`.
- `size="md"` — used in modal header. Same atoms scaled to
  `padding:3px 10px`, `fontSize:11px`. Dot 8px.

### ASCII
```
sm:   ● BULLISH        (green dot, dark-green pill, light-green text)
md:   AI demand  ● BULLISH
```

### Implementation
```ts
const SENTIMENT_TOKENS = {
  bullish:        { dot: "#16a34a", bg: "#052e16", border: "#16a34a", text: "#4ade80", label: "Bullish" },
  cautious:       { dot: "#f59e0b", bg: "#1c1409", border: "#f59e0b", text: "#fbbf24", label: "Cautious" },
  bearish:        { dot: "#dc2626", bg: "#2a0a0a", border: "#dc2626", text: "#f87171", label: "Bearish" },
  not_mentioned:  { dot: "#64748b", bg: "#0f172a", border: "#334155", text: "#94a3b8", label: "Not mentioned" },
} as const;

const AXIS_LABEL = {
  ai_demand: "AI demand",
  power_constraints: "Power",
  datacenter_capex: "DC capex",
  overall: "Overall",
} as const;
```

The card uses the value-only form. Modal header uses the labelled form
on a single row, separated by `12px` gaps.

---

## 7. Filter Bar Spec

### 7.1 Company multi-select
- Controlled component, source from `/api/companies/?page_size=200`
  filtered to `public_private === "public"`. Initial set is empty.
- Visual: chip-input. Selected companies render as removable chips
  using the ticker; unselected are picked from a dropdown popup.
- Dropdown items show `{ticker} · {canonical_name}` with the ticker
  in `#60a5fa` and the name in `#94a3b8`. Filter-as-you-type on either
  field.
- Max display chips inline: 3. Beyond that show `+N more`.
- Container styling: `background:#1e293b`, `border:1px solid #334155`,
  `borderRadius:8px`, `padding:6px 10px`, `minWidth:280px`.

### 7.2 Quarter dropdown
- Native `<select>` styled to match. Options:
  - `All quarters` (default, value `""`)
  - Last 8 quarters dynamically computed, newest first
    (`2026Q1`, `2025Q4`, `2025Q3`, …). Format display as `Q1 2026`.
- Width 140px.

### 7.3 Sentiment-axis toggle
- Two-control compound:
  - Axis select: `Overall (default) | AI demand | Power | DC capex`.
  - Value select: `Any (default) | Bullish | Cautious | Bearish |
    Not mentioned`.
- When axis is `Overall` and value is `Any`, no sentiment filter is sent.
- Layout: inline pair separated by a thin divider; total width ~280px.

### 7.4 Clear filters
- Plain text button, `color:#94a3b8` default, `#60a5fa` hover,
  `fontSize:12px`. Only shows when at least one filter is non-default.

### 7.5 URL/state behaviour
- v1 stores filter state in React component state only (no URL sync).
- Adding shareable URL params is **OPEN** for v2.

---

## 8. CompanyDetailPanel — Earnings Calls Section

Added as a fourth section in `CompanyDetailPanel`
(`frontend/src/components/tabs/CompaniesTab.tsx`), positioned **after
Recent Filings** and **before Sites by State**.

### 8.1 Section header
```
[Mic 11px #94a3b8]  EARNINGS CALLS (N)
```
Identical structure to the "Recent Filings" header on line 296.

### 8.2 Timeline rows
Each row: a single horizontally laid-out button.

```
┌─────────────────────────────────────────────────────────────────┐
│ 2026-05-21 │ Q1 FY26 │ ● Bullish │ "Blackwell ramp accelerates…"│
│   date     │ quarter │  overall  │  guidance.raw_quote (≤72ch)  │
└─────────────────────────────────────────────────────────────────┘
```

Atoms:
- **Date column** — fixed `minWidth:84px`, `color:#cbd5e1`,
  `fontWeight:600`, `fontSize:11px`. Below it in `#64748b 10px`:
  `Earnings call`.
- **Quarter chip** — same chip atom as the EarningsTab card.
- **Overall sentiment badge** — `SentimentBadge size="sm" axis="overall"`.
- **Headline** — 1-line truncate. Source: `guidance.raw_quote` if
  present, else the first `ai_power_mention.quote`, else the literal
  string "(no extracted highlights yet)". Color `#94a3b8`,
  `fontSize:11px`, `lineHeight:1.4`, `whiteSpace:nowrap`,
  `overflow:hidden`, `textOverflow:ellipsis`.
- Row container styling: identical to the filings-row anchor on
  CompaniesTab lines 311–325 (same background, hover, padding).
- Click handler: opens `<EarningsTranscriptModal>` (shared component
  from Section 4) with the row's `transcript_id`.

### 8.3 Section states
- **Loading:** "Loading earnings calls…" centered, `color:#3b82f6`,
  `padding:20px 0`, `fontSize:12px`.
- **Empty:** placeholder card mirroring the filings-empty block at
  CompaniesTab lines 301–304:
  > "No earnings transcripts ingested for this company yet. The Alpha
  > Vantage adapter refreshes daily off the earnings calendar."
- **Error:** inline `<ErrorPanel variant="inline" />`.

### 8.4 Cap and pagination
- Show up to the most recent **8** transcripts inline.
- If `total > 8`, append a small footer line:
  `Showing 8 of {total} calls` styled like CompaniesTab line 432.

---

## 9. Interaction States

### 9.1 Card
| State | Visual |
|---|---|
| Default | `background:#1e293b`, `border:1px solid #334155` |
| Hover | `background:#22304a`, cursor pointer |
| Focus (keyboard) | Outline `2px solid #3b82f6` with `outline-offset:2px` |
| Pressed | brief `transform:scale(0.99)` `transition:transform 80ms` (optional polish) |

Cards must be reachable by keyboard. Render them as
`<button type="button" aria-haspopup="dialog" aria-label="Open {company} {quarter} earnings call details">`.

### 9.2 Filter bar
| Control | Default | Focus | Disabled |
|---|---|---|---|
| Multi-select | border `#334155` | border `#3b82f6` | opacity 0.5 |
| Select | border `#334155` | border `#3b82f6` | opacity 0.5 |
| Clear filters | hidden when inactive | underline on focus | n/a |

### 9.3 Modal
| State | Behaviour |
|---|---|
| Open | Trap focus inside modal; first focusable is the close button |
| Backdrop click | Close |
| Escape | Close |
| External link click | Opens in new tab, modal stays open |
| Body scroll lock | Set `document.body.style.overflow = "hidden"` on open, restore on close (matches existing modal behavior) |

### 9.4 Sentiment badges
- Static, non-interactive (no hover, no focus ring).
- `aria-label` matches the spoken form: `AI demand sentiment: bullish`.

---

## 10. Content / Copy Guidelines

- Use sentence case for all labels and tooltips. Title case is reserved
  for product nouns ("Earnings Calls", "Alpha Vantage").
- Quarter format displayed to the user: `Q1 2026` (display) — the API
  format is `2026Q1` (preserve for URLs and identifiers).
- Speaker attribution: always `— {speaker_name}` (em dash + space).
  When the speaker string lacks a role, render verbatim. Do not invent
  roles.
- Empty-state copy is plain and explains the mechanism (refresh cadence)
  so analysts know it's not a bug.
- Never use emojis in any visible label or copy.
- Sentiment values displayed as `Bullish | Cautious | Bearish | Not mentioned`.
- Date formats:
  - Card / modal header: `Wed, May 21 2026`
  - Timeline (compact): `2026-05-21`
  - CitationFooter: `2026-05-22` (handled by CitationFooter — it splits
    on `T`).

---

## 11. Accessibility Notes

### 11.1 Semantics
- EarningsTab content root: `<main aria-label="Earnings calls feed">`.
- Filter bar: `<form role="search" aria-label="Filter earnings calls">`.
  Each control has a visible `<label>` or `aria-label`.
- Cards: rendered as `<button type="button">`. Each carries
  `aria-haspopup="dialog"` and a descriptive `aria-label`
  (`"Open NVIDIA Q1 2026 earnings call details"`).
- Modal: `<div role="dialog" aria-modal="true" aria-labelledby="…">`,
  where the labelledby points to the modal header element.

### 11.2 Sentiment badges (color-independence)
- Each badge has `aria-label="{axis} sentiment: {value}"`. The colored
  dot has `aria-hidden="true"` so screen readers don't read it.
- Color is reinforced by the text label (`Bullish` / `Cautious` /
  `Bearish` / `Not mentioned`) — required because color contrast
  alone cannot communicate sentiment to color-blind users.

### 11.3 Keyboard navigation
- Tab order in feed: filter bar → first card → … → last card →
  Load more.
- Within filter bar: Tab into multi-select; Arrow keys cycle options;
  Backspace removes the last chip; Esc closes the dropdown.
- Card → Enter or Space opens modal.
- Modal: Tab cycles forward through focusable elements; Shift+Tab
  cycles back; focus is trapped (cannot Tab out of the modal).
- Modal close shortcuts: Esc, click on backdrop, click on close button.
  Esc must work regardless of which element inside the modal is focused.
- After modal closes, focus returns to the card/row that opened it.

### 11.4 Contrast targets
- Body text on `#1e293b` background must be at least `#94a3b8` (passes
  WCAG AA for 12px regular).
- Sentiment pill text on its background must be at least 4.5:1. The
  tokens in Section 5.2 are verified — keep them in sync if anyone
  proposes lighter pill backgrounds.

### 11.5 Reduced motion
- Honor `prefers-reduced-motion: reduce`:
  - Disable the optional pressed-scale on cards.
  - Disable the `transform:rotate` on dropdown chevrons.
  - Modal still opens/closes instantly (already no animation).

### 11.6 Live regions
- When the feed updates after a filter change, the count badge
  ("N calls tracked") should sit inside an `aria-live="polite"` region
  so screen readers announce the new result count.

---

## 12. Implementation Checklist (for the frontend agent)

In order, with no expected backtracking:

1. Create `frontend/src/components/shared/SentimentBadge.tsx`
   (see Section 6). Export `SENTIMENT_TOKENS` and `AXIS_LABEL` as
   named exports so other components can reuse them.
2. Create `frontend/src/components/tabs/earnings/EarningsCard.tsx`
   (one card; props: full transcript summary from
   `/api/earnings`; `onOpen(id)` callback).
3. Create `frontend/src/components/tabs/earnings/EarningsFilterBar.tsx`
   with the three controls and a `Clear filters` button. Lifts state
   up via `onChange({ tickers, quarter, axis, value })`.
4. Create `frontend/src/components/tabs/earnings/EarningsTranscriptModal.tsx`
   — the shared modal. Takes `transcriptId` and fetches
   `/api/earnings/{id}` internally with `useApi`. This component is
   imported by both EarningsTab and CompanyDetailPanel.
5. Create `frontend/src/components/tabs/EarningsTab.tsx` wiring the
   above three together. Reuse `TabWrapper`, `ErrorPanel`,
   `CitationFooter`, `useApi`.
6. Update `frontend/src/components/layout/TabNav.tsx` to append the
   new entry (Section 1).
7. Update `frontend/src/App.tsx` `TAB_CONFIG` to register the tab.
8. Update `frontend/src/components/tabs/CompaniesTab.tsx`
   `CompanyDetailPanel` to add the new section (Section 8) using the
   shared modal.

---

## 13. Open Questions

- **OPEN-1:** Should sentiment-axis filtering allow multi-select on
  the value side (e.g., `Bullish OR Cautious`)? V1 single-select keeps
  the URL contract tight; revisit after 30 days of usage.
- **OPEN-2:** Should clicking a `mentioned_company` chip in the
  Competitive section deep-link to that company's detail panel?
  Out of scope for v1.
- **OPEN-3:** Do we surface `confidence` per extracted mention in the
  modal? Currently no — the LLM-extraction's substring validation is
  binary (drop or keep). Revisit if analysts ask.
- **OPEN-4:** Pagination — should "Load more" be infinite scroll or
  paged? V1 is a paged button to keep the implementation small.
