# UX Design: Data States, Lineage, and Mock-to-Real Transition
**Owner:** Product Design | **Status:** Draft v1.0 | **Date:** 2026-04-28

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Data State Visual System](#2-data-state-visual-system)
3. [Source Citation UX](#3-source-citation-ux)
4. [Data Freshness Indicators](#4-data-freshness-indicators)
5. [Tab-Level Data Quality Banner](#5-tab-level-data-quality-banner)
6. [Triangulation Tab Special UX](#6-triangulation-tab-special-ux)
7. [Mock-to-Real Transition Plan](#7-mock-to-real-transition-plan)
8. [Empty State Designs](#8-empty-state-designs)
9. [Design Tokens and Visual Language](#9-design-tokens-and-visual-language)
10. [Wireframes](#10-wireframes)
11. [Interaction States](#11-interaction-states)
12. [Accessibility Notes](#12-accessibility-notes)

---

## 1. Design Principles

These five principles govern every data presentation decision in the platform:

**P1 -- Never lie with plausible numbers.** A blank or "no data" state is always better than a random number that looks real. The current `mock_data.py` generates new random values on every page load. This is the single biggest trust problem. Every `random.*` call must be replaced with either sourced data or an explicit absence indicator.

**P2 -- Every number earns its place.** If a number appears on screen, it must be traceable to a primary source within two clicks. No number exists without a citation.

**P3 -- Absence is informative.** "No data" is not a failure -- it is intelligence. Knowing that no EDGAR filing exists for a company in a geography is a meaningful signal. Design the absence states to communicate why data is missing and when it might arrive.

**P4 -- Confidence is earned, not assigned.** Confidence scores reflect parsing certainty, not a random float between 0.7 and 0.98. The UI must make the basis of confidence visible and understandable.

**P5 -- Progressive disclosure of complexity.** Surface the key number first. Show the confidence indicator alongside it. Reveal source details, raw excerpts, and lineage metadata on demand (click/hover), not all at once.

---

## 2. Data State Visual System

The platform recognizes exactly four data states. Every datapoint on every tab falls into one of these four categories. There is no fifth category. There is no "mock data" state in production -- that state is eliminated entirely.

### State 1: Real Data (Pipeline-Sourced)

**Definition:** A datapoint backed by a live ingestion pipeline (SEC EDGAR, county permits, earnings transcripts, Aterio dataset). The pipeline retrieved it, parsed it, assigned a confidence score based on parsing certainty, and stored it with full lineage.

**Visual treatment:**

- Default theme styling -- no special badge or indicator. Real data is the expected state and should not draw attention to itself.
- Small citation link icon (12x12px) appears to the right of every numeric value. The icon uses `gray-500` color to stay unobtrusive until hovered.
- On hover over the value itself, show a tooltip with: `Retrieved: Apr 27, 2026, 14:32 UTC`
- Confidence indicator: a three-segment quality bar rendered inline after the value.
  - High confidence (>= 0.80): all three segments filled, color `green-600`
  - Medium confidence (0.50 - 0.79): two segments filled, color `yellow-500`
  - Low confidence (< 0.50): one segment filled, color `red-500`
- The confidence bar has a tooltip explaining the score: e.g., "High -- MW figure extracted from filing text with counterparty identified"

**Example rendering:**

```
  2.4 GW   [|||] [link-icon]
            ^confidence   ^citation
```

### State 2: Curated Data (Hand-Verified)

**Definition:** A datapoint from `curated_deals.py` -- hand-verified by the team with real SEC URLs, press release links, lat/lon coordinates, MW figures, and meaningful confidence scores (0.85-0.99). This is the highest-trust data in the system.

**Visual treatment:**

- Subtle inline badge: a small checkmark icon followed by the word "Verified" in `blue-600` text, rendered at 11px font size, positioned below or beside the value.
- The badge is not a large pill or tag -- it is small enough to avoid visual clutter but visible enough to signal elevated trust.
- Source link icon is always present (same as State 1) but uses `blue-600` instead of `gray-500`.
- No confidence bar needed -- curated data is implicitly high confidence. However, the source popover still shows the confidence score and its basis ("Hand-verified from SEC filing URL").
- Border-left accent: when curated data appears in a table row or card, a 3px left border in `blue-500` distinguishes it.

**Example rendering:**

```
  500 MW   [check] Verified   [link-icon]
           ^blue accent        ^blue link
```

### State 3: No Data Available

**Definition:** The pipeline has looked for data and either (a) found nothing, (b) the source does not cover this entity/geography, or (c) ingestion has not yet reached this entity/geography but is planned. This state explicitly replaces every current `random.*` generation in `mock_data.py`.

**Visual treatment:**

- The cell, card, or chart area where a number would appear instead shows a centered em-dash followed by a reason string.
- Text color: `gray-400` for the em-dash, `gray-500` for the reason text.
- Font: reason text in 12px, italic.
- Background: `gray-50` fill.
- Border: 1px dashed `gray-300`.
- If a timeline is known for when data is expected, show it: "Data expected by [date]" in `gray-500`.
- No zeros. No blank spaces. No random numbers. The absence is always explained.

**Reason strings by context (exhaustive list for Phase 1):**

| Context | Reason String |
|---------|--------------|
| Power tab, company has no EDGAR filings for a geography | "No power contracts found in EDGAR filings for [Company] in [Region]" |
| Power tab, geography outside Phase 1 scope | "Data ingestion not yet configured for [Region]. Northern Virginia available now." |
| Permits tab, county has no datacenter permits | "No datacenter-related permits found in [County]. Next weekly ingestion: [date]." |
| Permits tab, county outside Phase 1 scope | "Permit monitoring covers Loudoun and Prince William counties. [County] planned for Phase 2." |
| GPU Supply tab, missing quarter | "Transcript data not yet ingested for [Quarter]. Expected after earnings call on [date]." |
| GPU Supply tab, derived metric unavailable | "GPU unit estimate requires NVIDIA datacenter revenue. Earnings data pending." |
| NICs/Optics tab (entire tab in Phase 1) | See State 4 below -- this is a "Coming Soon" state. |
| Triangulation, missing layer | "Incomplete -- missing [Layer Name]. Cannot compute gap without this input." |

**Example rendering:**

```
  +- - - - - - - - - - - - - - - - - - -+
  |                                       |
  |    --  No power contracts found in    |
  |        EDGAR filings for Meta in      |
  |        Northern Virginia              |
  |                                       |
  |    Data expected by: Jun 2026         |
  |                                       |
  +- - - - - - - - - - - - - - - - - - -+
       ^dashed border, gray-50 bg
```

### State 4: Coming Soon (Feature Planned, Not Built)

**Definition:** An entire tab, section, or feature that is on the roadmap but has no implementation yet. Specifically in Phase 1: the Satellite imagery analysis, NICs/Optics data, and TSMC packaging data are in this state. The satellite metadata (site coordinates and milestones from `get_satellite_sites()`) is real and should render normally -- only the imagery and change detection are "Coming Soon."

**Visual treatment:**

- The content area renders a blurred placeholder. Use CSS `filter: blur(4px)` on a static representative layout (not random data -- use a fixed illustrative screenshot or a gray placeholder grid).
- Centered overlay text: "Coming in Phase 2" in `gray-600`, 18px semibold, on a `white/90%` translucent backdrop.
- Below the overlay text, a single line: "Satellite imagery change detection is planned for Q3 2026" (or equivalent timeline).
- A small clock icon (`gray-500`, 16px) appears next to the "Coming in Phase 2" text.
- No numbers of any kind. No charts. No tables with data. The blurred placeholder is purely decorative to suggest the shape of the future feature.
- Border: 1px dotted `gray-200` around the entire section.

**Example rendering:**

```
  +...................................+
  |  //////////////////////////////// |
  |  //  [blurred placeholder]    // |
  |  //////////////////////////////// |
  |                                   |
  |    [clock]  Coming in Phase 2     |
  |                                   |
  |    Satellite imagery change       |
  |    detection planned for Q3 2026  |
  |                                   |
  +...................................+
       ^dotted border, gray-200
```

**Per-tab Phase 1 state mapping:**

| Tab | State |
|-----|-------|
| Power | State 1 (real) for NoVA + curated deals; State 3 (no data) for other geos |
| Satellite | Site metadata = State 2 (curated real data); Imagery/change detection = State 4 |
| GPU Supply | State 1 (real) for NVIDIA quarters with data; State 3 for missing quarters |
| NICs/Optics | State 4 (entire tab) |
| TSMC | State 1 (real) for ingested quarters; State 3 for missing quarters |
| Permits | State 1 (real) for Loudoun/PWC; State 3 for other counties |
| Triangulation | Mixed -- see Section 6 |
| Sources | State 1 (always real -- reflects actual pipeline status) |

---

## 3. Source Citation UX

### Citation Link Icon

Every numeric value in the platform that is backed by data (State 1 or State 2) has a citation link icon. This is the primary interaction for verifying a datapoint.

**Icon specification:**

- Icon: external-link variant, 12x12px
- Color: `gray-500` default; `blue-600` on hover; `blue-600` always for curated data
- Position: 4px to the right of the value, vertically centered
- Cursor: pointer on hover
- Tooltip on hover (before click): "View source"

### Source Detail Popover

Clicking the citation icon opens a popover anchored to the icon. The popover appears to the right of the icon by default, shifting left if near the viewport edge.

**Popover layout (single source):**

```
+----------------------------------------------+
|  SOURCE DETAIL                          [x]  |
+----------------------------------------------+
|                                              |
|  Source:     SEC EDGAR 8-K                   |
|  Filed:      Apr 15, 2026                    |
|  Retrieved:  Apr 16, 2026, 03:22 UTC         |
|  Parser:     v1.2.0                          |
|                                              |
|  Confidence: [|||] High (0.87)               |
|  Basis: MW figure extracted from filing text  |
|         with counterparty identified and      |
|         energy source classified              |
|                                              |
|  +----------------------------------------+ |
|  | EXCERPT FROM SOURCE                     | |
|  | "...Microsoft has entered into a power  | |
|  | purchase agreement with Dominion Energy  | |
|  | for approximately 500 megawatts of      | |
|  | renewable energy capacity in Loudoun    | |
|  | County, Virginia..."                    | |
|  +----------------------------------------+ |
|                                              |
|  [Open Filing on SEC.gov ->]                 |
|                                              |
+----------------------------------------------+
```

**Popover fields:**

| Field | Description | Always shown? |
|-------|-------------|---------------|
| Source name | Human-readable name, e.g., "SEC EDGAR 8-K", "Curated Deal", "Shovels.ai Permit" | Yes |
| Source URL | Clickable link, opens in new tab. Full URL displayed truncated with ellipsis at 60 chars. | Yes |
| Filing/effective date | The date the source document applies to (filing date, permit date, etc.) | Yes |
| Retrieved timestamp | UTC datetime when the pipeline fetched this data | Yes |
| Parser version | Semantic version string, e.g., "v1.2.0" | Yes |
| Confidence score | Numeric (0.87) with quality bar and tier label (High/Medium/Low) | Yes |
| Confidence basis | 1-2 sentence explanation of how confidence was computed | Yes |
| Raw excerpt | Up to 500 characters of the source text that was parsed. Rendered in a monospace font, light gray background, with the key extracted value highlighted in yellow. | Yes, if available |
| "Open source" button | Primary action button, opens source URL in new tab | Yes |

**Popover for aggregated numbers:**

When a displayed number is the sum of multiple source records (e.g., "Total GW for Microsoft in Virginia" sums across multiple EDGAR filings and curated deals), the popover shows a list of contributing sources:

```
+----------------------------------------------+
|  SOURCE DETAIL (3 sources)              [x]  |
+----------------------------------------------+
|                                              |
|  Total: 2.4 GW                               |
|  Aggregation: Sum of 3 records               |
|                                              |
|  1. Curated Deal #14              500 MW     |
|     [check] Verified | Confidence: 0.95      |
|     Microsoft-Dominion PPA, Loudoun County    |
|     [View source ->]                         |
|                                              |
|  2. SEC EDGAR 8-K (2025-11-03)    1,200 MW   |
|     Confidence: [|||] 0.87                   |
|     "...1.2 GW renewable energy..."          |
|     [View source ->]                         |
|                                              |
|  3. SEC EDGAR 8-K (2026-02-14)    700 MW     |
|     Confidence: [||.] 0.72                   |
|     "...approximately 700 megawatts..."      |
|     [View source ->]                         |
|                                              |
+----------------------------------------------+
```

**Behavior notes:**

- Only one popover open at a time. Opening a new one closes the previous.
- Popover closes on click outside, Escape key, or explicit close button.
- Popover width: 400px fixed. Height: auto, max 480px with scroll.
- On mobile/narrow viewports: popover becomes a bottom drawer (slide up from bottom, 100% width).

---

## 4. Data Freshness Indicators

### Per-Source Freshness Badge

Each tab that consumes a data source shows a freshness badge indicating when that source was last successfully ingested. The badge appears in the tab-level quality banner (see Section 5) and on the Sources tab.

**Freshness tiers and colors:**

| Source Type | Green (Fresh) | Yellow (Aging) | Red (Stale) |
|-------------|--------------|----------------|-------------|
| SEC EDGAR filings | < 24 hours since last check | 24 - 72 hours | > 72 hours |
| County permits | < 7 days since last ingestion | 7 - 14 days | > 14 days |
| Earnings transcripts | < 72 hours after earnings call date | 72 hours - 7 days | > 7 days after call |
| Aterio dataset | < 30 days since last upload | 30 - 60 days | > 60 days |
| Curated deals | Always green (manually maintained) | N/A | N/A |

**Badge rendering:**

```
  [green-dot] SEC EDGAR: Updated 2h ago
  [yellow-dot] Permits: Updated 5 days ago
  [red-dot] Earnings: Last ingestion 8 days ago -- stale
```

- Dot: 8px circle, filled with the tier color
- Text: 12px, `gray-600`
- "Stale" label in `red-600` bold when the source is in the red tier
- Clicking the badge navigates to the Sources tab filtered to that source

### Global Data Health Bar

A thin (4px tall) bar in the application header, below the navigation tabs, provides an at-a-glance view of overall pipeline health.

**Rendering:**

- The bar is divided into segments proportional to the number of active data sources.
- Each segment is colored according to that source's freshness tier (green/yellow/red).
- Hovering over the bar shows a tooltip: "Pipeline Health: 3 of 5 sources fresh, 1 aging, 1 stale"
- Clicking the bar navigates to the Sources tab.

**Bar layout example:**

```
  [=====green=====][==yellow==][=red=]
   SEC EDGAR       Permits     Earnings
```

- If all sources are green, the entire bar is green -- the healthiest state.
- If any source is red, the bar includes a red segment -- the user immediately sees degradation.

### Pipeline Status Endpoint Display

The Sources tab shows a detailed pipeline health dashboard sourced from the `/api/pipeline/health` endpoint. This replaces the current `get_sources_data()` and `get_agent_status()` mock data.

**Sources tab layout per source:**

```
+----------------------------------------------+
|  SEC EDGAR 8-K                               |
|  Status: [green-dot] Healthy                 |
|                                              |
|  Last successful run:  Apr 28, 2026 06:00    |
|  Records ingested:     1,247                 |
|  Next scheduled run:   Apr 28, 2026 12:00    |
|  Error count (7d):     0                     |
|                                              |
|  Feeds tabs: Power, Triangulation (L1)       |
+----------------------------------------------+
```

---

## 5. Tab-Level Data Quality Banner

Every tab (Power, Permits, GPU Supply, TSMC, Satellite, Triangulation) displays a banner at the top of its content area. This banner provides immediate context about the quality and completeness of data on that tab.

### Banner Layout

```
+----------------------------------------------------------------------+
|  [info-icon]  Power Tab: 3 of 5 companies have real data for NoVA    |
|               Sources: SEC EDGAR, Curated Deals                      |
|               Last updated: 2h ago                                   |
|               [View all sources ->]                                  |
+----------------------------------------------------------------------+
```

**Banner fields:**

| Field | Content | Example |
|-------|---------|---------|
| Data completeness | "[N] of [M] [entities] have real data [for geography]" | "3 of 5 companies have real data for NoVA" |
| Sources | List of data source names feeding this tab | "Sources: SEC EDGAR, Curated Deals" |
| Last updated | Most recent ingestion timestamp across all sources on this tab | "Last updated: 2h ago" |
| Link | "View all sources" link to Sources tab | Navigates to Sources tab |

**Banner styling:**

- Background: `blue-50`
- Border: 1px solid `blue-200`
- Border-radius: 8px
- Padding: 12px 16px
- Icon: info circle in `blue-500`
- Dismiss: the banner can be collapsed to a single-line summary via a chevron toggle. Collapsed state persists per session.

**Banner variants by data completeness:**

| Completeness | Background | Border | Icon |
|--------------|-----------|--------|------|
| >= 80% real data | `blue-50` | `blue-200` | info-circle, `blue-500` |
| 40% - 79% real data | `yellow-50` | `yellow-200` | alert-triangle, `yellow-600` |
| < 40% real data | `orange-50` | `orange-200` | alert-circle, `orange-600` |
| 0% real data (Coming Soon tab) | `gray-50` | `gray-200` | clock, `gray-500` |

**Per-tab banner content (Phase 1):**

| Tab | Banner Text |
|-----|-------------|
| Power | "Power Tab: 3 of 5 companies have real data for NoVA / Sources: SEC EDGAR, Curated Deals / Last updated: [time]" |
| Satellite | "Satellite Tab: Site metadata available for 16 sites / Imagery and change detection coming in Phase 2 / Source: Curated site data" |
| GPU Supply | "GPU Supply Tab: NVIDIA data available for [N] of 8 quarters / Source: SEC EDGAR 10-Q / Last updated: [time]" |
| NICs/Optics | "NICs and Optics Tab: Data sources not yet integrated / Broadcom, Coherent, Lumentum ingestion planned for Phase 2" |
| TSMC | "TSMC Tab: Data available for [N] of 8 quarters / Source: SEC EDGAR 10-Q / Last updated: [time]" |
| Permits | "Permits Tab: Loudoun and Prince William counties monitored / [N] datacenter permits tracked / Last updated: [time]" |
| Triangulation | "Triangulation: L1 (Power) real, L2 (GPU) real with assumptions, L3 (NICs) not available, L4 (Permits) real for NoVA" |
| Sources | No banner needed -- this tab IS the data quality view |

---

## 6. Triangulation Tab Special UX

The triangulation tab is the most complex view in the platform. It combines four data layers to answer Karan's core question: "Is there enough power being contracted to actually run all the GPUs being shipped?" The UX must make the inputs, assumptions, and gaps transparent.

### Layer Stack Visualization

The four triangulation layers are presented as a vertical stack, with L1 at the top and L4 at the bottom. Each layer is a horizontal bar that shows its data completeness.

```
+----------------------------------------------------------------------+
|  TRIANGULATION: Northern Virginia                                     |
+----------------------------------------------------------------------+
|                                                                      |
|  L1  Contracted Power                                                |
|  [========================================] 100%  2.4 GW             |
|  Sources: 3 EDGAR filings, 2 curated deals                          |
|  Confidence: [|||] High (0.91)                                       |
|                                                                      |
|  L2  Estimated GPU Power Draw                                        |
|  [================================........] 80%   1.8 GW (est.)     |
|  Sources: NVIDIA 10-Q (6 of 8 quarters)                             |
|  Confidence: [||.] Medium (0.68) -- derived metric, assumptions      |
|  [Adjust assumptions v]                                              |
|                                                                      |
|  L3  NIC/Optics Validation                                          |
|  [........................................]  0%   -- No data          |
|  Not available -- Broadcom/Coherent/Lumentum ingestion in Phase 2    |
|                                                                      |
|  L4  County Permit Signals                                           |
|  [========================================] 100%  47 permits         |
|  Sources: Loudoun County (32), Prince William County (15)            |
|  Confidence: [|||] High (0.85)                                       |
|                                                                      |
+----------------------------------------------------------------------+
|                                                                      |
|  RESULT                                                              |
|                                                                      |
|  Power Gap: +0.6 GW  (Contracted exceeds estimated GPU demand)       |
|  Status: Overbuild                                                   |
|  Overall Confidence: [||.] Medium (0.68)                             |
|  Note: Missing L3 (NIC/optics) -- gap estimate is incomplete         |
|                                                                      |
|  Error Range: +0.2 GW to +1.1 GW                                    |
|  (reflects uncertainty in GPU ASP, utilization, and power draw)      |
|                                                                      |
+----------------------------------------------------------------------+
```

**Layer bar color coding:**

- Green fill (`green-500`): data available and fresh
- Gray fill (`gray-200`): no data
- Yellow fill (`yellow-400`): data available but stale or low confidence

**Completeness percentage:** Calculated as (number of entities with data) / (total expected entities). For L1: (companies with power data in this geo) / (total tracked companies). For L2: (quarters with earnings data) / (total quarters in range). For L4: (counties with permit data) / (total counties in geo).

### Incomplete Triangulation Handling

When any layer has no data, the triangulation result must clearly indicate incompleteness rather than presenting a confident-looking number.

**Rules:**

1. If L1 (power) has no data: "Cannot compute gap -- no contracted power data for [geography]." No gap number shown.
2. If L2 (GPU) has no data: "Cannot compute gap -- no GPU deployment estimate available." No gap number shown.
3. If L3 (NICs/optics) has no data: Gap number IS shown, but with a caveat: "Note: Missing L3 (NIC/optics validation). Gap estimate is unvalidated." The result confidence is capped at Medium.
4. If L4 (permits) has no data: Gap number IS shown, but with a caveat: "Note: Missing L4 (permit ground truth). Gap estimate is not corroborated by construction activity." The result confidence is capped at Medium.
5. If both L3 and L4 are missing: Result confidence is capped at Low, regardless of L1/L2 confidence.

### Assumption Sliders (L2)

Layer 2 (GPU power draw) depends on assumptions that the user should be able to adjust. The sliders appear in an expandable panel below the L2 bar.

**Slider panel layout:**

```
+----------------------------------------------+
|  ASSUMPTIONS (Layer 2)                       |
+----------------------------------------------+
|                                              |
|  GPU Model Mix                               |
|  H100 (700W TDP)    [======|====] 60%       |
|  B200 (1000W TDP)   [====|======] 40%       |
|                                              |
|  Average Power per GPU                       |
|  [==========|==========] 820 W               |
|  Range: 500W ------------- 1200W             |
|                                              |
|  Utilization Rate                            |
|  [============|========] 65%                 |
|  Range: 30% --------------- 95%              |
|                                              |
|  GPU ASP (for revenue-to-units derivation)   |
|  [==========|==========] $25,000             |
|  Range: $15,000 ---------- $40,000           |
|                                              |
|  [Reset to defaults]                         |
|                                              |
+----------------------------------------------+
```

**Slider behavior:**

- Adjusting any slider immediately recalculates the L2 estimate and the gap result. The recalculation is client-side (no API call needed -- the formula is simple multiplication).
- Changed values are highlighted with a `yellow-100` background to indicate deviation from defaults.
- "Reset to defaults" button restores all sliders to the default values defined in the pipeline config.
- The error range on the triangulation result widens or narrows based on how far the assumptions deviate from defaults.

### Error Bars on Triangulation Output

The gap result shows an error range reflecting the cumulative uncertainty of all input layers.

**Error range calculation (displayed, not hidden):**

```
  Gap = L1_power - L2_gpu_power
  Error_low  = (L1_power * L1_confidence_low)  - (L2_gpu_power * L2_confidence_high)
  Error_high = (L1_power * L1_confidence_high) - (L2_gpu_power * L2_confidence_low)
```

**Visual rendering:**

```
  Power Gap: +0.6 GW
             |----[====X====]----|
           +0.2                +1.1
           low estimate        high estimate
```

- The center mark (X) is the point estimate.
- The bar represents the error range.
- Green bar if gap is positive (overbuild), red bar if gap is negative (constrained).

---

## 7. Mock-to-Real Transition Plan

### Current State Inventory

Based on `mock_data.py`, the following functions currently generate random data on every page load:

| Function | Random calls | Replacement |
|----------|-------------|-------------|
| `get_power_data()` | ~210 random values (70 rows x 3 per row) | Pipeline (EDGAR + curated) for NoVA; State 3 for other geos |
| `get_power_timeseries()` | ~60 random values | Pipeline time-series; State 3 for gaps |
| `get_gpu_data()` | ~50+ random values | NVIDIA earnings for available quarters; State 3 for gaps |
| `get_nics_optics_data()` | ~40 random values | State 4 (Coming Soon) -- entire tab |
| `get_tsmc_data()` | ~40 random values | TSMC earnings for available quarters; State 3 for gaps |
| `get_permits_data()` | ~40 random values | Real permits for Loudoun/PWC; State 3 for other counties |
| `get_triangulation_data()` | ~24 random values | Pipeline-fed triangulation for NoVA; State 3 for other regions |
| `get_satellite_sites()` | 0 (already real) | Keep as-is; add State 4 for imagery features |
| `get_sources_data()` | 0 (static mock) | Replace with live `/api/pipeline/health` |
| `get_agent_status()` | 0 (static mock) | Replace with live pipeline status |

### Phase 1 Transition (Week by Week)

**Week 1-2: Foundation**
- Implement the four data state components in the frontend (State 1, 2, 3, 4 visual treatments).
- Replace `get_sources_data()` and `get_agent_status()` with live pipeline health endpoint.
- Sources tab becomes fully real.
- All other tabs: gate `mock_data.py` behind `MOCK_DATA=1` env flag (default: off). When off, tabs show State 3 ("No data -- pipeline not yet connected") instead of random numbers.
- This is the critical moment: the dashboard will look emptier but will be honest.

**Week 3: Power Tab Goes Live**
- EDGAR adapter delivers real filing data for NoVA.
- Curated deals wrapped in adapter interface.
- Power tab for NoVA shows real data (State 1 + State 2).
- Power tab for other geographies shows State 3 with reason: "Data ingestion not yet configured for [Region]."
- Power timeseries: real for quarters with data, State 3 for gaps.

**Week 4: Permits + Earnings Go Live**
- Permits tab shows real Loudoun/PWC data. Other counties show State 3.
- GPU Supply tab shows NVIDIA data for available quarters. Missing quarters show State 3.
- TSMC tab shows data for available quarters. Missing quarters show State 3.
- NICs/Optics tab shows State 4 (Coming Soon).

**Week 5: Triangulation Goes Live**
- Triangulation for NoVA computed from real L1 + L2 + L4. L3 shows "not available."
- Assumption sliders wired up.
- Error bars displayed.
- Other regions show State 3: "Triangulation requires data for all layers. [Region] data not yet ingested."

**Week 6: Polish + Demo**
- All citation links wired to source popovers.
- Freshness indicators live.
- Tab-level quality banners live.
- Global health bar live.
- `mock_data.py` remains in codebase but gated behind env flag, all random calls removed from production paths.

### Transition Rules (Non-Negotiable)

1. **No silent mixing.** At no point during the transition does real data appear alongside mock data in the same tab without explicit labeling. If a tab is partially real, the quality banner states exactly which entities have real data.

2. **No "looks real" mock data.** During transition, if a data source is not yet connected, the UI shows State 3 or State 4 -- never a plausible-looking number. The current behavior where `random.uniform(0.7, 0.98)` generates fake confidence scores is eliminated in Week 1.

3. **Honest emptiness over impressive fakery.** The dashboard will look sparser during the transition. This is intentional and correct. A sparse dashboard with real data builds more trust than a full dashboard with random numbers.

4. **Progressive enrichment.** As each data source comes online, the corresponding tab transitions from State 3/4 to State 1, and the tab-level quality banner percentages increase. This is a visible and satisfying progression.

---

## 8. Empty State Designs

Each major view has a specific empty state design. Empty states are not generic -- they explain what data is expected, why it is absent, and when it might arrive.

### Power Map -- No Data for a Company/Region

```
+----------------------------------------------------------------------+
|  POWER: Microsoft in Northern Virginia                                |
+----------------------------------------------------------------------+
|                                                                      |
|  +- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -+   |
|  |                                                               |   |
|  |     [search-icon]                                             |   |
|  |                                                               |   |
|  |     No power contracts found in EDGAR filings                 |   |
|  |     for Microsoft in Northern Virginia                        |   |
|  |                                                               |   |
|  |     What we checked:                                          |   |
|  |     - SEC EDGAR 8-K filings (2023-present)     [0 results]    |   |
|  |     - Curated deals database                   [0 matches]    |   |
|  |     - Aterio dataset                           [0 matches]    |   |
|  |                                                               |   |
|  |     Next EDGAR check: Apr 29, 2026, 06:00 UTC                |   |
|  |                                                               |   |
|  +- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -+   |
|                                                                      |
+----------------------------------------------------------------------+
```

### Permits Tab -- No Permits for a County

```
+----------------------------------------------------------------------+
|  PERMITS: Maricopa County, AZ                                         |
+----------------------------------------------------------------------+
|                                                                      |
|  +- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -+   |
|  |                                                               |   |
|  |     [building-icon]                                           |   |
|  |                                                               |   |
|  |     No datacenter-related permits found                       |   |
|  |     in Maricopa County                                        |   |
|  |                                                               |   |
|  |     Permit monitoring covers Loudoun County, VA and           |   |
|  |     Prince William County, VA in Phase 1.                     |   |
|  |                                                               |   |
|  |     Maricopa County is planned for Phase 2 (Q4 2026).         |   |
|  |                                                               |   |
|  +- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -+   |
|                                                                      |
+----------------------------------------------------------------------+
```

For Loudoun/PWC with zero results:

```
|     No datacenter-related permits found                       |
|     in Loudoun County for [date range]                        |
|                                                               |
|     This county is actively monitored. Check back after       |
|     the next weekly ingestion on [date].                      |
```

### GPU Supply -- Missing Quarters

```
+----------------------------------------------------------------------+
|  GPU SUPPLY: NVIDIA Datacenter Revenue                                |
+----------------------------------------------------------------------+
|                                                                      |
|  Q1 2023  $4.3B   [|||] [link]                                      |
|  Q2 2023  $10.3B  [|||] [link]                                      |
|  Q3 2023  $14.5B  [|||] [link]                                      |
|  Q4 2023  $18.4B  [|||] [link]                                      |
|  Q1 2024  $22.6B  [|||] [link]                                      |
|  Q2 2024  $26.3B  [||.] [link]                                      |
|  Q3 2024  +- - - - - - - - - - - - - - - - - - - -+                 |
|           | -- Transcript not yet ingested for      |                 |
|           |    Q3 2024. Expected after earnings     |                 |
|           |    call on Nov 20, 2024.                |                 |
|           +- - - - - - - - - - - - - - - - - - - -+                 |
|  Q4 2024  +- - - - - - - - - - - - - - - - - - - -+                 |
|           | -- Data not yet available for Q4 2024.  |                 |
|           |    10-Q expected Feb 2025.              |                 |
|           +- - - - - - - - - - - - - - - - - - - -+                 |
|                                                                      |
+----------------------------------------------------------------------+
```

### Satellite Tab -- No Imagery

The satellite tab has a split design: site metadata (which is real) renders normally, while imagery features show State 4.

```
+----------------------------------------------------------------------+
|  SATELLITE: Microsoft Goodyear Campus                                 |
+----------------------------------------------------------------------+
|                                                                      |
|  SITE METADATA  [check] Verified                                     |
|  Location: Goodyear, Arizona (33.4373, -112.3576)                    |
|  Size: 279 acres                                                     |
|  Status: Active Construction (45%)                                   |
|  Announced: May 2024                                                 |
|  Source: Microsoft Blog  [link]                                      |
|                                                                      |
|  MILESTONES                                                          |
|  [timeline visualization with 7 milestones]                          |
|                                                                      |
|  IMAGERY & CHANGE DETECTION                                          |
|  +...............................................................+  |
|  |  //////////////////////////////////////////////////////////// |  |
|  |  //  [blurred satellite imagery placeholder]              // |  |
|  |  //////////////////////////////////////////////////////////// |  |
|  |                                                               |  |
|  |     [clock]  Coming in Phase 2                                |  |
|  |                                                               |  |
|  |     Satellite imagery and automated change detection          |  |
|  |     are planned for Q3 2026 pending vendor selection          |  |
|  |     (Planet Labs or Maxar).                                   |  |
|  |                                                               |  |
|  +...............................................................+  |
|                                                                      |
+----------------------------------------------------------------------+
```

### Triangulation -- Incomplete Layers

```
+----------------------------------------------------------------------+
|  TRIANGULATION: Northern Virginia                                     |
+----------------------------------------------------------------------+
|                                                                      |
|  [alert-triangle]  Incomplete Analysis                               |
|                                                                      |
|  This triangulation is missing 1 of 4 data layers.                   |
|  The gap estimate is shown but should be treated as preliminary.      |
|                                                                      |
|  L1  Contracted Power    [====] Real    2.4 GW                       |
|  L2  GPU Power Draw      [====] Real    1.8 GW (est.)               |
|  L3  NIC/Optics          [----] Missing                              |
|  L4  Permit Signals      [====] Real    47 permits                   |
|                                                                      |
|  Gap: +0.6 GW (Overbuild)                                           |
|  Confidence: Medium (capped -- L3 missing)                           |
|  Error range: +0.2 to +1.1 GW                                       |
|                                                                      |
+----------------------------------------------------------------------+
```

---

## 9. Design Tokens and Visual Language

### Color Tokens

| Token Name | Hex Value | Usage |
|-----------|-----------|-------|
| `--color-real-default` | (inherit from theme) | Real data text and values -- uses default theme colors |
| `--color-curated-accent` | `#2563EB` (blue-600) | Curated data badge, link icon, left border accent |
| `--color-curated-bg` | `#EFF6FF` (blue-50) | Curated data row highlight background |
| `--color-curated-border` | `#BFDBFE` (blue-200) | Curated data subtle border |
| `--color-nodata-text` | `#6B7280` (gray-500) | "No data" reason text |
| `--color-nodata-dash` | `#9CA3AF` (gray-400) | Em-dash in no-data cells |
| `--color-nodata-bg` | `#F9FAFB` (gray-50) | No-data cell background |
| `--color-nodata-border` | `#D1D5DB` (gray-300) | No-data dashed border |
| `--color-coming-border` | `#E5E7EB` (gray-200) | Coming-soon dotted border |
| `--color-coming-text` | `#4B5563` (gray-600) | Coming-soon overlay text |
| `--color-confidence-high` | `#16A34A` (green-600) | Confidence bar -- high tier |
| `--color-confidence-med` | `#EAB308` (yellow-500) | Confidence bar -- medium tier |
| `--color-confidence-low` | `#DC2626` (red-600) | Confidence bar -- low tier |
| `--color-fresh-green` | `#16A34A` (green-600) | Freshness dot -- fresh |
| `--color-fresh-yellow` | `#EAB308` (yellow-500) | Freshness dot -- aging |
| `--color-fresh-red` | `#DC2626` (red-600) | Freshness dot -- stale |
| `--color-banner-info-bg` | `#EFF6FF` (blue-50) | Quality banner -- high completeness |
| `--color-banner-warn-bg` | `#FFFBEB` (yellow-50) | Quality banner -- medium completeness |
| `--color-banner-alert-bg` | `#FFF7ED` (orange-50) | Quality banner -- low completeness |
| `--color-excerpt-bg` | `#F3F4F6` (gray-100) | Source excerpt background in popover |
| `--color-excerpt-highlight` | `#FEF08A` (yellow-200) | Highlighted extracted value in excerpt |

### Typography Tokens

| Token Name | Value | Usage |
|-----------|-------|-------|
| `--font-value` | 16px / 600 (semibold) | Primary data values (GW, MW, $B) |
| `--font-value-unit` | 14px / 400 (normal) | Unit labels next to values (GW, MW) |
| `--font-confidence-label` | 11px / 400 (normal) | Confidence score text below values |
| `--font-badge` | 11px / 500 (medium) | "Verified" badge text |
| `--font-nodata-reason` | 12px / 400 (italic) | No-data reason string |
| `--font-nodata-dash` | 18px / 300 (light) | Em-dash in no-data cells |
| `--font-coming-overlay` | 18px / 600 (semibold) | "Coming in Phase 2" overlay text |
| `--font-coming-detail` | 13px / 400 (normal) | Timeline detail below "Coming in Phase 2" |
| `--font-excerpt` | 13px / 400 (monospace) | Raw source excerpt in popover |
| `--font-stale-indicator` | 12px / 400 (italic) | Stale data timestamp rendering |
| `--font-popover-heading` | 12px / 600 (semibold, uppercase) | "SOURCE DETAIL" heading in popover |
| `--font-popover-label` | 12px / 500 (medium) | Field labels in popover (Source, Filed, etc.) |
| `--font-popover-value` | 13px / 400 (normal) | Field values in popover |
| `--font-banner-primary` | 13px / 500 (medium) | Tab quality banner primary text |
| `--font-banner-secondary` | 12px / 400 (normal) | Tab quality banner secondary text (sources, timestamp) |

### Spacing Tokens

| Token Name | Value | Usage |
|-----------|-------|-------|
| `--space-citation-gap` | 4px | Gap between value and citation icon |
| `--space-confidence-gap` | 6px | Gap between value and confidence bar |
| `--space-badge-gap` | 4px | Gap between checkmark icon and "Verified" text |
| `--space-curated-border-width` | 3px | Left border accent width for curated data rows |
| `--space-nodata-padding` | 16px 20px | Padding inside no-data cells |
| `--space-popover-padding` | 16px | Padding inside source popover |
| `--space-popover-width` | 400px | Fixed width of source popover |
| `--space-popover-max-height` | 480px | Max height before scroll |
| `--space-banner-padding` | 12px 16px | Padding inside quality banner |
| `--space-banner-radius` | 8px | Border radius of quality banner |
| `--space-slider-height` | 4px | Height of assumption slider track |
| `--space-slider-thumb` | 16px | Diameter of slider thumb |
| `--space-health-bar-height` | 4px | Height of global health bar |
| `--space-freshness-dot` | 8px | Diameter of freshness indicator dot |
| `--space-layer-bar-height` | 24px | Height of triangulation layer completeness bar |

### Border Tokens

| Token Name | Value | Usage |
|-----------|-------|-------|
| `--border-real` | 1px solid `gray-200` | Default border for real data containers |
| `--border-curated-left` | 3px solid `blue-500` | Left accent border for curated data rows |
| `--border-nodata` | 1px dashed `gray-300` | Border for no-data cells and containers |
| `--border-coming` | 1px dotted `gray-200` | Border for coming-soon sections |
| `--border-popover` | 1px solid `gray-200` | Border for source detail popover |
| `--border-banner` | 1px solid (varies by tier) | Border for quality banner |
| `--border-excerpt` | 1px solid `gray-200` | Border around raw excerpt block in popover |

### Shadow Tokens

| Token Name | Value | Usage |
|-----------|-------|-------|
| `--shadow-popover` | `0 4px 12px rgba(0,0,0,0.15)` | Source detail popover shadow |
| `--shadow-slider-thumb` | `0 1px 3px rgba(0,0,0,0.2)` | Assumption slider thumb shadow |

### Icon Specifications

| Icon | Size | Color | Usage |
|------|------|-------|-------|
| Citation link | 12x12px | `gray-500` / `blue-600` on hover | Clickable source link next to every value |
| Verified checkmark | 12x12px | `blue-600` | Badge for curated data |
| No-data dash | Rendered as text em-dash | `gray-400` | Placeholder in no-data cells |
| Coming-soon clock | 16x16px | `gray-500` | Icon in "Coming in Phase 2" overlay |
| Confidence bar segment | 6x12px each (3 segments) | green/yellow/red per tier | Inline confidence indicator |
| Freshness dot | 8x8px circle | green/yellow/red per tier | Data source freshness |
| Info circle | 16x16px | `blue-500` | Quality banner icon (high completeness) |
| Alert triangle | 16x16px | `yellow-600` | Quality banner icon (medium completeness) |
| Alert circle | 16x16px | `orange-600` | Quality banner icon (low completeness) |
| Search icon | 24x24px | `gray-400` | Empty state -- "no results found" |
| Building icon | 24x24px | `gray-400` | Empty state -- "no permits" |

---

## 10. Wireframes

### 10.1 Power Tab Wireframe (NoVA, Mixed States)

```
+======================================================================+
|  [logo]  Datacenter & Power Intelligence Platform                     |
+======================================================================+
|  [====green====][====green====][=yellow=][=====green=====]  <- health bar
+----------------------------------------------------------------------+
|  Power | Satellite | GPU Supply | NICs | TSMC | Permits | Tri | Src  |
|  [===]                                                               |
+----------------------------------------------------------------------+
|                                                                      |
|  +----------------------------------------------------------------+  |
|  | [i] Power Tab: 3 of 5 companies have real data for NoVA        |  |
|  |     Sources: SEC EDGAR, Curated Deals | Last updated: 2h ago   |  |
|  |     [View all sources ->]                              [^]     |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  Geography: [Northern Virginia v]   Company: [All v]                 |
|                                                                      |
|  +------------------------+  +------------------------+              |
|  | MICROSOFT              |  | AWS                    |              |
|  | 2.4 GW [|||] [link]    |  | 1.8 GW [|||] [link]   |              |
|  | [check] Verified       |  |                        |              |
|  | Contracted: 2.0 GW     |  | Contracted: 1.5 GW    |              |
|  | Operational: 1.6 GW    |  | Operational: 1.2 GW   |              |
|  | Source: 3 filings      |  | Source: 2 filings      |              |
|  +------------------------+  +------------------------+              |
|                                                                      |
|  +------------------------+  +- - - - - - - - - - - - +              |
|  | GOOGLE                 |  |                        |              |
|  | 1.2 GW [||.] [link]    |  |  -- No power contracts |              |
|  |                        |  |     found for Meta in  |              |
|  | Contracted: 1.0 GW     |  |     Northern Virginia  |              |
|  | Operational: 0.8 GW    |  |                        |              |
|  | Source: 1 filing       |  |  Expected by: Jun 2026 |              |
|  +------------------------+  +- - - - - - - - - - - - +              |
|                                                                      |
|  +- - - - - - - - - - - - +                                          |
|  |                        |                                          |
|  |  -- No power contracts |                                          |
|  |     found for Oracle   |                                          |
|  |     in Northern VA     |                                          |
|  |                        |                                          |
|  +- - - - - - - - - - - - +                                          |
|                                                                      |
+----------------------------------------------------------------------+
```

### 10.2 Source Citation Popover Wireframe (Opened)

```
+----------------------------------------------------------------------+
|  ...                                                                 |
|  | MICROSOFT              |                                          |
|  | 2.4 GW [|||] [link] <------ user clicks                          |
|  |                   +----------------------------------------------+|
|  |                   |  SOURCE DETAIL (3 sources)              [x]  ||
|  |                   +----------------------------------------------+|
|  |                   |                                              ||
|  |                   |  Total: 2.4 GW (sum of 3 records)           ||
|  |                   |                                              ||
|  |                   |  1. Curated Deal #14            500 MW       ||
|  |                   |     [check] Verified                         ||
|  |                   |     Confidence: 0.95 (High)                  ||
|  |                   |     Microsoft-Dominion PPA                   ||
|  |                   |     Loudoun County, VA                       ||
|  |                   |     [Open SEC filing ->]                     ||
|  |                   |                                              ||
|  |                   |  2. EDGAR 8-K (2025-11-03)     1,200 MW      ||
|  |                   |     Confidence: [|||] 0.87 (High)            ||
|  |                   |     Retrieved: Nov 4, 2025 03:22 UTC         ||
|  |                   |     Parser: v1.2.0                           ||
|  |                   |     +--------------------------------------+ ||
|  |                   |     | "...entered into a power purchase    | ||
|  |                   |     | agreement for approximately [1,200]  | ||
|  |                   |     | megawatts of renewable energy..."    | ||
|  |                   |     +--------------------------------------+ ||
|  |                   |     [Open filing on SEC.gov ->]              ||
|  |                   |                                              ||
|  |                   |  3. EDGAR 8-K (2026-02-14)      700 MW       ||
|  |                   |     Confidence: [||.] 0.72 (Medium)          ||
|  |                   |     Retrieved: Feb 15, 2026 06:10 UTC        ||
|  |                   |     Parser: v1.2.0                           ||
|  |                   |     +--------------------------------------+ ||
|  |                   |     | "...approximately [700] megawatts    | ||
|  |                   |     | of capacity in the Virginia market"  | ||
|  |                   |     +--------------------------------------+ ||
|  |                   |     [Open filing on SEC.gov ->]              ||
|  |                   |                                              ||
|  |                   +----------------------------------------------+|
|  +------------------------+                                          |
```

### 10.3 Triangulation Tab Wireframe

```
+======================================================================+
|  Power | Satellite | GPU Supply | NICs | TSMC | Permits | Tri | Src  |
|                                                            [===]     |
+----------------------------------------------------------------------+
|                                                                      |
|  +----------------------------------------------------------------+  |
|  | [!] Triangulation: L1 real, L2 real (with assumptions),        |  |
|  |     L3 not available, L4 real for NoVA                         |  |
|  |     Overall confidence limited by missing L3 data       [^]   |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  Geography: [Northern Virginia v]                                    |
|                                                                      |
|  DATA LAYERS                                                         |
|  +-----------------------------------------------------------------+ |
|  |                                                                 | |
|  | L1  Contracted Power                                  2.4 GW   | |
|  | [=================================================] 100%       | |
|  | [green]  Sources: 3 EDGAR filings, 2 curated deals             | |
|  |          Confidence: [|||] High (0.91)   [link]                | |
|  |                                                                 | |
|  | L2  Estimated GPU Power Draw                          1.8 GW   | |
|  | [========================================.........] 80%         | |
|  | [green]  Sources: NVIDIA 10-Q (6 of 8 quarters)                | |
|  |          Confidence: [||.] Medium (0.68)   [link]              | |
|  |          [v Adjust assumptions]                                 | |
|  |                                                                 | |
|  |   +-----------------------------------------------------------+| |
|  |   | ASSUMPTIONS                                               || |
|  |   |                                                           || |
|  |   | Avg Power/GPU     [========|========]  820W               || |
|  |   | Utilization        [==========|======]  65%               || |
|  |   | GPU ASP            [========|========]  $25,000           || |
|  |   |                                                           || |
|  |   | [Reset to defaults]                                       || |
|  |   +-----------------------------------------------------------+| |
|  |                                                                 | |
|  | L3  NIC/Optics Validation                             --       | |
|  | [...................................................] 0%        | |
|  | [gray]  Not available -- Broadcom/Coherent/Lumentum             | |
|  |         earnings ingestion planned for Phase 2                  | |
|  |                                                                 | |
|  | L4  County Permit Signals                             47       | |
|  | [=================================================] 100%       | |
|  | [green]  Loudoun County (32), Prince William County (15)        | |
|  |          Confidence: [|||] High (0.85)   [link]                | |
|  |                                                                 | |
|  +-----------------------------------------------------------------+ |
|                                                                      |
|  RESULT                                                              |
|  +-----------------------------------------------------------------+ |
|  |                                                                 | |
|  |  Power Gap:  +0.6 GW   (Overbuild)                             | |
|  |              |----[=======X=======]----|                        | |
|  |            +0.2 GW              +1.1 GW                        | |
|  |                                                                 | |
|  |  Confidence: [||.] Medium (0.68)                                | |
|  |  Note: Missing L3 (NIC/optics). Gap estimate is unvalidated.   | |
|  |                                                                 | |
|  |  Interpretation: Northern Virginia has approximately 0.6 GW     | |
|  |  more contracted power than estimated GPU deployment requires.  | |
|  |  This suggests capacity overbuild or planned future deployment. | |
|  |                                                                 | |
|  +-----------------------------------------------------------------+ |
|                                                                      |
+----------------------------------------------------------------------+
```

### 10.4 NICs/Optics Tab Wireframe (Coming Soon)

```
+======================================================================+
|  Power | Satellite | GPU Supply | NICs | TSMC | Permits | Tri | Src  |
|                                  [===]                               |
+----------------------------------------------------------------------+
|                                                                      |
|  +----------------------------------------------------------------+  |
|  | [clock] NICs and Optics: Data sources not yet integrated       |  |
|  |         Broadcom, Coherent, Lumentum planned for Phase 2       |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  +...............................................................+  |
|  | ///////////////////////////////////////////////////////////// |  |
|  | //                                                        // |  |
|  | //   [blurred table placeholder showing rows and columns] // |  |
|  | //                                                        // |  |
|  | //   Quarter | InfiniBand | Ethernet | 400G | 800G        // |  |
|  | //   --------|------------|----------|------|------        // |  |
|  | //   Q1 2023 |  xxxxxxx   | xxxxxxx  | xxxx | xxxx       // |  |
|  | //   Q2 2023 |  xxxxxxx   | xxxxxxx  | xxxx | xxxx       // |  |
|  | //   Q3 2023 |  xxxxxxx   | xxxxxxx  | xxxx | xxxx       // |  |
|  | //                                                        // |  |
|  | ///////////////////////////////////////////////////////////// |  |
|  |                                                               |  |
|  |         [clock-icon]  Coming in Phase 2                       |  |
|  |                                                               |  |
|  |         NIC shipment tracking (Broadcom InfiniBand,           |  |
|  |         high-speed Ethernet) and optical transceiver           |  |
|  |         tracking (Coherent, Lumentum 400G/800G) require       |  |
|  |         earnings transcript ingestion not yet built.           |  |
|  |                                                               |  |
|  |         Target availability: Q4 2026                          |  |
|  |                                                               |  |
|  +...............................................................+  |
|                                                                      |
+----------------------------------------------------------------------+
```

### 10.5 Sources Tab Wireframe (Pipeline Health)

```
+======================================================================+
|  Power | Satellite | GPU Supply | NICs | TSMC | Permits | Tri | Src  |
|                                                                [===] |
+----------------------------------------------------------------------+
|                                                                      |
|  PIPELINE HEALTH                                                     |
|                                                                      |
|  Overall: 3 of 5 sources healthy  |  1 aging  |  1 not configured   |
|                                                                      |
|  +-----------------------------+  +-----------------------------+    |
|  | SEC EDGAR 8-K               |  | County Permits              |    |
|  | [green-dot] Healthy         |  | [green-dot] Healthy         |    |
|  |                             |  |                             |    |
|  | Last run:  Apr 28, 06:00    |  | Last run:  Apr 21, 02:00   |    |
|  | Records:   1,247            |  | Records:   312              |    |
|  | Next run:  Apr 28, 12:00    |  | Next run:  Apr 28, 02:00   |    |
|  | Errors (7d): 0              |  | Errors (7d): 0             |    |
|  |                             |  |                             |    |
|  | Feeds: Power, Tri (L1)      |  | Feeds: Permits, Tri (L4)   |    |
|  +-----------------------------+  +-----------------------------+    |
|                                                                      |
|  +-----------------------------+  +-----------------------------+    |
|  | NVIDIA Earnings (10-Q)      |  | TSMC Earnings (10-Q)       |    |
|  | [yellow-dot] Aging          |  | [yellow-dot] Aging         |    |
|  |                             |  |                             |    |
|  | Last run:  Apr 20, 14:00    |  | Last run:  Apr 18, 10:00   |    |
|  | Records:   48               |  | Records:   32              |    |
|  | Next run:  Event-driven     |  | Next run:  Event-driven    |    |
|  | Errors (7d): 0              |  | Errors (7d): 0             |    |
|  |                             |  |                             |    |
|  | Feeds: GPU Supply, Tri (L2) |  | Feeds: TSMC                |    |
|  +-----------------------------+  +-----------------------------+    |
|                                                                      |
|  +-----------------------------+  +-----------------------------+    |
|  | Curated Deals               |  | Aterio Dataset             |    |
|  | [green-dot] Healthy         |  | [green-dot] Healthy        |    |
|  |                             |  |                             |    |
|  | Records:   22               |  | Last upload: Apr 10        |    |
|  | Manually maintained         |  | Records:   1,840           |    |
|  |                             |  |                             |    |
|  | Feeds: Power, Tri (L1)      |  | Feeds: Power               |    |
|  +-----------------------------+  +-----------------------------+    |
|                                                                      |
|  NOT YET CONFIGURED                                                  |
|                                                                      |
|  +- - - - - - - - - - - - - -+  +- - - - - - - - - - - - - -+      |
|  | Broadcom Earnings          |  | Coherent Earnings          |      |
|  | [gray-dot] Phase 2         |  | [gray-dot] Phase 2         |      |
|  |                            |  |                            |      |
|  | Would feed: NICs, Tri (L3) |  | Would feed: Optics, Tri(L3)|      |
|  +- - - - - - - - - - - - - -+  +- - - - - - - - - - - - - -+      |
|                                                                      |
|  +- - - - - - - - - - - - - -+  +- - - - - - - - - - - - - -+      |
|  | Lumentum Earnings          |  | Satellite Imagery          |      |
|  | [gray-dot] Phase 2         |  | [gray-dot] Phase 2         |      |
|  |                            |  |                            |      |
|  | Would feed: Optics, Tri(L3)|  | Would feed: Satellite      |      |
|  +- - - - - - - - - - - - - -+  +- - - - - - - - - - - - - -+      |
|                                                                      |
+----------------------------------------------------------------------+
```

### 10.6 Permits Tab Wireframe (Mixed Real and No-Data)

```
+======================================================================+
|  Power | Satellite | GPU Supply | NICs | TSMC | Permits | Tri | Src  |
|                                                [===]                 |
+----------------------------------------------------------------------+
|                                                                      |
|  +----------------------------------------------------------------+  |
|  | [i] Permits: Loudoun and Prince William counties monitored     |  |
|  |     47 datacenter permits tracked | Last updated: 3 days ago   |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  County: [Loudoun County, VA v]                                      |
|                                                                      |
|  +----------------------------------------------------------------+  |
|  | Permit   | Company    | Type        | Filed      | Status     |  |
|  |----------|------------|-------------|------------|------------|  |
|  | PLN-4521 | AWS        | Electrical  | 2026-03-12 | Approved   |  |
|  |          | (Vadata)   |             |            |            |  |
|  |          | 250,000 sf | 80 MW       | [|||] [link]           |  |
|  |----------|------------|-------------|------------|------------|  |
|  | PLN-4498 | Microsoft  | Construct.  | 2026-02-28 | Under Rev. |  |
|  |          | (Cloverleaf)|            |            |            |  |
|  |          | 400,000 sf | 150 MW      | [|||] [link]           |  |
|  |----------|------------|-------------|------------|------------|  |
|  | PLN-4467 | Unknown    | Grading     | 2026-02-15 | Approved   |  |
|  |          | (Bowman    |             |            |            |  |
|  |          |  Dev LLC)  |             |            |            |  |
|  |          | 180,000 sf | -- MW n/a   | [||.] [link]           |  |
|  |          | [?] Unresolved company -- review needed             |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  County: [Maricopa County, AZ v]                                     |
|                                                                      |
|  +- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -+   |
|  |                                                               |   |
|  |  [building-icon]                                              |   |
|  |                                                               |   |
|  |  Permit monitoring covers Loudoun County, VA and              |   |
|  |  Prince William County, VA in Phase 1.                        |   |
|  |                                                               |   |
|  |  Maricopa County is planned for Phase 2 (Q4 2026).            |   |
|  |                                                               |   |
|  +- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -+   |
|                                                                      |
+----------------------------------------------------------------------+
```

---

## 11. Interaction States

### Citation Link Icon

| State | Visual |
|-------|--------|
| Default | `gray-500` icon, 12x12px |
| Hover | `blue-600` icon, cursor pointer, tooltip "View source" |
| Active/pressed | `blue-700` icon, slight scale down (0.95) |
| Popover open | `blue-600` icon, popover anchored below-right |
| Focus (keyboard) | 2px `blue-400` focus ring around icon |

### Confidence Bar

| State | Visual |
|-------|--------|
| High (>= 0.80) | Three green segments filled |
| Medium (0.50 - 0.79) | Two yellow segments filled, one gray |
| Low (< 0.50) | One red segment filled, two gray |
| Hover | Tooltip showing score and basis text |
| No confidence data | Bar hidden entirely (should not occur -- every State 1/2 datapoint has confidence) |

### Assumption Sliders

| State | Visual |
|-------|--------|
| Default | Slider at default position, `gray-600` track, `blue-600` thumb |
| Hover | Thumb grows to 18px, shadow intensifies |
| Dragging | Thumb `blue-700`, value label follows thumb position |
| Changed from default | Track turns `yellow-400`, value text `yellow-700`, yellow-100 background behind the row |
| Disabled (no L2 data) | `gray-300` track, `gray-400` thumb, 50% opacity |
| Focus (keyboard) | 2px `blue-400` focus ring around thumb. Arrow keys adjust by step value. |

### Tab Quality Banner

| State | Visual |
|-------|--------|
| Expanded (default) | Full banner with all fields, chevron pointing up |
| Collapsed | Single line: "[icon] Power Tab: 3 of 5 companies real | 2h ago" with chevron pointing down |
| Hover on "View all sources" | Underline, `blue-600` text |

### No-Data Cell

| State | Visual |
|-------|--------|
| Default | Dashed border, `gray-50` background, centered em-dash and reason text |
| Hover | Border color shifts to `gray-400`, subtle shadow appears |
| Focus (keyboard) | 2px `blue-400` focus ring. Screen reader announces the reason text. |

### Coming-Soon Section

| State | Visual |
|-------|--------|
| Default | Blurred placeholder, overlay text, dotted border |
| Hover | No change (non-interactive) |
| Focus (keyboard) | Focus ring on the section. Screen reader announces: "[Tab name] data coming in Phase 2. [Timeline detail]." |

### Global Health Bar

| State | Visual |
|-------|--------|
| Default | 4px bar with colored segments |
| Hover | Bar expands to 8px, tooltip shows source breakdown |
| Click | Navigates to Sources tab |

### Source Detail Popover

| State | Visual |
|-------|--------|
| Opening | Fade-in 150ms, scale from 0.95 to 1.0 |
| Open | Fixed width 400px, shadow, border |
| Scroll (if content exceeds max-height) | Vertical scrollbar, subtle `gray-200` track |
| Close button hover | X icon turns `red-500` |
| Close triggers | Click outside, Escape key, close button click |
| Closing | Fade-out 100ms |

---

## 12. Accessibility Notes

### WCAG 2.1 AA Compliance Targets

**Color contrast:**
- All data state indicators must meet 4.5:1 contrast ratio for text.
- The green/yellow/red freshness dots and confidence bars use colors that are distinguishable even in grayscale (different luminance values). Additionally, freshness tiers include text labels ("Fresh", "Aging", "Stale") and confidence tiers include labels ("High", "Medium", "Low") so that color is never the sole indicator.
- No-data `gray-500` text on `gray-50` background: 5.7:1 ratio (passes AA).
- Coming-soon `gray-600` text on white: 5.9:1 ratio (passes AA).

**Screen reader support:**
- Citation link icons have `aria-label="View source for [value description]"`.
- Confidence bars have `aria-label="Confidence: [tier] ([score])"` and `role="img"`.
- No-data cells have `role="status"` and the full reason text as the accessible name. The dashed border is decorative and not conveyed to screen readers.
- Coming-soon sections have `aria-label="[Feature name]: Coming in Phase 2. [Timeline detail]."`.
- The global health bar has `role="status"` and `aria-label="Pipeline health: [N] of [M] sources fresh"`.
- Source detail popover uses `role="dialog"`, `aria-modal="true"`, and traps focus while open. Escape closes it.
- Aggregated source popovers use a list (`role="list"`) for contributing sources.

**Keyboard navigation:**
- Citation link icons are focusable via Tab key and activated via Enter/Space.
- Assumption sliders are operable via arrow keys (Left/Right for value, Home/End for min/max).
- Tab quality banner collapse/expand toggle is focusable and activated via Enter/Space.
- Source detail popover traps focus: Tab cycles through popover elements, Escape closes.
- All interactive elements have visible focus indicators (2px `blue-400` ring).

**Motion and animation:**
- Popover open/close animations respect `prefers-reduced-motion`. When reduced motion is preferred, popovers appear/disappear instantly without fade or scale.
- Slider thumb animations respect `prefers-reduced-motion`.

**Content and language:**
- No-data reason strings are written in plain language, not technical jargon.
- Abbreviations (GW, MW, NoVA) are expanded on first use per page or available via `<abbr>` tag with `title` attribute.
- Source excerpts in popovers use `lang` attribute if the source text is in a different language than the UI.

**Data table accessibility (Permits tab, GPU Supply tab):**
- Tables use proper `<th>` headers with `scope="col"` or `scope="row"`.
- No-data rows span the full table width with a `colspan` and the reason text centered.
- Sort controls (if any) announce sort direction to screen readers.

---

### OCI %-Share KPI Tile

Displayed on every category tab (Power, GPU, NICs/Optics, TSMC, Permits, Triangulation).

**Data states:**
- **Loading:** Skeleton tile with shimmer animation
- **Real data:** OCI logo + percentage + absolute value + unit + trend arrow
- **No data:** "OCI share unavailable" with info tooltip explaining why
- **Error:** "Failed to load OCI share" with retry button

**API:** `GET /api/{tab}/oci-share`
**Computation:** Defined in `03-architecture-design.md` (canonical) and `03-PIPELINE-ARCHITECTURE.md` (pipeline).

---

### Energy Supply Tab (New)

**Data states:**
- **Loading:** Table skeleton + map placeholder
- **Real data:** Sortable table + map with project markers
- **Empty:** "No energy projects match your filters" with clear-filters button
- **Error:** Standard error card with retry

**Source:** `GET /api/energy-projects` (1695 rows from Aterio Energy Project Inventory)

---

### Events Timeline

**Data states:**
- **Loading:** Timeline skeleton with placeholder cards
- **Real data:** Vertical timeline with event cards, linked to site names
- **Empty:** "No events in selected date range" with date range adjuster
- **Error:** Standard error card with retry

**Source:** `GET /api/events` (957 rows from Aterio Data Dictionary Events sheet)
**Placement:** Collapsible section below main content on Power, Permits, Satellite tabs

---

### Broken UI Fixes (§5 of 00-DECISIONS-AND-CONSTRAINTS.md)

| # | Issue | Data State Impact | Fix |
|---|---|---|---|
| 1 | Silent EDGAR `except Exception` | Errors hidden from user | Add error state + toast notification |
| 2 | `useApi` swallows errors | No error UI rendered | Add error boundary + error state to all consumers |
| 3 | `random.*` mock confidence | Misleading confidence badges | Replace with deterministic formula or honest "no data" |
| 4 | Hardcoded `localhost:8000` | Broken in production | Environment variable / relative URL |
| 5 | CORS `*` | Security risk | Restrict origin |
| 6 | Google Maps key in `.env.local` | Exposed secret | Move to env var, gitignore `.env.local` |

---

## Appendix A: Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| No "Mock Data" state in production | Mock data that looks real erodes trust. Better to show nothing than fake numbers. The env-gated `MOCK_DATA=1` flag exists only for local development. | 2026-04-28 |
| Four data states, not three | Distinguishing "No Data" (pipeline looked and found nothing) from "Coming Soon" (feature not built yet) provides different information to the user and requires different visual treatment. | 2026-04-28 |
| Curated data gets elevated trust signal | `curated_deals.py` is hand-verified with real SEC URLs. It deserves a higher trust indicator than pipeline-parsed data, which may have parsing errors. | 2026-04-28 |
| Popover for citations, not a side panel | Most citation checks are quick (verify the source, glance at excerpt). A popover is faster than navigating to a separate panel. Aggregated sources may warrant a larger popover but still not a full panel. | 2026-04-28 |
| Error bars on triangulation, not point estimates | The PRD explicitly flags that L2 (GPU power draw) compounds assumptions. A single number without error bars would be misleading. | 2026-04-28 |
| Assumption sliders client-side | The triangulation formula is simple multiplication. Sliders recalculate instantly without an API round-trip, making the interaction feel responsive. | 2026-04-28 |
| Health bar in global header | Pipeline health affects every tab. A persistent, minimal indicator (4px bar) keeps this visible without consuming space. | 2026-04-28 |

---

## Appendix B: Mapping from mock_data.py Functions to Design States

This table maps every function in the current `mock_data.py` to its Phase 1 replacement state, ensuring nothing is missed.

| mock_data.py Function | Current Behavior | Phase 1 Replacement |
|-----------------------|-----------------|-------------------|
| `get_power_data()` | 70 rows x `random.uniform` for GW, contracted, operational, confidence | NoVA: State 1 (EDGAR + curated). Other geos: State 3 with reason. |
| `get_power_timeseries()` | `random.uniform` for base GW and quarterly increment | Real time-series for available quarters. State 3 cells for gaps. |
| `get_gpu_data()` | `random.randint` for shipped/deployed/inventory, `random.uniform` for revenue | NVIDIA 10-Q data for available quarters. State 3 for missing quarters. |
| `get_nics_optics_data()` | `random.randint` for IB/Ethernet/400G/800G, `random.uniform` for correlation | State 4 (entire tab). "Coming in Phase 2." |
| `get_tsmc_data()` | `random.randint` for wafers/CoWoS, `random.uniform` for utilization, `random.choice` for constraint | TSMC 10-Q data for available quarters. State 3 for missing quarters. |
| `get_permits_data()` | `random.sample`/`random.choice`/`random.randint` for everything including fake URLs | Loudoun/PWC: State 1 (real permits). Other counties: State 3 with Phase 2 timeline. |
| `get_triangulation_data()` | `random.uniform` for GW/confidence, `random.randint` for GPUs/permits | Pipeline-computed triangulation for NoVA. Missing layers: explicit "not available." Other regions: State 3. |
| `get_satellite_sites()` | No randomness -- real curated data | Keep as-is (State 2). Add State 4 for imagery/change detection features. |
| `get_sources_data()` | Static mock with plausible but fake timestamps | Replace with live `/api/pipeline/health` endpoint. |
| `get_agent_status()` | Static mock with fake run timestamps | Replace with live pipeline status. |

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§5 UX Rule:** All changes additive. No existing components/pages removed. No visual changes.
- **New data states:** OCI %-share KPI tile, Energy Supply tab, Events Timeline.
- **Broken UI fixes:** 6 issues with data-state impact identified.
- **OCI %-share:** Frontend presentation spec; computation in `03-architecture-design.md`.
