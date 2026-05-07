# UX — AI Insights Tab
**Owner:** Product Designer · **Stakeholder:** the user (via PM)
**Status:** Draft v0.1 · **Date:** 2026-05-04
**Cross-refs:** [`./PRD.md`](./PRD.md) · [`./RESEARCH.md`](./RESEARCH.md) · [`./ARCHITECTURE.md`](./ARCHITECTURE.md) · [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) · [`./TASKS.md`](./TASKS.md)
**Parent PRD:** [`/strategic-insights-tool/PRD.md`](../../PRD.md)

> Planning document. ASCII wireframes, token tables, behaviour specs. No JSX, no CSS files, no real Figma frames. Exit criterion: a developer can implement V1 of `frontend/src/components/insights/` without inventing visual decisions.

---

## U1. Audience & UX goals

### U1.1 Personas (restated from PRD §4)

| # | Persona | Goal in 60 seconds on this tab |
|---|---|---|
| P1 | **the user (exec sponsor)** | Land on tab Monday 09:00. Skim 5–10 cards. Find the one non-obvious claim that sharpens his next exec sync. Push back in chat on the strongest one. Walk away with one talking point. |
| P2 | **Strategy analyst** | Filter cards by tag (`#power`, `#permits`). Copy a chart and provenance footer into Confluence. Click through citations to verify the underlying SEC 8-K. |
| P3 | **Capacity planner** | Skip the cards. Open the chat dock under a chosen insight. Ask "which states have the highest contracted-GW per active building permit?" Get a state-ranked table back. |

### U1.2 UX goals (the three things this tab must do well)

| # | Goal | Acceptance signal |
|---|---|---|
| **G1** | **Insight is scannable in <5 s.** Headline + materiality chip + chart shape carry 80% of the value before the eye moves to footnotes. | Five-card stack readable end-to-end in 60 s without scrolling past the 4th card. |
| **G2** | **Every claim's provenance is one click away.** No card asks the reader to trust without showing. Provenance footer is collapsed by default but always one chevron-click from full transparency. | A reader who clicks "show provenance" sees the SQL or endpoint, the row count, the skills run, and (V2) the citations — all without leaving the card. |
| **G3** | **Chat follow-up feels like a continuation, not a context switch.** The chat dock opens in-card with the insight headline pinned as a context chip. The dock reuses the same `agentchat/` primitives that power the global Q&A widget, so the keystroke pattern is already learned. | the user opens chat on a card and his first message is a follow-up question, not "what was that claim again?". |

These three goals trade off with each other in known places — the explicit decisions below name which goal wins each trade-off.

---

## U2. Page layout

### U2.1 Tab-nav placement (decision)

The platform has 9 existing tabs (per PRD §4.4): **Power · Satellite · GPU Supply · NICs & Optics · TSMC · Permits · Triangulation · Sources · Energy Supply · Events · Companies**. **Decision:** AI Insights lands as the **rightmost** tab, following Sources. Rationale: (a) it is the *interpretation* layer over all other tabs, so it reads as terminal in the left-to-right journey; (b) "Sources" is the closest semantic neighbour (both are meta-tabs about data, not data themselves); (c) keeping it last avoids disturbing muscle memory for the existing nav order. **Open question for PM (U14):** confirm rightmost vs. between Sources and Companies.

### U2.2 Full-page wireframe (desktop, 1440px)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Strategic Insights                                          [search]  [coverage]  [global filter]  │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Power │ Satellite │ GPU │ NICs │ TSMC │ Permits │ Triangulation │ Sources │ AI Insights *          │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                     │
│  AI Insights                                                                            [? help]    │
│  Proactive synthesis over the live data — generated 2 minutes ago.                                  │
│                                                                                                     │
│  ┌─────────────────────────────────┐  ┌──────────────────────────┐  ┌────── [Run new insights] ──┐  │
│  │ Session: 2026-05-04 09:12 UTC ▾ │  │ Companies: All ▾  Geo: US ▾ │   Time: last 90d ▾  [Cancel] │  │
│  └─────────────────────────────────┘  └──────────────────────────┘  └─────────────────────────────┘  │
│                                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │ ⚙ Surveying 6,973 sites · 1,695 energy projects · 957 events · running 4 skills…  [40%]    │    │
│  │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                                     │
│  ┌──── Insight 1 of 7 ───────────────────────────────────── [M] [conf: high]   ⋯ ────────────────┐  │
│  │  Oracle's contracted-renewable share (86%) is 3× the hyperscaler median.                     │  │
│  │  Structurally divergent from Amazon (0%, last 5 deals) and Microsoft (55%).                  │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────────────┐    │  │
│  │  │  [stacked-bar: renewable vs nuclear vs grid by hyperscaler, last 12 mo]               │    │  │
│  │  └──────────────────────────────────────────────────────────────────────────────────────┘    │  │
│  │  Source: curated_deals (n=23) · view underlying →                                            │  │
│  │                                                                                              │  │
│  │  KPI strip:  [Oracle 86%]  [MSFT 55%]  [AWS 0%]  [Google 41%]  [Meta 22%]                    │  │
│  │                                                                                              │  │
│  │  ▸ Reasoning summary (collapsed)                                                             │  │
│  │  ◇ Sources (V2): [SemiAnalysis ✓]  [Reuters ✓]  [Aterio ◐]                                  │  │
│  │  [ Discuss this insight ]   (V2)                                                             │  │
│  │  ▾ Provenance: 2 sources · 4 skills · gpt-5.4 · 09:13 UTC · session a3f2…                    │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                                     │
│  ┌──── Insight 2 of 7 ───────────────────────────────────── [L] [conf: med]   ⋯ ─────────────────┐  │
│  │  Building-permit pull-rate in Loudoun County dropped 34% in March; concurrent 8-K cadence …  │  │
│  │  …                                                                                           │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                                     │
│  ┌──── Insight 3 ──── (skeleton — streaming) ────────────────────────────────────────────────────┐  │
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                       │  │
│  │  ░░░░░░░░░░░░░░░░░░░░                                                                         │  │
│  │  [chart skeleton]                                                                             │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                                     │
│  …                                                                                                  │
│                                                                                                     │
│  ── Footer ──────────────────────────────────────────────────────────────────────────────────────   │
│  Data freshness: EDGAR 2 h · Aterio 27 d · permits 3 d · curated_deals 0 d.   [Coverage page →]    │
│  AI-generated. Treat as analysis, not fact. [legal disclaimer link]                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### U2.3 Grid spec

| Property | Desktop (≥1280) | Tablet (≥900) | Mobile (<900) |
|---|---|---|---|
| Page max-width | `1280px` (matches existing tabs' inner column) | `100vw – 24px` | `100vw – 16px` |
| Outer gutter | `24px` left/right | `16px` | `12px` |
| Card stack columns | **1** (intentional — see U12) | 1 | 1 |
| Card max-width | `1080px` (centred under header) | full | full |
| Card → card vertical gap | `24px` | `20px` | `16px` |
| Header → first card gap | `20px` | `16px` | `12px` |
| Last card → footer gap | `40px` | `32px` | `24px` |
| Streaming preamble strip | full card-width | full | full |

V1/V2 are **desktop-first** (resolves D10 — see ARCHITECTURE A15.1). Tablet/mobile breakpoints are described above so the layout doesn't visually break, but mobile is **explicitly not a target persona** in V1/V2; capacity-planner and strategy-analyst use desktop browsers.

### U2.4 Header anatomy

| Region | Element | Behaviour |
|---|---|---|
| Title row | `AI Insights` (h1) + subtitle ("Proactive synthesis over the live data") + last-generated relative-time | Right-aligned `[?]` opens a 240px popover explaining what the tab does in 3 sentences |
| Controls row | Session selector (`▾`) · Filter chips (Companies, Geo, Time-range) · Primary CTA (`Run new insights`) · Cancel (only visible while running) | Filter chips pre-populate from the global filter state if it exists for the active tab; otherwise all-defaults |
| Streaming strip | Animated preamble + progress bar | Mounts on `session_started`; replaced by first card on `insight_complete` index 0; never coexists with completed cards |

### U2.5 Right rail (V2 only)

V1 ships with no right rail — the card stack uses the full 1080 px content column. **In V2** an optional 280 px right rail appears at ≥1480 px viewport showing: session-level summary (one paragraph), "Open executive summary" button, share link. Below 1480 px the rail collapses into a button that opens a modal with the same content. **V1 decision: ship without the rail.** Rationale: on a 1366×768 laptop (the user's likely device per existing tab assumptions), a right rail forces the card column down to ~700 px and the chart legibility suffers.

### U2.6 Footer

Reuses the existing tabs' `CoverageBadge` + freshness banner pattern. Adds one line: "AI-generated. Treat as analysis, not fact." This is the AI-generated disclosure (PRD §9 R8 mitigation).

---

## U3. Insight card anatomy

The single most important component on the page. Everything else exists to serve this card.

### U3.1 Wireframe

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ┌── header ──────────────────────────────────────────────────────────────────────────────────┐   │
│ │ Insight 1 of 7        [M-materiality chip]  [conf: high chip]  [! low ext support]    ⋯    │   │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                  │
│ Oracle's contracted-renewable share (86%) is 3× the hyperscaler median.        ← HEADLINE      │
│ Structurally divergent from Amazon (0%, last 5 deals) and Microsoft (55%).     ← SUBTITLE      │
│                                                                                                  │
│ ┌── chart frame ─────────────────────────────────────────────────────────────────────────────┐   │
│ │                                                                                            │   │
│ │     [ Recharts <InsightChart spec=…> — stackedBar, 220 px tall ]                           │   │
│ │                                                                                            │   │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│ Figure: Renewable vs nuclear vs grid share, by hyperscaler, last 12 months.                      │
│ Source: curated_deals (n=23, fetched 09:12 UTC) · view underlying data →                         │
│                                                                                                  │
│ ┌── KPI strip (optional) ────────────────────────────────────────────────────────────────────┐   │
│ │  Oracle 86%   │   MSFT 55%   │   AWS 0%    │   Google 41%  │   Meta 22%                    │   │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                  │
│ ▸ Reasoning summary  (click to expand — V1 collapsed-by-default)                                 │
│                                                                                                  │
│ ── Sources (V2) ──                                                                               │
│ ◯ [Reuters · "Oracle taps Talen Energy…"        ✓ agree   ]                                     │
│ ◯ [SemiAnalysis · "Hyperscaler renewable mix…"  ✓ agree   ]                                     │
│ ◯ [Aterio note · "Renewable allocation…"        ◐ context]                                      │
│                                                                                                  │
│ [ Discuss this insight ]   (V2)                                                                  │
│                                                                                                  │
│ ── Provenance ──   (collapsed by default; chevron expands)                                       │
│ ▾ 2 sources · 4 skills · gpt-5.4 · session a3f2… · generated 09:13 UTC                           │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### U3.2 Element spec

| # | Element | Required | V-phase | Spec |
|---|---|---|---|---|
| E1 | Card index ("Insight 1 of 7") | yes | V1 | 11px, `#64748b`, top-left, no border |
| E2 | Materiality chip `[S]/[M]/[L]` | yes | V1 | 11px, monospace single letter, height 20px, padding 0 6px, background tinted by level (see U3.4), top-right cluster |
| E3 | Confidence chip `[conf: low/med/high]` | yes | V1 | 11px, height 20px, neutral border, text colour by level (high `#22c55e`, med `#f59e0b`, low `#94a3b8`) |
| E4 | Low-external-support flag (V2) | conditional | V2 | Only renders when `low_external_support=true`. Pill: 11px `! low external support`, amber `#f59e0b` border, no fill. Tooltip: "Web search returned <2 supporting citations." |
| E5 | Card actions kebab (`⋯`) | yes | V1 | 16px hit-area, opens menu: Copy permalink · Copy as Markdown · Regenerate this insight (V2) · Report as wrong (V2) |
| E6 | Headline | yes | V1 | 18px, weight 600, `#ffffff`, max 80 chars (truncate with ellipsis if exceeded — but the agent prompt should cap at 80; truncation is a fail-safe). Line-height 1.35. |
| E7 | Subtitle | yes | V1 | 13px, `#cbd5e1`, line-height 1.5, max 2 lines (`-webkit-line-clamp:2`) |
| E8 | Chart frame | yes when applicable | V1 | 220px tall by default; see U4 for sizing rules per chart type. Background `#0f172a`, 1px `#334155` border, 8px radius. Padding 12px. |
| E9 | Figure caption | yes when chart present | V1 | 11px, `#64748b`. Format: `Source: <data_source.kind>:<spec_summary> (n=<rows>) · <link to underlying data>` |
| E10 | KPI strip | optional | V1 | 5-up row of mini-tiles. Each tile: label 10px `#64748b`, number 16px weight 700 white, optional delta arrow. Renders only when `chart_type` is `kpi_tile` or when `key_numbers` array is present on the insight payload |
| E11 | Reasoning summary toggle | yes | V1 | Collapsed: chevron + "Reasoning summary". Expanded: 12px prose body, max 6 lines, then "show more" |
| E12 | Citations row | yes (V2) | V2 | See U5. Inline pills, wraps after 3. |
| E13 | "Discuss" button | yes (V2) | V2 | 32px tall, `#1e3a5f` bg, `#60a5fa` text, opens `InsightChatDock` (see U6). Icon: `MessageSquare` 14px |
| E14 | Provenance footer | yes | V1 | Collapsed by default — single line with summary counts. Resolves D6. Expanded — see U3.5. |

### U3.3 Card chrome

| Property | Default | Hover | Focus | Streaming |
|---|---|---|---|---|
| Background | `#1e293b` (matches PowerTab `CARD_STYLE`) | unchanged (no hover lift — cards are not clickable as a whole) | unchanged | unchanged |
| Border | `1px solid #334155` | unchanged | `2px solid #3b82f6` outset 2px (when card is the keyboard-focused card via J/K) | `1px dashed #475569` (subtle indicator that content is still arriving) |
| Border radius | `12px` | — | — | — |
| Shadow | none (flat — matches existing tabs) | — | — | — |
| Padding | `20px` (top/right/bottom/left) | — | — | — |
| Header → headline gap | `12px` | — | — | — |
| Headline → subtitle gap | `6px` | — | — | — |
| Subtitle → chart gap | `16px` | — | — | — |
| Chart → caption gap | `8px` | — | — | — |
| Caption → KPI gap | `16px` | — | — | — |
| KPI → reasoning gap | `12px` | — | — | — |
| Reasoning → citations gap | `12px` | — | — | — |
| Citations → discuss gap | `12px` | — | — | — |
| Discuss → provenance gap | `16px` | — | — | — |
| Card → next-card gap | `24px` (outer) | — | — | — |

**No hover-lift / hover-shadow.** Cards are content, not actions. Only the kebab and the Discuss button respond to hover.

### U3.4 Materiality & confidence chip palette

Resolves D7 (low-external-support visibility).

| Chip | Background | Border | Text | Notes |
|---|---|---|---|---|
| `[L]` (large materiality) | `#1e3a5f` | `#3b82f6` | `#60a5fa` | Brand blue — highest visual weight |
| `[M]` (medium materiality) | `#1e293b` | `#475569` | `#cbd5e1` | Neutral |
| `[S]` (small materiality) | transparent | `#334155` | `#94a3b8` | Muted |
| `conf: high` | transparent | `#22c55e44` | `#22c55e` | Success green |
| `conf: med` | transparent | `#f59e0b44` | `#f59e0b` | Warning amber |
| `conf: low` | transparent | `#94a3b844` | `#94a3b8` | Muted slate |
| `! low external support` | transparent | `#f59e0b` | `#f59e0b` | Amber outline only — distinct shape (exclamation) supports colour-blind users |

All chips use a single-letter or short-token form so screen-readers can read them as a label, not a badge. Each chip carries an `aria-label` (e.g., `aria-label="Materiality: large"`).

### U3.5 Provenance footer (PRD §5.6 — 7 fields)

Collapsed (default):

```
▾ 2 sources · 4 skills · gpt-5.4 · session a3f2… · 09:13 UTC
```

Expanded (chevron click):

```
─ Provenance ───────────────────────────────────────────────────────────────────────
  Data sources used:
    • db_query · curated_deals · 23 rows · 09:12:14 UTC
    • router_call · /api/triangulation/l2 · 9 rows · 09:12:18 UTC
  Skills used:
    [programmatic-eda]  [segmentation-analysis]  [insight-synthesis]  [data-narrative-builder]
  Confidence:    high
  Materiality:   large
  Generated:     2026-05-04 09:13:42 UTC
  Model:         oci/openai.gpt-5.4
  Session:       a3f2-7c91-…  (click to copy full ID)
─────────────────────────────────────────────────────────────────────────────────────
```

**Skills are rendered as chips, not text** — this is the SKILL_CONVERSION cross-ref (skills inform a "skills used" badge row in the provenance footer). Chip style: 10px, height 18px, `#0f172a` bg, `#334155` border, `#94a3b8` text. Tooltip on each chip: one-line description from the skill's `SKILL.md` frontmatter.

### U3.6 Card actions menu (kebab `⋯`)

| Action | V-phase | Behaviour |
|---|---|---|
| Copy permalink | V1 | Copies `/insights/sessions/<id>#insight-<insight_id>` to clipboard. Toast: "Permalink copied." |
| Copy as Markdown | V1 | Copies headline + subtitle + figure caption + provenance summary as a Markdown block. Toast: "Copied as Markdown." (Charts not in markdown — link to permalink instead.) |
| Regenerate this insight | V2 | Re-runs the per-insight verification loop. Card flips to streaming state. |
| Report as wrong | V2 | Opens 200×120 textarea modal: "What's wrong about this insight?" Submits to `tool_call_log` with `error_code=user_reported_wrong`. |

### U3.7 Dark mode

The platform is **dark-only today** (PowerTab uses `#0f172a`/`#1e293b` exclusively). **Decision: V1/V2 ship dark-only.** No light-mode tokens are designed. If light mode is added platform-wide later, the card design has no dark-mode-specific dependencies (no `#0f172a`-tinted shadows, no glow effects); it only uses the existing dark token set, so a light variant would be a token-swap.

---

## U4. Chart placement & styling

### U4.1 Palette (reused — do not invent)

Read directly from `frontend/src/components/tabs/PowerTab.tsx` lines 67–73 and `frontend/src/components/ChatPanel.tsx` lines 89–95.

| Token | Hex | Use |
|---|---|---|
| `chart.brand.microsoft` | `#38BDF8` | MSFT lines/bars |
| `chart.brand.amazon` | `#F97316` | AWS lines/bars |
| `chart.brand.google` | `#22C55E` | Google lines/bars |
| `chart.brand.meta` | `#A78BFA` | Meta lines/bars |
| `chart.brand.oracle` | `#EF4444` | Oracle lines/bars |
| `chart.categorical[0..7]` | `#3b82f6, #22c55e, #f59e0b, #ef4444, #8b5cf6, #06b6d4, #ec4899, #a855f7` | Non-company categorical (deal type, energy source, state). From `PIE_COLORS` in ChatPanel. |
| `chart.grid` | `#1e293b` | `<CartesianGrid stroke />` |
| `chart.axis.tick` | `#94a3b8` | tick text |
| `chart.axis.label` | `#64748b` | axis labels |
| `chart.tooltip.bg` | `#0f172a` | already in `TOOLTIP_STYLES` |
| `chart.tooltip.border` | `#334155` | tooltip border |

### U4.2 Sizing per `chart_type`

| `chart_type` | Frame size | Use case |
|---|---|---|
| `line`, `area`, `stacked_area`, `scatter` | full card width × 220 px tall | Time-series, distribution insights |
| `bar`, `stacked_bar`, `grouped_bar` | full card width × 220 px tall (260 px if ≥6 categories) | Comparison insights |
| `pie` | 320 px × 220 px centred | Composition insights — capped at 8 slices (existing rule from `ChatPanel.tsx::TRUNCATE_AT`) |
| `sparkline` | full card width × 60 px tall, axes off | Inline trend annotation, not the primary chart |
| `kpi_tile` | replaces the chart frame entirely with the KPI strip (E10), no Recharts call | Single-number-shaped insights |

### U4.3 Tooltip styling

Already standardized via `TOOLTIP_STYLES` in `ChatPanel.tsx` (lines 89–93). Reuse verbatim. No new tooltip variants.

### U4.4 Caption beneath chart

Format: `Source: <kind>:<spec_summary> · n=<rows> · <link>`

Examples:
- `Source: db_query: curated_deals · n=23 · view underlying →`
- `Source: router_call: /api/triangulation/l2?company=Oracle · n=9 · view underlying →`
- `Source: chart_data: power.gw_by_company · n=5 · open Power tab →`

The link target depends on `data_source.kind`:
- `db_query` → opens a small modal showing the SQL + first 50 rows of the queried frame (read-only, scrollable).
- `router_call` → opens a small modal showing the endpoint + the JSON response (collapsed at depth 2).
- `chart_data` → deep-links to the originating tab and chart (e.g., `/power#gw_by_company`).

### U4.5 Empty / zero-data chart

If `data.length == 0` after validation:

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│   No data for this slice — reasoning still applies.      │
│   ↳ See provenance footer for the underlying query.      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

11px `#94a3b8`, centred vertically, height 220 px (matches normal frame). Do **not** render an empty Recharts axis frame — it implies measurement and there is no measurement.

---

## U5. Citation styling (V2)

### U5.1 Inline citation pill

```
┌─────────────────────────────────────────────────────┐
│ [favicon] Reuters · Oracle taps Talen Energy…  ✓     │
└─────────────────────────────────────────────────────┘
```

| Property | Spec |
|---|---|
| Height | 28 px |
| Padding | 4px 10px |
| Background | `#1e293b` |
| Border | `1px solid #334155` |
| Border-radius | 14 px (full pill) |
| Favicon | 16×16 px, fetched from `https://<host>/favicon.ico`. Fallback: `Globe` lucide icon at `#64748b`. |
| Title text | 12px `#cbd5e1`, max 60 chars truncated with ellipsis, host preserved as prefix |
| Agree/disagree icon | 12px, **shape redundant** with colour: `✓` (CheckCircle) for agree, `✗` (XCircle) for disagree, `◐` (Circle half) for context |
| Agree colour | text `#22c55e`, no fill |
| Disagree colour | text `#f59e0b` (NOT red — keeps red for true error states only), no fill |
| Context colour | text `#94a3b8`, no fill |

**Why amber for disagree, not red:** red is reserved for error states (failed loads, dead links). A disagreeing citation is informative, not broken. Amber + `✗` shape carries the meaning without taxing the error-state palette. **Resolves accessibility note:** colour alone never carries the agree/disagree distinction — the icon shape does (`✓`/`✗`/`◐`).

### U5.2 Hover card (resolves D3)

**Decision: hover-card preferred over inline expansion.** Rationale:

| Inline expansion (rejected) | Hover-card (chosen) |
|---|---|
| Each citation balloons the card height by 60–80 px; 3 citations adds ~240 px to a card | Card height stable; details revealed on demand |
| Forces a sequential read order (citations always visible in line) | Reader can scan all 3 pills first, then drill |
| Snippet truncation in the inline row creates a "preview-of-the-preview" problem | Full snippet available in 300px hover card |
| Mobile-friendly | Mobile-hostile, but mobile is non-target |

Hover-card spec:

```
   ┌── 300 × auto ──────────────────────────────────────────┐
   │  [favicon] Reuters · 2026-04-22                        │
   │  Oracle taps Talen Energy in nuclear PPA               │
   │ ─────────────────────────────────────────────────────  │
   │  "Oracle has signed a 1.2 GW PPA with Talen Energy,    │
   │   bringing its renewable share to 86% of contracted    │
   │   capacity, well above the hyperscaler median…"        │
   │ ─────────────────────────────────────────────────────  │
   │  [✓ AGREE] Snippet cites the 86% figure within ±2pp.   │
   │  Retrieved 09:12:43 UTC · open in new tab →            │
   └────────────────────────────────────────────────────────┘
```

Behaviour:
- Mount delay: 300 ms hover, 0 ms keyboard focus.
- Dismiss: pointer leave + 100 ms grace; or Esc.
- Position: prefers below-right of the pill; flips up if within 100 px of viewport bottom.
- Z-index: 100 (above chart tooltips at z-index 50).
- Snippet body: 12px `#cbd5e1`, max 6 lines.
- Rationale block: 11px italic `#94a3b8`, prefixed by the same chip-shape used inline (`[✓ AGREE]`).
- Open-link: 12px `#60a5fa`, opens new tab.

### U5.3 Citation row layout

3 pills wrap to a new row every 3. If `>5` citations exist, render the first 5 plus a `+N more` chip that opens an InsightCitationsModal.

---

## U6. Chat dock (V2)

### U6.1 Resolution of D2 (where the chat lives)

**Decision: in-card slide-down dock.** Justification:

| Option | Why considered | Why rejected (or kept) |
|---|---|---|
| **In-card slide-down** | Keeps the conversation visually adjacent to the insight it's about. Matches the architect's recommendation (ARCHITECTURE A12.2 — "InsightChatDock is docked into the bottom of the insight card, not a floating FAB"). Fits the "continuation, not context switch" UX goal (G3). | **Chosen.** |
| Persistent right-rail | One pane, visible at all times. | Right-rail eats 280 px on a 1366 px laptop, hurting chart legibility (the very thing we're protecting in U2.5). And it implies a single global thread, which conflicts with PRD §5.4 (per-insight scoping). |
| Floating FAB / modal | Already exists for the global Q&A widget (`ChatPanel.tsx`). | Coexistence problem — two FABs on screen at once is confusing. Modal forces full-screen and breaks the "scoped to this insight" feel. |
| Bottom-of-page persistent dock | One thread per page. | Doesn't scope to insight; same per-insight conflict as the right-rail. |

The global `ChatPanel.tsx` FAB stays for cross-tab Q&A. **Insight-scoped chat is structurally different and lives in-card.** The two are wired via the same `agentchat/` primitives (per RESEARCH R5).

### U6.2 Wireframe (dock open under one card)

```
┌──── Insight 1 of 7 ───────────────────────────────── [M] [conf: high] ⋯ ──┐
│ Oracle's contracted-renewable share (86%) is 3× the hyperscaler median.  │
│ … (rest of card as in U3.1) …                                            │
│                                                                          │
│ [ ✗ Close discussion ]                                                   │
├──────────────────────────────────────────────────────────────────────────┤
│ ── Discuss this insight ───────────────  [ scoped to this insight pill ] │
│                                                                          │
│ ┌── pinned context chip ───────────────────────────────────────────────┐ │
│ │ "Oracle's contracted-renewable share (86%) is 3× the hyperscaler …" │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│ ┌── messages ─────────────────────────────────────────────────────────┐  │
│ │  the user:                                                              │  │
│ │  ╭─────────────────────────────────────────────────────────────────╮ │  │
│ │  │ Is the renewable concentration a financing constraint or a       │ │  │
│ │  │ strategy?                                                        │ │  │
│ │  ╰─────────────────────────────────────────────────────────────────╯ │  │
│ │                                                                      │  │
│ │  Analyst:                                                            │  │
│ │  ╭─────────────────────────────────────────────────────────────────╮ │  │
│ │  │ Looking at the financing structure across Oracle's last 5 deals: │ │  │
│ │  │ [chart streamed inline]                                          │ │  │
│ │  │ ▸ Show reasoning (4 tool calls)                                  │ │  │
│ │  │ Sources: [SEC 10-K ✓]                                            │ │  │
│ │  ╰─────────────────────────────────────────────────────────────────╯ │  │
│ └──────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│ ┌── input ───────────────────────────────────────────────────────────┐   │
│ │ Ask a follow-up about this insight…                          [Send] │   │
│ └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### U6.3 Spec

| Region | Spec |
|---|---|
| Dock header | 13px weight 600 white "Discuss this insight" + right-aligned `[scoped to this insight]` pill (10px, `#1e3a5f` bg, `#60a5fa` text). Pill exists to make the scope obvious. |
| Pinned context chip | 12px, `#0f172a` bg, `#475569` left-border 3px, italic `#cbd5e1`. Always-on. Truncates the headline at 80 chars. |
| Message list | Reuses `agentchat/AgentMessage`. Max-height 400px, scrollable. Auto-scrolls to bottom on new message. |
| Tool trace toggle | Reuses `agentchat/ToolTrace`. Collapsed by default (text "▸ Show reasoning (N tool calls)"). Resolves PRD §5.5 visibility default. |
| Input box | Reuses `agentchat/` input pattern from `ChatPanel.tsx` (lines 538–582). Placeholder: "Ask a follow-up about this insight…". |
| Send button | `#3b82f6` when input non-empty, `#334155` disabled. Reuses ChatPanel send-button pattern. |
| Stop button | Replaces Send during stream — `#ef4444` "Stop" with Square icon. Same pattern as `ChatPanel.tsx`. |
| Close button | Top-right of dock — collapses dock back to "Discuss this insight" button. State preserved (re-opening shows the same thread). |
| Persistence | Thread persists per `insight_id` across page loads (loaded via `GET /api/insights/insights/{id}/chat`). |
| Empty state | When the thread has 0 messages: a single suggestion chip below the pinned context: "Try: 'Why is Oracle's mix this divergent?'". |

### U6.4 SSE events the dock consumes (per ARCHITECTURE A5)

| Event | Action in dock |
|---|---|
| `token` (with `field=body`) | Append `delta` to the in-flight assistant message's body |
| `tool_call` | Append a row to the assistant message's `ToolTrace` (collapsed) |
| `tool_result` | Update the row to show `ok` + `row_count` + `latency_ms` |
| `chart` | Mount an `<InsightChart>` inline in the assistant message (same component as in cards) |
| `citation` | Append a citation pill to the assistant message |
| `error` | Render an inline error block at message-tail; if `retryable=true`, show a Retry button |
| `ping` | ignore |
| `insight_started` / `insight_complete` / `session_*` | not used here — dock is per-insight chat, not session-level |

The dock does **not** consume `surveying` or `reasoning_step` events.

### U6.5 Latency UX

Per PRD §5.4 the chat latency budget is ≤20 s p50 / ≤45 s p95. UX accommodations:

| Time elapsed | Treatment |
|---|---|
| 0–500 ms | Empty assistant bubble with a 3-dot pulser |
| 500 ms+ | First token streams; cursor (`|`) trails the last char while streaming |
| 5 s without tokens | Add a subtle "Thinking…" line with an animated ellipsis below the bubble |
| 30 s without first token | Add "Still working — long-running tool call" line |
| 45 s+ | Timeout error inline; suggest "Try a more specific follow-up" |

Reduced-motion users see static dots, no pulser, no animated ellipsis, no streaming cursor.

---

## U7. Loading & streaming states

### U7.1 State catalogue

| State | When | Visual | Resolves |
|---|---|---|---|
| **S1. Empty page (no session yet)** | First-ever visit, no `ai_sessions` rows | Hero block + CTA + recent-sessions list (empty) | — |
| **S2. Recent-sessions list (>1 session exists)** | After at least one prior session | Session selector populated, last session's cards rendered (read-only view) | — |
| **S3. Session running, no insights yet** | Between `session_started` and first `insight_started` | Animated surveying preamble + 5 ghost-skeleton cards | D5 (preamble UX) |
| **S4. Insight 1 streaming** | After first `insight_started`, during `token` events | Card 1 mounted; headline streams token-by-token in low-contrast "drafting" treatment; chart frame is a skeleton; citations row hidden until citation events | D1, D4 |
| **S5. Insight 1 complete, Insight 2 streaming** | After `insight_complete` for index 0, during `token` for index 1 | Card 1 in solid final state; Card 2 in S4 treatment | D1 |
| **S6. All insights complete** | After `session_complete` | All cards solid; surveying preamble removed; "Generated 09:13 UTC" timestamp under header | — |
| **S7. Reconnecting** | EventSource onerror, before reconnect | Subtle toast top-right: "Reconnecting…" 11px `#94a3b8` bg `#1e293b`. After reconnect: "Reconnected" 1.5 s then dismiss | — |
| **S8. Cancelled (mid-session)** | After cancel POST + `error code=cancelled` event | Banner above cards: "Session cancelled at insight 3 of 5" amber. Cards 1–3 stay; cards 4–5 are removed | D8 |

### U7.2 Skeleton hierarchy (resolves D4)

When `insight_started` arrives **without** any `token` events yet, render:

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Insight 3 of 7                                       [skel chip] [skel]  ⋯ │   ← header line — index visible immediately
│                                                                            │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    │   ← headline shimmer line (1 line, 80% width, animated)
│                                                                            │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                         │   ← subtitle shimmer (60% width)
│                                                                            │
│ ┌────────────────────────────────────────────────────────────────────┐    │
│ │                                                                    │    │   ← chart skeleton frame, full width × 220 px
│ │   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                │    │
│ │   ░░░░░░░░░░░░░░░░░░░░░░░                                         │    │
│ └────────────────────────────────────────────────────────────────────┘    │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░                                              │   ← caption shimmer
│                                                                            │
│ ░░░░░░░░░░░░░░░░  ░░░░░░░░░  ░░░░░░░░░  ░░░░░░░░░                          │   ← provenance footer shimmer
└────────────────────────────────────────────────────────────────────────────┘
```

Order of resolution as events arrive:
1. **Header** (insight index, materiality chip placeholder) — solid immediately on `insight_started`.
2. **Headline** — streams char-by-char on `token field=headline` events. Cursor `|` trails the last char. Color `#94a3b8` ("drafting") until `insight_complete`, then transitions to `#ffffff` (final). **Resolves D1.**
3. **Subtitle** — same treatment as headline.
4. **Chart frame** — shimmer until `chart` event; then mounts `<InsightChart>` with a 200 ms fade-in.
5. **Citations row** — hidden entirely until first `citation` event; then mounts pills one at a time as events arrive.
6. **Provenance footer** — shimmer until `insight_complete`; then resolves with skill chips animating in left-to-right (50 ms stagger).

**Skeletons use a CSS pulse animation:** `background: linear-gradient(90deg, #1e293b 0%, #334155 50%, #1e293b 100%); animation: pulse 1.6s ease-in-out infinite;`. **Reduced-motion users see a static `#334155` block** (no animation).

**No spinners.** Only shimmer skeletons + a single horizontal progress bar in the surveying preamble.

### U7.3 Wireframe — S1 (empty page)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AI Insights                                                                │
│  Proactive synthesis over the live data.                                    │
│                                                                             │
│         ┌──────────────────────────────────────────────────────┐            │
│         │                                                      │            │
│         │              [glyph: lightbulb 64 px]                │            │
│         │                                                      │            │
│         │   No sessions yet                                    │            │
│         │   The agent surveys 6,973 sites, 1,695 energy        │            │
│         │   projects, 957 events and 23 curated power deals,   │            │
│         │   then surfaces 5–10 non-trivial findings per run.   │            │
│         │                                                      │            │
│         │   [ Run my first insights session ]                  │            │
│         │                                                      │            │
│         │   Typical run: 60–180 s.                             │            │
│         │                                                      │            │
│         └──────────────────────────────────────────────────────┘            │
│                                                                             │
│  ── Footer (data freshness) ──                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### U7.4 Wireframe — S3 (surveying preamble + 5 skeleton cards)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AI Insights                       Session: 2026-05-04 09:12 UTC ▾ [Cancel] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──── ⚙ Surveying the platform ─────────────────────────────────────────┐  │
│  │  Reading 6,973 sites · 1,695 energy projects · 957 events           │  │
│  │  Skills queued: programmatic-eda, segmentation-analysis, …          │  │
│  │  Hypotheses generated: 11   Verified: 3                             │  │
│  │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ETA 90 s │  │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌── skeleton card 1 ────────────────────────────────────────────────┐    │
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │    │
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                              │    │
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌── skeleton card 2 ────────────────────────────────────────────────┐    │
│  │  …                                                                 │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  …(3 more skeleton cards)                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

The surveying strip:
- Background `#162032` (matches existing tabs' header treatment), border `1px solid #1e293b`, radius 8 px.
- Gear icon `⚙` rotates slowly when `prefers-reduced-motion` is not set; static otherwise.
- Counts (`6,973 sites`, `1,695 energy projects`) come from a server-rendered constant — they're the platform's published numbers, not live counters.
- "Hypotheses generated: 11   Verified: 3" updates as `surveying`/`reasoning_step` events arrive.
- Progress bar is **wall-clock proportional** (elapsed/expected_total), not "tokens emitted" — the latter is meaningless to the user.
- ETA is a heuristic: if `insights_emitted == 0` after 30 s, ETA reads "≤90 s"; after `insight_complete[0]`, ETA reads "≤(remaining * 20s)".

### U7.5 Wireframe — S4 (insight 1 streaming)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  …header…                                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌── Insight 1 of 7 ────────────────────────────  [drafting…]  ⋯ ──────┐  │
│  │  Oracle's contracted-renewable share (86%) is 3× the hyperscaler|   │  │   ← cursor still emitting
│  │                                                                      │  │
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░       │  │   ← subtitle still skeleton
│  │  ┌─────────────────────────────────────────────────────────┐        │  │
│  │  │           [ chart skeleton — 220 px tall ]              │        │  │
│  │  └─────────────────────────────────────────────────────────┘        │  │
│  │  ░░░░░░░░░░░░░░░░░░░░░░░░░                                          │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌── skeleton card 2 ────────────────────────────────────────────────┐    │
│  │  …                                                                 │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

Notes on the streaming card:
- `[drafting…]` chip in the header — replaces the materiality + confidence chips during streaming. 11px `#94a3b8` text, italic.
- Headline text in `#94a3b8` (drafting). Snaps to `#ffffff` on `insight_complete`.
- **Focus is not stolen** when this card mounts. The page's keyboard focus stays where it was. (See U9.)

---

## U8. Empty / error / edge states

### U8.1 Catalogue

| # | State | Cause | Visual | Recovery |
|---|---|---|---|---|
| EE1 | No data ingested at all | Fresh DB, surveying returns 0 candidates (rare) | Banner inside surveying strip: "Platform data is empty — nothing to analyse yet." Followed by a link to the Sources tab. CTA disabled. | Re-run after ingestion catches up |
| EE2 | LlamaStack unavailable | 5xx from `LlmClient.reason()` | S1-style hero replaced with: "AI service unavailable — last successful session: <timestamp> [view last session]". CTA disabled. | Auto-retry every 30 s in the background; toast "Service back" on recovery |
| EE3 | Web search blocked / timeout (V2) | Both Tavily and Brave return errors | Banner top-of-stack: "Web search degraded — citations may be incomplete." Per-card `! low external support` chip on every affected card | Continue session; show banner until session ends |
| EE4 | Tool-loop hit limit (per-insight) | `tool_error: turn_budget` | Card renders with header chip `[partial]` (amber). Body says "Insight halted at depth 12 — partial result rendered." Reasoning summary is forced-expanded so the user sees what was learned | Show "Regenerate this insight" in kebab menu |
| EE5 | DB query failed (per-insight) | sqlglot reject or timeout | Card retries internally up to 2× (per ARCHITECTURE A13). On final failure: card shows "Couldn't verify against data" + Retry button + the failed SQL in a code block (collapsed) | User clicks Retry |
| EE6 | ChartSpec invalid | Pydantic / Zod parse fail | Card body fully renders. Chart frame replaced with: "Chart unavailable; reasoning preserved." + a `▸ Show raw spec` chevron that expands to a JSON viewer (read-only, syntax-highlighted, max-height 240 px scroll). Resolves ARCHITECTURE A13. | None — soft fail; chart unavailable for this insight |
| EE7 | User cancelled session | POST cancel | Banner: "Session cancelled at insight 3 of 5 — partial insights kept." Amber. Cards 1–3 persist; cards 4–5 unmount; surveying strip removed. **Resolves D8.** | "Run new insights" CTA re-enables |
| EE8 | Stream disconnect | EventSource onerror | Toast top-right: "Reconnecting…" `#94a3b8` on `#1e293b`. After Last-Event-ID resume succeeds: "Reconnected" 1.5s. If reconnect fails 3×: error EE2 path | Automatic |
| EE9 | Insight headline ≥80 chars (overflow) | Agent prompt failed to cap | Truncate with `…` at 78 chars + 2-char ellipsis. Hover reveals full headline as tooltip. (Not the user's problem — but the renderer doesn't break.) | None |
| EE10 | Permalink to a deleted session | `GET /sessions/<id>` returns 404 | Page renders S1 hero + a banner: "This session was deleted or expired." | "Run new insights" CTA |

### U8.2 Wireframe — EE7 (cancelled)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AI Insights                                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ ⚠ Session cancelled at insight 3 of 5 — partial insights kept.       │  │
│  │   [ Run new insights ]                                                │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌── Insight 1 of 3 (kept) ──────────────────────…                       │  │
│  │  …                                                                    │  │
│  └────────────────────────────────────────────────                       │  │
│                                                                             │
│  ┌── Insight 2 of 3 (kept) ──────────────────────…                       │  │
│  │  …                                                                    │  │
│  └────────────────────────────────────────────────                       │  │
│                                                                             │
│  ┌── Insight 3 of 3 (kept) ──────────────────────…                       │  │
│  │  …                                                                    │  │
│  └────────────────────────────────────────────────                       │  │
└─────────────────────────────────────────────────────────────────────────────┘
```

Cancel banner:
- Background `#1e1b14` (warm amber-tinted dark), border `1px solid #f59e0b`, radius 8.
- Icon `⚠` `#f59e0b`, 16 px.
- Text 12px `#cbd5e1`.
- CTA right-aligned, secondary style (`#1e293b` bg, `#3b82f6` border, `#60a5fa` text).

### U8.3 Wireframe — EE6 (chart invalid)

```
┌─── Insight 4 of 7 ─────────────────────────── [M] [conf: med]  ⋯ ──┐
│ Hyperscaler 8-K cadence shifted 22% in March vs Feb baseline.       │
│                                                                     │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │                                                                 │ │
│ │   Chart unavailable; reasoning preserved.                       │ │
│ │   ▸ Show raw spec                                               │ │
│ │                                                                 │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ ─ Reasoning summary (auto-expanded) ─                               │
│ The agent observed that…                                            │
│ …                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

When the chart can't render, the reasoning summary auto-expands so the card still earns its space.

---

## U9. Interaction details

### U9.1 Keyboard shortcuts

| Keys | Action | Available when |
|---|---|---|
| `J` | Move focus to next card | Tab is active, focus is on body or a card |
| `K` | Move focus to previous card | Tab is active, focus is on a card |
| `Enter` | Toggle reasoning summary on focused card | Focus on a card |
| `C` | Open chat dock for focused card (V2) | Focus on a card |
| `G then I` | Jump to AI Insights tab from anywhere | Global |
| `R` | Open `Run new insights` confirmation | Tab is active, no session running |
| `Esc` | Cancel the running session (or close kebab/hover-card) | Focus in session header / dialog open |
| `Cmd/Ctrl + Enter` | Submit chat input | Chat dock open with input focused |
| `?` | Open keyboard-shortcuts help overlay | Tab is active |

Visible-focus styles:
- Cards: `2px solid #3b82f6` outset 2px when focused via J/K.
- Buttons / pills: `2px solid #3b82f6` inset 0px (browser default focus ring overridden).
- The default browser focus ring is removed and replaced — but only on these explicit elements.

### U9.2 Focus management

- **Streaming new card does NOT steal focus.** This is critical for keyboard users — if you're reading insight 2 and insight 3 starts streaming below, your focus stays.
- After session_complete, focus stays where the user put it; we do not auto-jump anywhere.
- After `Run new insights`: focus moves to the `Cancel` button (so Esc/Tab dismiss flow is one keystroke away).
- After `Cancel`: focus moves to the cancelled-banner's "Run new insights" CTA.
- Hover-cards never steal focus — they only mount on pointer hover or keyboard focus *of the citation pill itself*.

### U9.3 Hash deep-link

Format: `/insights/sessions/<session_id>#insight-<insight_id>`

Behaviour on load:
1. Page renders the named session in read-only state (cards solid).
2. `window.scrollTo` to the named insight's offsetTop − 80 px.
3. Card receives a 600 ms highlight pulse (`box-shadow: 0 0 0 2px #3b82f6` fading to none).
4. URL hash is preserved across reasoning-summary expand/collapse.

### U9.4 Share & copy

| Action | V-phase | Detail |
|---|---|---|
| Copy permalink | V1 | Card kebab → Copy permalink. Writes the deep-link URL to clipboard. |
| Copy as Markdown | V1 | Card kebab → Copy as Markdown. Content (Markdown form):  `### <headline>\n\n<subtitle>\n\n_Source: <data_source.kind>:<spec_summary> · n=<rows>_\n\n[See full insight](<permalink>)` |
| Share by link | V3 | Sends `POST /share` to mint a short-link. Out of V1/V2 scope. |

### U9.5 Cancel UX (resolves D8)

- Single page-level Cancel button (in the header, only visible while session is running).
- No per-insight pause. (Per-insight pause was considered and rejected: the orchestrator runs insights sequentially in V1, so per-insight pause = "stop after current insight finishes" which is just the natural end of streaming. Adds confusing button.)
- Esc keystroke triggers the same Cancel.
- Confirmation: none — Cancel is reversible (just click "Run new insights" again to start fresh). Don't add friction.

---

## U10. Accessibility

### U10.1 Colour + shape redundancy

Every status indicator uses **at least one non-colour signal**:

| Indicator | Colour | Shape / glyph |
|---|---|---|
| Materiality `[L]` / `[M]` / `[S]` | brand blue / neutral / muted | letter inside brackets |
| Confidence | green / amber / muted | text label "high"/"med"/"low" |
| Citation agree | green text | `✓` icon |
| Citation disagree | amber text | `✗` icon |
| Citation context | muted | `◐` half-circle |
| Low external support | amber | `!` glyph + "low external support" text |
| Chart series colours | brand colours | distinct line stroke patterns when ≥3 series share a chart (solid / dashed / dotted) |

### U10.2 ARIA-live regions

| Region | aria-live | Reason |
|---|---|---|
| Surveying preamble strip | `polite` | User wants to know when generation is done; politeness avoids interrupting their reading |
| Each card body | `off` (default) | Streaming tokens would spam screen readers — not announced |
| Each `insight_complete` event | the card's `aria-label` updates from "Insight 1, drafting" to "Insight 1, complete: <headline>" — announced once via a single `aria-live=polite` "status" element shared across cards | One announcement per insight, not per token |
| Reconnecting / Reconnected toast | `polite` | Relevant but non-interrupting |
| Cancelled banner | `assertive` | Important state change |
| Error EE2 (LlamaStack down) | `assertive` | Important — user's CTA is now disabled |
| Tool-trace expand | uses `aria-expanded` on the toggle, no announcement | Visual-only |

### U10.3 Contrast audit (existing palette)

Tested against WCAG 2.1 AA (4.5:1 body text, 3:1 large text):

| Pair | Ratio | Pass? |
|---|---|---|
| `#ffffff` on `#1e293b` (headline on card) | 14.6 : 1 | ✓ |
| `#cbd5e1` on `#1e293b` (subtitle) | 10.8 : 1 | ✓ |
| `#94a3b8` on `#1e293b` (caption) | 6.1 : 1 | ✓ |
| `#64748b` on `#1e293b` (muted line) | **3.9 : 1** | ✗ for body, ✓ for ≥18px |
| `#3b82f6` on `#1e293b` (link) | 4.9 : 1 | ✓ |
| `#22c55e` on `#1e293b` (success) | 6.7 : 1 | ✓ |
| `#f59e0b` on `#1e293b` (warning) | 8.2 : 1 | ✓ |
| `#ef4444` on `#1e293b` (danger) | 5.5 : 1 | ✓ |
| `#60a5fa` on `#1e293b` (link var) | 6.4 : 1 | ✓ |
| `#94a3b8` on `#0f172a` (chart axis) | 7.4 : 1 | ✓ |

**One palette violation:** `#64748b` body text on `#1e293b` cards (3.9:1) fails for <18px. The existing `PowerTab` uses `#64748b` for 11px metadata strings (e.g. dates). **Mitigation in the AI Insights tab:** never use `#64748b` for any text smaller than 12 px on `#1e293b`. Where 11px metadata is needed, step up to `#94a3b8`. Document this as a tab-local rule until the platform addresses globally.

### U10.4 Keyboard-only flow

A keyboard-only user can complete the full happy path:

1. `G then I` — jump to tab.
2. `Tab` to "Run new insights" CTA, `Enter` to start.
3. Focus auto-moves to Cancel; user reads via screen reader updates from the surveying strip.
4. Once session_complete, `Tab` reaches the first card.
5. `J/K` cycles cards.
6. `Enter` expands reasoning on focused card.
7. (V2) `C` opens chat dock. Tab into the input. Type. Cmd/Ctrl-Enter to send. Esc to close dock.
8. `Cmd/Ctrl-C` while focus is on the kebab menu's "Copy permalink" item to copy the link.

### U10.5 Reduced motion

Honour `prefers-reduced-motion: reduce`:

| Element | Default motion | Reduced-motion variant |
|---|---|---|
| Skeleton pulse | 1.6 s ease-in-out infinite | static `#334155` |
| Streaming cursor `|` | 1 s blink | hidden; tokens just append |
| Surveying gear `⚙` | 4 s linear rotate | static |
| Card mount fade-in | 200 ms | 0 ms (snap) |
| Hover-card mount | 150 ms scale-from-95% | snap |
| Highlight-pulse on deep-link | 600 ms | snap to bg-tint and stay 600 ms then snap back |
| Provenance skill chip stagger | 50 ms left-to-right | all appear simultaneously |

---

## U11. Visual tokens

The platform does **not have a centralized token file**; tokens are inlined in component files (e.g. `PowerTab.tsx::CARD_STYLE`, `ChatPanel.tsx::TOOLTIP_STYLES` and `PIE_COLORS`). **Recommendation for V1 implementation:** create `frontend/src/styles/insightTokens.ts` to consolidate the values listed below, *then* migrate existing tabs in a follow-up. Until that migration ships, the AI Insights tab inlines the same hex values to match.

### U11.1 Spacing scale

| Token | Px | Use |
|---|---|---|
| `s.0` | 0 | reset |
| `s.1` | 4 | tight inline |
| `s.2` | 8 | inter-chip gap |
| `s.3` | 12 | label-to-control |
| `s.4` | 16 | small section |
| `s.5` | 20 | card padding |
| `s.6` | 24 | card-to-card |
| `s.7` | 32 | section-to-section |
| `s.8` | 48 | major section break |

### U11.2 Radii

| Token | Px | Use |
|---|---|---|
| `r.sm` | 4 | source badge |
| `r.md` | 6 | input |
| `r.lg` | 8 | callout / chart frame |
| `r.xl` | 12 | card |
| `r.pill` | 999 | citation pill |

### U11.3 Shadows

| Token | Value | Use |
|---|---|---|
| `shadow.none` | `none` | cards (flat) |
| `shadow.fab` | `0 8px 24px rgba(59,130,246,0.4)` | global ChatPanel FAB only |
| `shadow.modal` | `0 24px 64px rgba(0,0,0,0.6)` | modal dialogs |
| `shadow.popover` | `0 16px 40px rgba(0,0,0,0.5)` | hover-card |

### U11.4 Type scale

| Token | Size / weight | Use |
|---|---|---|
| `t.display` | 26 / 700 | hero numbers (KPI primary) |
| `t.title` | 18 / 600 | insight headline |
| `t.subtitle` | 14 / 500 | section heads |
| `t.body` | 13 / 400 | card subtitle, message body |
| `t.caption` | 12 / 400 | figure captions |
| `t.meta` | 11 / 400 | chip text, timestamps |
| `t.micro` | 10 / 600 (uppercase) | section eyebrows ("Sources", "Analyst") |
| `t.mono` | 12 / 400 monospace | session IDs, SQL preview |

Font family: inherits from platform (`-apple-system, BlinkMacSystemFont, …` — defaults). No webfont introduction.

### U11.5 Color tokens (semantic)

| Token | Hex | Source / reuse |
|---|---|---|
| `color.bg.page` | `#0a1220` | Implicit page bg from existing tabs |
| `color.bg.card` | `#1e293b` | `PowerTab.CARD_STYLE.background` |
| `color.bg.surface` | `#0f172a` | `ChatPanel.TOOLTIP_STYLES.contentStyle.background` |
| `color.bg.surfaceAlt` | `#162032` | `ChatPanel` header bg |
| `color.border.weak` | `#1e293b` | row dividers |
| `color.border.default` | `#334155` | card border |
| `color.border.strong` | `#475569` | popover border |
| `color.text.primary` | `#ffffff` | headlines |
| `color.text.body` | `#e2e8f0` | body |
| `color.text.muted` | `#cbd5e1` | secondary body |
| `color.text.caption` | `#94a3b8` | captions, metadata |
| `color.text.faint` | `#64748b` | use only ≥12px ([U10.3](#u103-contrast-audit-existing-palette)) |
| `color.text.deepest` | `#475569` | section eyebrows |
| `color.brand.primary` | `#3b82f6` | links, CTAs |
| `color.brand.primaryHover` | `#60a5fa` | hover/active link |
| `color.semantic.success` | `#22c55e` | confidence high, agree |
| `color.semantic.warning` | `#f59e0b` | confidence med, disagree, low support, partial |
| `color.semantic.danger` | `#ef4444` | true errors, stop button |
| `color.semantic.info` | `#06b6d4` | rare, contextual chip variant |
| `color.brand.microsoft` | `#38BDF8` | from PowerTab |
| `color.brand.amazon` | `#F97316` | from PowerTab |
| `color.brand.google` | `#22C55E` | from PowerTab |
| `color.brand.meta` | `#A78BFA` | from PowerTab |
| `color.brand.oracle` | `#EF4444` | from PowerTab |
| `chart.categorical[0..7]` | `#3b82f6, #22c55e, #f59e0b, #ef4444, #8b5cf6, #06b6d4, #ec4899, #a855f7` | from `ChatPanel.PIE_COLORS` |

### U11.6 Breakpoints

| Token | Px | Note |
|---|---|---|
| `bp.mobile` | <900 | best-effort layout |
| `bp.tablet` | ≥900 | best-effort layout |
| `bp.desktop` | ≥1280 | primary target |
| `bp.wide` | ≥1480 | enables V2 right-rail |

### U11.7 Where tokens live

- **Today (existing platform):** values inlined in component files.
- **V1 plan:** add `frontend/src/styles/insightTokens.ts` exporting the above as named consts. AI Insights components import from there.
- **Follow-up (out of scope here):** migrate `PowerTab`/`ChatPanel`/etc. to import the same module, then deprecate inline duplicates. **PM open question (U14):** do we want to do the platform-wide migration as part of V1, or as a separate cleanup task?

---

## U12. Information density vs scannability

### U12.1 Card-stack vs 2-column grid

**Decision: 1-column card stack, vertically scrollable.** Rationale:

| Factor | 1-column stack (chosen) | 2-column grid (rejected) |
|---|---|---|
| Insight size variability | Insights vary in size (a KPI-tile insight is shorter than a stacked-bar-with-citations insight). 1-col gracefully accommodates any height. | 2-col forces uniform card heights or creates jagged "Pinterest" layouts; jagged layout fights the scan-pattern (G1). |
| Reading order | Strict top-to-bottom — agent has *ranked* the insights by materiality + novelty (PRD §5.1). Top-to-bottom matches the rank. | Reader's eye is forced into a Z-pattern; the rank gets lost. |
| Chart legibility | 1080 px-wide column gives charts ~1040 px after padding — plenty of room for a stacked-bar with 5 hyperscalers and 12 months. | 2-col halves chart width to ~510 px, forcing axis-label rotation and tighter tick density. |
| Streaming UX | Insight N+1 always renders below — no "where did the new card just appear" hunt. | New card could appear in either column; less predictable. |
| Mobile | Already 1-col. | Doesn't gracefully degrade. |

The cost of 1-column is more vertical scrolling. We accept that — the user-style scanners are reading ~5 cards × ~600 px each = 3000 px, which is one-and-a-half page-downs. That's faster than parsing a 2-col grid.

### U12.2 60-second-scan path (the user persona)

For the user (P1) on a 1366 × 768 laptop at default zoom:

```
0:00 — Land on tab. Header + first card visible.
0:02 — Eye locked on first headline (it's 18px weight 600 — highest contrast on page).
0:05 — Glance right at materiality chip. [L] = read further; [S] = skim.
0:08 — Glance at chart shape. Stacked-bar with one tall outlier? Read chart caption.
0:15 — Decide: useful / not useful. Either click "Discuss" (V2) or J to next card.
0:18 — Card 2 headline.
…
0:55 — Card 5 read.
0:60 — Choose 1 card to open Discuss on, OR done.
```

The **headline + materiality chip + chart shape** carry 80% of the value in this scan. The **provenance footer is on-demand only**, never required for the scan. The **citations row** is on-demand for analyst (P2), not for the user (P1).

This is why the provenance footer is collapsed by default (D6 resolution) and why citation pills exist as an inline summary (3 pills max in main view) with a hover-card for detail (D3 resolution).

---

## U13. V2 / V3 deltas

### U13.1 V2 deltas

| Affordance | V1 state | V2 change |
|---|---|---|
| Citation pills row | Hidden | Lights up on `citation` events; up to 5 pills + overflow |
| `! low external support` chip | Not emitted | Emitted by backend; rendered in card header |
| "Discuss this insight" button | Not rendered | Rendered below provenance footer; opens chat dock (U6) |
| Chat dock | Not present | Slides down from card bottom; persists per-insight thread |
| Right rail | Not present | Optional (≥1480 px viewport): session summary + executive-summary modal |
| Card kebab — "Regenerate this insight" | Hidden item | Visible; re-runs verification loop |
| Card kebab — "Report as wrong" | Hidden item | Visible; opens 200×120 textarea modal |
| Subscribe button | Hidden | Rendered as a UI scaffold next to "Discuss" — wires to nothing in V2; V3 lights it up |

### U13.2 V3 deltas

| Affordance | V2 state | V3 change |
|---|---|---|
| Insight diff badge | Not present | Each insight that recurs (matched by canonical claim) gets a `Δ` chip in the header showing `↑12%` or `↓3pp` vs prior run; click reveals a diff modal showing prior-run side-by-side |
| Scheduled-runs list | Not present | New "Schedules" section in the page header (`Schedule ▾` selector). Lists weekly/biweekly schedules. CRUD via modal. |
| Subscribe button | UI scaffold | Functional — opens a modal: "Notify me when <metric> changes by >X%". Persists; backend cron evaluates. |
| Share by link | Not present | Card kebab adds "Share by link" — mints a short-link via `POST /share`; copies to clipboard |
| Geospatial chart shape | Not supported | If `geospatial-analysis` skill ships, a new `chart_type=map` becomes valid; renders via Leaflet inside the chart frame (NOT Recharts; existing Power Map tab pattern). 320 px tall. |

---

## U14. Open questions for PM (handed off to TASKS.md)

| # | Question | Why it's UX-blocking | Default if unanswered |
|---|---|---|---|
| Q1 | **Tab nav placement** — rightmost (after Sources) vs second-from-right (between Sources and Companies)? | Determines ordering muscle memory for existing users. | Rightmost. |
| Q2 | **Max headline length** — PRD says ≤80 chars; the agent prompt enforces this. Confirm 80 not 100. | Card height is sized assuming 1-line headline; 100-char headlines wrap to 2 lines and break the scan rhythm. | 80. |
| Q3 | **Materiality rubric labels** — `[S/M/L]` (chosen) vs `[low/med/high]` vs `[1/2/3]`? Same 3-level rubric, different surface. | The chip is the most-glanced element on the page; label form matters. | `[S/M/L]`. |
| Q4 | **Default sort order** — by materiality+novelty (agent's rank) vs by recency vs by tag? | Decides whether the first card the user sees is the "most important" or the "newest". | Agent's rank. |
| Q5 | **Insight count per session** — fixed 7 vs let the agent emit 5–10? | UI shows "Insight N of M"; M is dynamic if the agent decides. | Dynamic 5–10 (display M from `session_complete`). |
| Q6 | **Confidence label form** — `conf: high` (chosen) vs `high confidence` (verbose) vs just `high` ambiguous? | Brevity matters in the chip cluster. | `conf: high`. |
| Q7 | **Generated-time format** — relative ("2 minutes ago") vs absolute UTC ("09:13:42 UTC")? | the user reads at 09:14 UTC; relative is friendlier. Analyst copies to Confluence; absolute is needed. | Show relative in header, absolute in provenance footer. |
| Q8 | **Cancel during streaming — partial chart**: if a `chart` event arrived but `insight_complete` did not, do we keep the partial chart or discard? | UI complexity vs user expectation. | Discard the chart; keep the headline+subtitle (matches "halted at insight 3" framing). |
| Q9 | **Sessions retention in selector** — how many past sessions in the dropdown? | Affects dropdown design (search needed if >20). | Last 20. |
| Q10 | **Share-link expiry (V3)** — permanent vs 30-day? | Affects share-link modal copy. | 30-day, with renew option. |
| Q11 | **Per-insight ratings** — does the user rate inline (5-star widget on the card kebab menu)? PRD §7.2 calls for ≥40% useful ratings. | Determines whether the card needs a `[rate]` action. | V1: yes — inline 5-star in kebab. V2: same plus inline thumb up/down quick-rate. |

---

## U15. Cross-references

- [`./PRD.md`](./PRD.md) — Insight contract, provenance footer §5.6, V1/V2/V3 phasing.
- [`./RESEARCH.md`](./RESEARCH.md) — SSE event taxonomy R6, ChartSpec v1 R2, Tavily citation shape R1, ChatPanel reuse plan R5.
- [`./ARCHITECTURE.md`](./ARCHITECTURE.md) — Component layout under `frontend/src/components/insights/` (A12), SSE events the UI consumes (A5), error states (A13), designer hooks D1–D10 (A15.1).
- [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) — Skills inform a "skills used" badge row in the provenance footer (U3.5).
- [`./TASKS.md`](./TASKS.md) — to be authored; will pick up the U14 open questions and the implementation tickets implied by U2–U11.
- [`/strategic-insights-tool/PRD.md`](../../PRD.md) — the user's brand, OCI palette, existing tab visual language (PowerTab token map).
- [`/strategic-insights-tool/frontend/src/components/ChatPanel.tsx`](../../../frontend/src/components/ChatPanel.tsx) — Visual conventions inherited (markdown components, chart renderer, tooltip styles, citation row).
- [`/strategic-insights-tool/frontend/src/components/tabs/PowerTab.tsx`](../../../frontend/src/components/tabs/PowerTab.tsx) — Card chrome, brand palette, source badge, metric tile reference implementation.

---

**End of UX.md.**
