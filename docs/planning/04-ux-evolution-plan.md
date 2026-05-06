# UX Evolution Plan -- Datacenter & Power Intelligence Platform

**Version:** 1.0
**Date:** 2026-04-28
**Author:** Product Design
**Status:** Ready for engineering review

---

## Table of Contents

1. [Current State Audit](#1-current-state-audit)
2. [Component Hierarchy (Phase 1)](#2-component-hierarchy-phase-1)
3. [Design Tokens](#3-design-tokens)
4. [Error State Patterns](#4-error-state-patterns)
5. [Data Provenance UX](#5-data-provenance-ux)
6. [Time-Series and Global Filters](#6-time-series-and-global-filters)
7. [Loading States](#7-loading-states)
8. [Triangulation Tab Redesign](#8-triangulation-tab-redesign)
9. [Phase 1 Priorities and Sequencing](#9-phase-1-priorities-and-sequencing)
10. [Accessibility Notes](#10-accessibility-notes)

---

## 1. Current State Audit

### What works (preserve these patterns)

| Pattern | Location | Notes |
|---|---|---|
| Dark theme palette | `App.tsx` inline styles | `#0f172a` bg, `#1e293b` cards, `#334155` borders |
| `CARD_STYLE` constant | Every tab file | Consistent card treatment across all tabs |
| Recharts integration | 7 tabs | `ResponsiveContainer` wrapping, consistent tooltip styling |
| Deal row expand/collapse | `PowerTab.tsx` `DealRow` | Good progressive disclosure pattern |
| Source badges | `PowerTab.tsx` `SourceBadge` | Color-coded SEC EDGAR vs Press links |
| Company color map | `PowerTab.tsx` `COMPANY_COLORS` | MSFT blue, AWS orange, GCP blue, Meta blue, Oracle red |
| Tab nav LIVE/MOCK badges | `TabNav.tsx` `BADGE()` | Already distinguishes real vs mock at tab level |
| Status color coding | Multiple tabs | Green/yellow/red/blue status indicators |

### What is broken (fix in Phase 1)

| Issue | Severity | Current behavior |
|---|---|---|
| Error states silently swallowed | **Critical** | `useApi` tracks `error` but no tab reads it. API failure = infinite "Loading..." text or blank content. |
| No mock data warnings on content | **High** | TabNav has LIVE/MOCK badges, but the actual chart/card content has zero indication that data is random. Users refresh the page and see different numbers with no explanation. |
| Charts lack source links | **High** | PRD requires every datapoint to be clickable. Only the Power tab announcements table has `SourceBadge`. Zero charts link to sources. |
| No time controls | **Medium** | No quarter selector, no date range picker. PRD specifies cross-tab time/company/geo filtering. |
| No loading skeletons | **Medium** | Every tab uses a centered `"Loading..."` text string. |
| Confidence scores shown as raw numbers | **Low** | TriangulationTab shows a progress bar. Other tabs show `0.91` as plain text or ignore the field entirely. |
| Google Maps API key in client bundle | **Security** | `VITE_GOOGLE_MAPS_API_KEY` gets compiled into JS output. Mitigated: SatelliteTab now uses ESRI Wayback (no key needed), but the env var pattern remains a risk if reintroduced. |

---

## 2. Component Hierarchy (Phase 1)

Target component tree after Phase 1 refactoring:

```
App
|-- FilterContext.Provider          [NEW] global filter state
|   |-- Header
|   |   |-- BrandMark               (existing logo + title)
|   |   |-- SystemStatus            (existing "8 Agents Active" + last sync)
|   |   +-- DataFreshnessIndicator  [NEW] "Last refresh: 3 min ago"
|   |
|   |-- GlobalFilterBar             [NEW]
|   |   |-- CompanyMultiSelect      [NEW] chips: MSFT, AWS, GCP, Meta, Oracle
|   |   |-- GeographySelect         [NEW] state/region dropdown
|   |   +-- QuarterRangeSlider      [NEW] Q1 2022 ... Q4 2024
|   |
|   |-- TabNav                      (existing, keep LIVE/MOCK badges)
|   |
|   |-- TabContent                  [NEW] wrapper for each tab
|   |   |-- ErrorBoundary           [NEW] catches React render errors
|   |   |-- DataProvenanceBanner    [NEW] "This tab uses mock data" warning
|   |   |-- [Tab-specific content]
|   |   |   |-- LoadingSkeleton     [NEW] per-card skeleton placeholder
|   |   |   |-- Charts
|   |   |   |   |-- SourceTooltip   [NEW] custom Recharts tooltip
|   |   |   |   +-- CitationFooter  [NEW] source + retrieved-at below chart
|   |   |   +-- ConfidenceBadge     [NEW] colored dot + percentage
|   |   +-- ErrorPanel              [NEW] replaces infinite spinner on failure
|   |
|   +-- Footer                      [NEW]
|       +-- DataFreshnessBar        [NEW] per-source freshness indicators
```

### New files to create

```
frontend/src/
  context/
    FilterContext.tsx               -- React context for company/geo/quarter
  components/
    shared/
      ErrorBoundary.tsx             -- class component, catches render errors
      ErrorPanel.tsx                -- API error display with retry
      DataProvenanceBanner.tsx      -- mock data warning banner
      LoadingSkeleton.tsx           -- skeleton card, skeleton chart
      ConfidenceBadge.tsx           -- colored confidence indicator
      SourceTooltip.tsx             -- custom Recharts tooltip with source link
      CitationFooter.tsx            -- source citation below each chart
      GlobalFilterBar.tsx           -- company, geography, quarter filters
      QuarterRangeSlider.tsx        -- dual-handle quarter slider
      CompanyMultiSelect.tsx        -- chip-based multi-select
      CoverageBadge.tsx             -- per-tab coverage chip (full / partial / federal / unavailable)
      NoStateCoverage.tsx           -- per-state empty state on geographic charts
      CoveragePage.tsx              -- pillar × state matrix under Sources tab
      QaChatPanel.tsx               -- docked chat panel for Triangulation Q&A agent (D)
      QaMessage.tsx                 -- single chat turn with tool-call evidence rendering
      WeeklyBriefCard.tsx           -- dashboard card surfacing latest weekly briefing (E)
      WeeklyBriefHistory.tsx        -- list of prior weekly briefs (under Sources tab)
      LlmEvidenceTrail.tsx          -- popover showing tool calls + signal weights for any LLM-attributed value
    layout/
      Footer.tsx                    -- data freshness footer
  hooks/
    useApi.ts                       -- enhanced with retry, staleness tracking
```

---

## 3. Design Tokens

All tokens below are compatible with the existing inline-style approach. When the team migrates to CSS modules or a design system, these become CSS custom properties.

### Colors

```typescript
// frontend/src/tokens.ts

export const TOKENS = {
  // ── Backgrounds ──
  bgBase:       "#0f172a",   // page background (existing)
  bgCard:       "#1e293b",   // card background (existing)
  bgCardHover:  "#253347",   // card hover state [NEW]
  bgElevated:   "#162032",   // expanded rows, overlays (existing)
  bgTooltip:    "#0f172a",   // chart tooltip (existing)

  // ── Borders ──
  borderDefault:  "#334155", // card borders (existing)
  borderSubtle:   "#1e293b", // section dividers (existing)
  borderFocus:    "#3b82f6", // keyboard focus ring [NEW]
  borderError:    "#ef4444", // error state border [NEW]
  borderWarning:  "#f59e0b", // warning state border [NEW]

  // ── Text ──
  textPrimary:    "#ffffff", // headings, values (existing)
  textSecondary:  "#e2e8f0", // body text (existing)
  textMuted:      "#94a3b8", // labels, subtitles (existing)
  textDim:        "#64748b", // timestamps, metadata (existing)
  textDisabled:   "#475569", // disabled controls [NEW]

  // ── Accent ──
  accentBlue:     "#3b82f6", // primary actions, active tab (existing)
  accentBlueBg:   "#3b82f622", // blue tinted backgrounds [NEW]
  accentGreen:    "#22c55e", // success, live data (existing)
  accentYellow:   "#f59e0b", // warnings, construction (existing)
  accentRed:      "#ef4444", // errors, constrained (existing)
  accentPurple:   "#8b5cf6", // supplementary (existing)

  // ── Company Colors (existing, centralized) ──
  companyMicrosoft: "#0078D4",
  companyAmazon:    "#FF9900",
  companyGoogle:    "#4285F4",
  companyMeta:      "#1877F2",
  companyOracle:    "#C74634",

  // ── Confidence ──
  confidenceHigh:   "#22c55e",  // >= 0.9
  confidenceMedium: "#f59e0b",  // >= 0.75
  confidenceLow:    "#ef4444",  // < 0.75

  // ── Skeleton ──
  skeletonBase:  "#1e293b",  // skeleton background [NEW]
  skeletonShimmer: "#2a3a50", // shimmer highlight [NEW]

  // ── Spacing (px) ──
  spacingXs: 4,
  spacingSm: 8,
  spacingMd: 12,
  spacingLg: 16,
  spacingXl: 20,
  spacing2xl: 24,
  spacing3xl: 32,

  // ── Radii ──
  radiusSm: "6px",
  radiusMd: "8px",
  radiusLg: "12px",
  radiusXl: "14px",

  // ── Typography ──
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  fontSizeXs:  "10px",
  fontSizeSm:  "11px",
  fontSizeMd:  "12px",
  fontSizeLg:  "13px",
  fontSizeXl:  "15px",
  fontSize2xl: "16px",
  fontSize3xl: "24px",
  fontSize4xl: "36px",
  fontWeightNormal: 400,
  fontWeightMedium: 500,
  fontWeightSemibold: 600,
  fontWeightBold: 700,

  // ── Shadows ──
  shadowCard:    "0 1px 3px rgba(0,0,0,0.3)",
  shadowElevated: "0 16px 40px rgba(0,0,0,0.6)",
  shadowModal:   "0 24px 80px rgba(0,0,0,0.6)",

  // ── Transitions ──
  transitionFast: "0.15s ease",
  transitionMedium: "0.25s ease",
} as const;
```

---

## 4. Error State Patterns

### 4.1 Enhanced `useApi` hook

The current hook tracks `error` but provides no retry mechanism and no staleness detection.

**Spec for enhanced hook:**

```typescript
// Return type additions
interface UseApiReturn<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  stale: boolean;          // true if data is > 60 min old
  lastFetchedAt: Date | null;
  retry: () => void;       // manual retry function
  retryCount: number;      // how many retries have been attempted
}
```

Key behaviors:
- On error, set `error` with a human-readable message, stop loading.
- Expose `retry()` that clears error and re-fetches.
- Track `lastFetchedAt` timestamp. When `Date.now() - lastFetchedAt > 60 min`, set `stale = true`.
- No auto-retry. The user clicks the retry button.

### 4.2 ErrorPanel component

Renders when `useApi` returns a non-null `error`.

**Wireframe:**

```
+--------------------------------------------------------------+
|  [!] Unable to load power capacity data                      |
|                                                              |
|  The server returned an error (HTTP 500). This may be a      |
|  temporary issue.                                            |
|                                                              |
|  [ Retry ]     Last attempt: 2 minutes ago                   |
+--------------------------------------------------------------+
```

**Component spec:**

| Prop | Type | Description |
|---|---|---|
| `title` | `string` | e.g. "Unable to load power capacity data" |
| `message` | `string` | Human-readable error. Map HTTP codes: 500 = "Server error", 403 = "Access denied", network = "Network connection failed" |
| `onRetry` | `() => void` | Calls `retry()` from useApi |
| `lastAttempt` | `Date or null` | Renders relative time ("2 minutes ago") |
| `variant` | `"full" or "inline"` | `full` = replaces entire content area. `inline` = sits inside a card alongside other content. |

**Visual treatment:**

- `full` variant: centered in the tab content area, max-width 480px.
  - Background: `#1e293b`
  - Border: `1px solid #ef4444` (left border 3px)
  - Icon: `AlertTriangle` from lucide-react, 20px, color `#ef4444`
  - Title: `#ffffff`, 15px, weight 600
  - Message: `#94a3b8`, 13px
  - Retry button: background `#3b82f6`, color white, border-radius 6px, padding 8px 16px
  - Last attempt text: `#64748b`, 11px, to the right of the button

- `inline` variant: same styling but no centering, fits within a card grid.

**Error message mapping:**

```typescript
function getErrorMessage(error: string): { title: string; message: string } {
  if (error.includes("500"))
    return { title: "Server error", message: "The API returned an internal error. Try again in a moment." };
  if (error.includes("404"))
    return { title: "Data not available", message: "This endpoint has not been implemented yet." };
  if (error.includes("403"))
    return { title: "Access denied", message: "You do not have permission to view this data." };
  if (error.includes("Failed to fetch") || error.includes("NetworkError"))
    return { title: "Network error", message: "Could not reach the server. Check your connection." };
  return { title: "Something went wrong", message: error };
}
```

### 4.3 Empty state

When the API succeeds but returns an empty array.

**Wireframe:**

```
+--------------------------------------------------------------+
|  [inbox icon]                                                |
|                                                              |
|  No power data available for this region and time range.     |
|                                                              |
|  Try adjusting your filters or check back later.             |
+--------------------------------------------------------------+
```

- Icon: `Inbox` from lucide-react, 32px, color `#475569`
- Message: `#94a3b8`, 14px
- Suggestion: `#64748b`, 12px
- Background: transparent (no card border -- this lives inside the existing card)

### 4.4 Stale data indicator

When data was fetched successfully but `stale === true`.

**Wireframe (inline banner, sits above chart content):**

```
+--------------------------------------------------------------+
| [clock icon] Data last refreshed 2 hours ago.  [ Refresh ]   |
+--------------------------------------------------------------+
```

- Background: `#f59e0b15`
- Border: `1px solid #f59e0b44`
- Border-radius: 8px
- Text: `#f59e0b`, 12px
- Refresh button: ghost style, border `1px solid #f59e0b`, color `#f59e0b`, padding 4px 10px

### 4.5 Partial data

When a tab makes multiple API calls and some succeed while others fail (e.g., PowerTab calls `/api/power/capacity`, `/api/power/timeseries`, `/api/power/announcements`).

**Behavior:**
- Render the sections that loaded successfully.
- Replace failed sections with the `inline` ErrorPanel variant.
- Do NOT block the entire tab.

**Implementation change for PowerTab:**
Currently, lines 389 do: `if (capLoading || tsLoading) return <LoadingSpinner />;`
This means if `capData` fails, the entire tab fails. Instead:

```typescript
// Render each section independently:
return (
  <div>
    {capError ? <ErrorPanel variant="inline" ... /> : capLoading ? <LoadingSkeleton variant="chart" /> : <CapacityChart data={capData} />}
    {tsError ? <ErrorPanel variant="inline" ... /> : tsLoading ? <LoadingSkeleton variant="chart" /> : <TimeseriesChart data={tsData} />}
    {annError ? <ErrorPanel variant="inline" ... /> : annLoading ? <LoadingSkeleton variant="table" /> : <AnnouncementsTable data={annData} />}
  </div>
);
```

### 4.6 ErrorBoundary (React render crash)

A class component wrapping each tab's content. If a rendering error occurs (e.g., data shape mismatch causes a TypeError), catch it and show a recovery UI.

```
+--------------------------------------------------------------+
|  [!] This section encountered an unexpected error.           |
|                                                              |
|  Error: Cannot read property 'gw_total' of undefined         |
|                                                              |
|  [ Reload Tab ]                                              |
+--------------------------------------------------------------+
```

- Wrap each `TAB_CONTENT[activeTab]` in `<ErrorBoundary key={activeTab}>`.
- The `key` prop forces a fresh mount when switching tabs, clearing the error state.

---

## 5. Data Provenance UX

### 5.1 DataProvenanceBanner

A persistent banner at the top of any tab using mock data, rendered inside the `TabContent` wrapper.

**Wireframe:**

```
+--------------------------------------------------------------+
| [beaker icon]  SIMULATED DATA -- This tab displays randomly  |
| generated sample data. Numbers change on each page refresh.  |
| Real data integration is in progress.         [ Dismiss (x)] |
+--------------------------------------------------------------+
```

**Three variants based on data source:**

| Variant | Background | Border | Icon | Label |
|---|---|---|---|---|
| `live` | `#052e1680` | `1px solid #16a34a44` | `CheckCircle` green | "LIVE DATA -- sourced from verified public filings and press releases." |
| `mock` | `#44403c30` | `1px solid #78716c44` | `Beaker` amber | "SIMULATED DATA -- Numbers are randomly generated and change on refresh." |
| `mixed` | `#f59e0b15` | `1px solid #f59e0b44` | `AlertTriangle` yellow | "MIXED DATA -- Some sections use real data, others are simulated. See badges on each chart." |

**Tab-to-variant mapping (current state):**

| Tab | Variant | Notes |
|---|---|---|
| Power | `live` | Announcements are curated real data. Capacity/timeseries derived from real deals. |
| Satellite | `live` | Real site data with ESRI imagery |
| DataCenters | `mock` | Random data |
| GPUSupply | `mock` | Random data |
| NICsOptics | `mock` | Random data |
| TSMC | `mock` | Random data |
| Permits | `mock` | Random data |
| Triangulation | `mock` | Random data |
| Sources | `live` | Static source registry |

**Dismissal behavior:**
- User can dismiss the banner for the current session (store in `sessionStorage`).
- Banner always returns on new session.
- The `mock` variant has a subtle pulsing border animation (2s ease-in-out infinite, alternating between `#78716c22` and `#78716c66`) to ensure it is not ignored.

### 5.2 ConfidenceBadge component

Displays the confidence score (0.0-1.0) as a colored dot with a percentage label.

**Wireframe:**

```
 [green dot] 94%     [yellow dot] 78%     [red dot] 62%
```

**Component spec:**

| Prop | Type | Description |
|---|---|---|
| `score` | `number` | 0.0 to 1.0 |
| `size` | `"sm" or "md"` | sm = 10px dot + 10px text. md = 14px dot + 12px text. |
| `showLabel` | `boolean` | If false, show only the dot (use in tight spaces like table cells) |

**Color logic:**

```typescript
function confidenceColor(score: number): string {
  if (score >= 0.9) return "#22c55e";  // green
  if (score >= 0.75) return "#f59e0b"; // yellow
  return "#ef4444";                     // red
}
```

**Rendering:**
- Dot: a `<span>` with `display: inline-block`, width/height per size, `border-radius: 50%`, `background` set to the color.
- Label: `{(score * 100).toFixed(0)}%` immediately after the dot, same color, with `margin-left: 4px`.
- Tooltip on hover: "Confidence: 94% -- High confidence based on primary source verification"
  - >= 0.9: "High confidence"
  - >= 0.75: "Moderate confidence -- cross-reference recommended"
  - < 0.75: "Low confidence -- treat as estimate"

### 5.3 SourceTooltip (custom Recharts tooltip)

Replaces the default Recharts `<Tooltip>` across all charts. Adds source URL and retrieval timestamp.

**Wireframe (on hover over a bar/line point):**

```
+------------------------------------+
|  Microsoft                         |
|  --------------------------------  |
|  Total GW:     4.20 GW   [*] 94%  |
|  Nuclear GW:   1.80 GW   [*] 91%  |
|  Renewable GW: 2.40 GW   [*] 88%  |
|  --------------------------------  |
|  Source: SEC 10-K Filing           |
|  Retrieved: 2024-12-10 14:30 UTC   |
|  [link icon] View source ->        |
+------------------------------------+
```

**Implementation pattern for Recharts:**

```tsx
// frontend/src/components/shared/SourceTooltip.tsx

import { ExternalLink } from "lucide-react";

interface SourceTooltipProps {
  active?: boolean;
  payload?: Array<{
    name: string;
    value: number;
    payload: Record<string, unknown>;
  }>;
  label?: string;
  unit?: string;
  sourceField?: string;     // key in the data record containing source URL
  confidenceField?: string; // key in the data record containing confidence
  retrievedAt?: string;     // ISO timestamp of last data fetch
  formatValue?: (value: number, name: string) => string;
}

export default function SourceTooltip({
  active, payload, label, unit = "",
  sourceField = "source_url",
  confidenceField = "confidence",
  retrievedAt,
  formatValue,
}: SourceTooltipProps) {
  if (!active || !payload?.length) return null;

  const record = payload[0].payload;
  const sourceUrl = record[sourceField] as string | undefined;
  const confidence = record[confidenceField] as number | undefined;

  return (
    <div style={{
      background: "#0f172a",
      border: "1px solid #334155",
      borderRadius: "8px",
      padding: "12px 14px",
      minWidth: "200px",
      maxWidth: "320px",
      boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
    }}>
      {/* Label */}
      <div style={{
        color: "#ffffff",
        fontSize: "13px",
        fontWeight: 600,
        marginBottom: "8px",
        borderBottom: "1px solid #1e293b",
        paddingBottom: "6px",
      }}>
        {label}
      </div>

      {/* Data rows */}
      {payload.map((entry, i) => (
        <div key={i} style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "3px 0",
        }}>
          <span style={{ color: "#94a3b8", fontSize: "12px" }}>
            {entry.name}
          </span>
          <span style={{ color: "#e2e8f0", fontSize: "12px", fontWeight: 500 }}>
            {formatValue
              ? formatValue(entry.value, entry.name)
              : `${entry.value}${unit}`}
          </span>
        </div>
      ))}

      {/* Source footer */}
      {(sourceUrl || confidence !== undefined || retrievedAt) && (
        <div style={{
          borderTop: "1px solid #1e293b",
          marginTop: "8px",
          paddingTop: "8px",
        }}>
          {confidence !== undefined && (
            <div style={{
              display: "flex", alignItems: "center", gap: "4px",
              marginBottom: "4px",
            }}>
              <span style={{
                width: "6px", height: "6px", borderRadius: "50%",
                background: confidence >= 0.9 ? "#22c55e"
                  : confidence >= 0.75 ? "#f59e0b" : "#ef4444",
                display: "inline-block",
              }} />
              <span style={{ color: "#64748b", fontSize: "10px" }}>
                Confidence: {(confidence * 100).toFixed(0)}%
              </span>
            </div>
          )}
          {retrievedAt && (
            <div style={{ color: "#475569", fontSize: "10px", marginBottom: "4px" }}>
              Retrieved: {retrievedAt}
            </div>
          )}
          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              style={{
                display: "inline-flex", alignItems: "center", gap: "4px",
                color: "#60a5fa", fontSize: "10px", textDecoration: "none",
              }}
            >
              <ExternalLink size={9} />
              View source
            </a>
          )}
        </div>
      )}
    </div>
  );
}
```

**Usage in a Recharts chart:**

```tsx
<Tooltip
  content={
    <SourceTooltip
      unit=" GW"
      sourceField="source_url"
      confidenceField="confidence"
      retrievedAt={lastFetchedAt?.toISOString()}
      formatValue={(v, name) => `${v.toFixed(2)} GW`}
    />
  }
  cursor={{ fill: "#ffffff10" }}
/>
```

**Data shape requirement:**
Each data record passed to Recharts must include `source_url` and `confidence` fields. For the Power tab bar chart, the `realGWData` mapping (currently at PowerTab.tsx line 396) must be extended:

```typescript
const realGWData = Object.entries(gwSummary).map(([company, v]) => ({
  company,
  "Total GW": v.gw_total,
  "Nuclear GW": v.nuclear_gw,
  "Renewable GW": v.renewable_gw,
  // ADD these fields for SourceTooltip:
  source_url: `/api/power/announcements?company=${company}`,
  confidence: deals
    .filter(d => d.buyer.includes(company))
    .reduce((sum, d) => sum + d.confidence, 0)
    / Math.max(deals.filter(d => d.buyer.includes(company)).length, 1),
}));
```

### 5.4 CitationFooter

A small footer below each chart card listing the data sources and retrieval time.

**Wireframe:**

```
+--------------------------------------------------------------+
| Sources: SEC EDGAR 10-K/10-Q filings, press releases         |
| Retrieved: 2024-12-15 09:00 UTC | Confidence: [green] 94%    |
+--------------------------------------------------------------+
```

**Component spec:**

| Prop | Type | Description |
|---|---|---|
| `sources` | `string[]` | e.g. `["SEC EDGAR", "Press Releases"]` |
| `retrievedAt` | `string or null` | ISO timestamp |
| `confidence` | `number or null` | Average confidence for the chart's dataset |
| `isMock` | `boolean` | If true, show "Simulated data" instead of source list |

**Visual:**
- Background: transparent (no separate card)
- Top border: `1px solid #1e293b` (separator from chart above)
- Padding: `10px 0 0`
- Text: `#64748b`, 11px
- If `isMock`, replace all content with: `"[beaker] Simulated data -- not sourced from real filings"` in `#78716c`

---

## 6. Time-Series and Global Filters

### 6.1 FilterContext

A React context that holds the global filter state and persists across tab switches.

```typescript
// frontend/src/context/FilterContext.tsx

interface FilterState {
  companies: string[];       // selected companies, empty = all
  geography: string | null;  // selected state/region, null = all
  quarterRange: {
    start: string;           // "Q1 2022"
    end: string;             // "Q4 2024"
  };
}

interface FilterContextValue {
  filters: FilterState;
  setCompanies: (companies: string[]) => void;
  setGeography: (geo: string | null) => void;
  setQuarterRange: (start: string, end: string) => void;
  resetAll: () => void;
}
```

**Persistence:** Store in `sessionStorage` so filters survive page refreshes within a session but not across sessions.

**Cross-tab behavior:** When a user selects "Virginia" on the Power tab, switching to the Permits tab should show Virginia permits automatically. The context lives above the tab router.

### 6.2 GlobalFilterBar

Sits between the TabNav and the tab content area. Always visible.

**Wireframe:**

```
+--------------------------------------------------------------+
| Company:  [MSFT] [AWS] [x GCP] [Meta] [Oracle]   |  Region: |
|           ^^^ chip toggles, filled = selected     | [Virginia|
|                                                   |   v    ] |
| Time:  Q1 2022 =====[=========]========= Q4 2024            |
|                      ^start    ^end                          |
|                                          [ Reset filters ]   |
+--------------------------------------------------------------+
```

**Component specs:**

#### CompanyMultiSelect

- Renders 5 chip buttons, one per company.
- Selected chips: filled with company color at 20% opacity, text in company color, 1px solid company color border.
- Unselected chips: `background: transparent`, `border: 1px solid #334155`, `color: #64748b`.
- Clicking toggles selection. If all are deselected, treat as "all selected" (no filtering).
- Height: 32px. Border-radius: 6px. Font: 12px, weight 500.

#### GeographySelect

- A native `<select>` dropdown (matching existing filter dropdowns in PowerTab and PermitsTab).
- Options: "All Regions", then sorted list of states/regions from the current tab's data.
- Style: matches existing selects -- `background: #0f172a`, `border: 1px solid #334155`, `color: white`, `border-radius: 6px`, padding `5px 8px`, font `12px`.

#### QuarterRangeSlider

- Dual-handle range input for selecting start and end quarters.
- Track: `background: #334155`, height `4px`, border-radius `2px`.
- Selected range fill: `background: #3b82f6`.
- Handles: `16px` circles, `background: #3b82f6`, `border: 2px solid #1e293b`.
- Labels below: show the selected range as text: "Q1 2023 -- Q3 2024".
- Tick marks at each quarter, with year labels at Q1 positions.
- Implementation: two `<input type="range">` elements overlaid, or a custom component. Do NOT pull in a heavyweight slider library.

#### Reset button

- Ghost button: `background: transparent`, `border: 1px solid #334155`, `color: #64748b`, `border-radius: 6px`.
- Text: "Reset filters"
- On click: calls `resetAll()` from FilterContext.
- Only visible when at least one filter differs from default.

### 6.3 How filters connect to API calls

Filters are passed as query parameters to API endpoints:

```
/api/power/capacity?companies=Microsoft,Amazon&region=Virginia&start=Q1+2023&end=Q4+2024
```

The `useApi` hook should accept the filter context and rebuild the URL when filters change:

```typescript
// Enhanced useApi usage:
const { filters } = useFilterContext();
const queryString = buildFilterQuery(filters);
const { data, loading, error } = useApi<PowerCapacityResponse>(
  `/api/power/capacity${queryString}`
);
```

**Backend requirement:** All `/api/*` endpoints must accept optional `companies`, `region`, `start`, `end` query parameters and filter their responses accordingly. Until the backend supports these parameters, the frontend should filter client-side as a fallback.

---

## 7. Loading States

### 7.1 LoadingSkeleton component

Replaces the current `"Loading..."` text with animated placeholder shapes.

**Variants:**

#### `variant="kpi-row"` (for metric card rows)

```
+----------+  +----------+  +----------+  +----------+
| [=====]  |  | [=====]  |  | [=====]  |  | [=====]  |
| [==]     |  | [==]     |  | [==]     |  | [==]     |
| [====]   |  | [====]   |  | [====]   |  | [====]   |
+----------+  +----------+  +----------+  +----------+
```

- 4 cards in a flex row, each with the standard `CARD_STYLE`.
- Inside each card: 3 skeleton bars of varying widths (80%, 40%, 60%).
- Bar height: 12px. Color: `#1e293b`. Border-radius: 4px.
- Shimmer animation: a CSS `@keyframes` that sweeps a lighter gradient (`#2a3a50`) left-to-right across each bar, 1.5s infinite.

#### `variant="chart"` (for Recharts containers)

```
+--------------------------------------------------------------+
| [=====================================]  <- title bar         |
| [==========]                             <- subtitle bar      |
|                                                              |
|     |                                                        |
|     |      ___                                               |
|     |  ___|   |___       ___                                 |
|     | |   |   |   |  ___|   |                                |
|     | |   |   |   | |   |   |                                |
|     +-----------------------------                           |
|                                                              |
+--------------------------------------------------------------+
```

- Outer card with `CARD_STYLE`.
- Title skeleton: 240px wide, 14px tall.
- Subtitle skeleton: 160px wide, 10px tall.
- Chart area: 5 vertical bars of random height (30-80%), `background: #1e293b`, with the same shimmer animation. Heights should be deterministic (not random on each render) -- use fixed values: `[60%, 45%, 75%, 35%, 55%]`.

#### `variant="table"` (for announcement tables)

```
+--------------------------------------------------------------+
| [===]  [==============]  [====]  [=====]  [====]  [===]      |
| [===]  [==============]  [====]  [=====]  [====]  [===]      |
| [===]  [==============]  [====]  [=====]  [====]  [===]      |
| [===]  [==============]  [====]  [=====]  [====]  [===]      |
| [===]  [==============]  [====]  [=====]  [====]  [===]      |
+--------------------------------------------------------------+
```

- 5 rows, each with 6 skeleton bars of varying widths matching the column layout.
- Row height: 40px. Row separator: `1px solid #1e293b`.

### 7.2 Shimmer animation (CSS)

Add this to the global CSS or inject it via a `<style>` tag in the skeleton component:

```css
@keyframes skeleton-shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.skeleton-bar {
  background: linear-gradient(
    90deg,
    #1e293b 25%,
    #2a3a50 50%,
    #1e293b 75%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
}
```

### 7.3 Progressive loading

For tabs that make multiple API calls (PowerTab makes 3), render each section as it arrives:

1. Show `LoadingSkeleton variant="kpi-row"` for KPIs while `/api/power/capacity` loads.
2. As soon as capacity data arrives, render the real KPI row and bar chart. Keep showing skeletons for the timeseries and announcements.
3. When timeseries arrives, render the line chart.
4. When announcements arrive, render the table.

This requires splitting the current monolithic `if (loading) return <LoadingSpinner />` into per-section checks.

### 7.4 Background refresh indicator

When data is being refreshed in the background (e.g., the user clicked "Refresh" on a stale data warning), show a thin progress bar at the top of the tab content area:

```
[===========>                                        ]  (2px tall)
```

- Position: absolute, top of the tab content area.
- Height: 2px.
- Color: `#3b82f6`.
- Animation: indeterminate left-to-right sweep.
- Disappears when fetch completes.

---

## 8. Triangulation Tab Redesign

The Triangulation tab is the most important view for the exec sponsor. It must communicate the intelligence pipeline clearly: how contracted power translates to estimated compute capacity, validated by NIC/optics signals and permit ground truth.

### 8.1 User Flow

```
User opens Triangulation tab
  |
  v
See the 4-layer model explanation (existing, keep)
  |
  v
See the "flow" visualization: Power -> GPUs -> NICs -> Permits
  |                                    [NEW]
  v
See the gap analysis chart (enhanced with source tooltips)
  |
  v
Adjust assumption sliders (GPU power draw, utilization rate)
  |                        [NEW]
  v
See region detail cards update in real time
  |
  v
Click any number to see its source chain
  [NEW]
```

### 8.2 Sankey-style flow visualization

Replace the current static "Model Layers" card with an interactive flow diagram showing how data cascades through the four layers.

**Wireframe:**

```
+--------------------------------------------------------------+
|  Intelligence Flow: Power -> Compute -> Validation            |
|                                                              |
|  +--L1 POWER--+     +--L2 GPU-----+     +--L3 NIC---+     +-L4 PERMIT-+
|  |             |     |             |     |           |     |           |
|  | 12.4 GW    |====>| ~180k GPUs  |====>| 0.87 NIC  |====>| 47 permits|
|  | contracted |     | estimated   |     | score     |     | filed     |
|  |             |     |             |     |           |     |           |
|  | [*] 94%    |     | [*] 78%    |     | [*] 82%  |     | [*] 91%  |
|  +-------------+     +-------------+     +-----------+     +-----------+
|         |                   |                  |                 |
|         v                   v                  v                 v
|    SEC filings        NVIDIA earnings    Broadcom/MLNX      County DBs
|    Utility PPAs       ASP model          shipment data       FOIA requests
+--------------------------------------------------------------+
```

**Implementation notes:**
- Use a CSS flex/grid layout, not a charting library. Four cards in a row connected by arrow/flow indicators.
- Arrow indicators: use CSS `::after` pseudo-elements or inline SVG arrows between boxes.
- Each box has:
  - Layer label (L1/L2/L3/L4) in `#3b82f6`, 11px, bold
  - Title (e.g. "Contracted Power"), 13px, white, weight 600
  - Value (e.g. "12.4 GW"), 24px, white, weight 700
  - Descriptor (e.g. "contracted"), 11px, `#64748b`
  - ConfidenceBadge at bottom
  - Below the box: source description in `#475569`, 10px
- Connecting arrows: `#334155` color, `2px` wide, with a small arrowhead. Use `>` characters or small SVG triangles.
- Box border: `1px solid #334155`. Active/hovered box gets `border-color: #3b82f6`.

### 8.3 Assumption sliders

Allow executives to adjust the model's key assumptions and see how the triangulation changes.

**Wireframe:**

```
+--------------------------------------------------------------+
|  Model Assumptions                                [Reset]    |
|                                                              |
|  GPU Power Draw (per unit)                                   |
|  700W  [====|============] 1200W           Current: 950W     |
|                                                              |
|  Average Utilization Rate                                    |
|  50%   [========|========] 100%            Current: 75%      |
|                                                              |
|  PUE (Power Usage Effectiveness)                             |
|  1.1   [=====|===========] 2.0             Current: 1.3      |
+--------------------------------------------------------------+
```

**Spec:**
- Three range sliders, each in its own row.
- Slider track: `background: #334155`, height `4px`, border-radius `2px`.
- Filled portion: `background: #3b82f6`.
- Handle: `16px` circle, `background: white`, `border: 2px solid #3b82f6`.
- Label left: min value. Label right: max value. Label far right: "Current: {value}".
- On change: recalculate derived values (GPU Demand GW, power gap) client-side:
  ```
  gpu_demand_gw = (deployed_gpus * gpu_power_draw_w * utilization_pct * pue) / 1_000_000_000
  ```
- All region cards and the gap chart update immediately (no API call).
- Reset button: restores default values (950W, 75%, 1.3).

**Default values and ranges:**

| Slider | Min | Max | Default | Step |
|---|---|---|---|---|
| GPU Power Draw | 700 W | 1200 W | 950 W | 25 W |
| Utilization Rate | 50% | 100% | 75% | 5% |
| PUE | 1.1 | 2.0 | 1.3 | 0.05 |

### 8.4 Source chain drill-down

Every numeric value in the Triangulation tab should be clickable, opening a popover that shows the derivation chain.

**Wireframe (on click of "12.4 GW" in the L1 box):**

```
+------------------------------------------+
|  Source Chain: Contracted Power           |
|  ----------------------------------------|
|  12.4 GW total across 5 companies        |
|                                          |
|  Microsoft   4.2 GW   [->] 8 deals      |
|  Amazon      3.8 GW   [->] 6 deals      |
|  Google      2.1 GW   [->] 4 deals      |
|  Meta        1.5 GW   [->] 3 deals      |
|  Oracle      0.8 GW   [->] 2 deals      |
|                                          |
|  Methodology: Sum of all verified PPA    |
|  contract values from SEC filings and    |
|  press releases.                         |
|                                          |
|  [*] 94% confidence                      |
|  [View all power deals ->]               |
+------------------------------------------+
```

- Popover: positioned below/right of the clicked element.
- Background: `#0f172a`. Border: `1px solid #334155`. Border-radius: 12px.
- Max-width: 360px. Box-shadow: `0 16px 40px rgba(0,0,0,0.6)`.
- Click on `[->] 8 deals` navigates to the Power tab filtered to that company.
- Click on `[View all power deals ->]` switches to the Power tab.
- Popover closes on click outside or Escape key.

### 8.5 Enhanced region cards

The existing region detail cards (TriangulationTab.tsx line 129) should be enhanced:

**Current:**
```
+--Region Name-------[status icon]--+
| Contracted    1.2 GW              |
| GPU Demand    0.9 GW              |
| Deployed GPUs 45k                 |
| Power Gap     0.3 GW              |
| NIC Score     87%                 |
| Permit Signals 12                 |
| Confidence    [====] 85%          |
+-----------------------------------+
```

**Enhanced (add source links and assumptions label):**
```
+--Region Name-------[status icon]--+
| Contracted    1.2 GW  [link]      |
| GPU Demand    0.9 GW  [calc]      |  <- "calc" badge = derived
| Deployed GPUs 45k     [link]      |
| Power Gap     0.3 GW  [calc]      |
| NIC Score     87%     [link]      |
| Permit Signals 12     [link]      |
| Confidence    [====] 85%          |
|                                   |
| [link] = clickable, opens source  |
| [calc] = derived from assumptions |
|         (click to see formula)    |
+-----------------------------------+
```

- `[link]` badge: `ExternalLink` icon, 9px, color `#475569`. On hover: `#60a5fa`. On click: opens the source chain popover.
- `[calc]` badge: `Calculator` icon, 9px, color `#8b5cf6`. On hover shows tooltip: "GPU Demand = 45,000 GPUs x 950W x 75% utilization x 1.3 PUE = 0.9 GW".

---

## 9. Phase 1 Priorities and Sequencing

### Sprint 1 (Week 1-2): Stop the silent failures

| Task | Files touched | Effort |
|---|---|---|
| Enhance `useApi` hook with retry, staleness, lastFetchedAt | `hooks/useApi.ts` | Small |
| Create `ErrorPanel` component | `components/shared/ErrorPanel.tsx` | Small |
| Create `ErrorBoundary` component | `components/shared/ErrorBoundary.tsx` | Small |
| Wrap each tab in `ErrorBoundary` | `App.tsx` | Small |
| Update PowerTab to render errors per section instead of blocking | `components/tabs/PowerTab.tsx` | Medium |
| Update all other tabs to render `ErrorPanel` when `error` is non-null | All 8 tab files | Medium |

**Acceptance criteria:**
- If the backend is down, each tab shows a clear error message with a retry button instead of infinite "Loading..." text.
- If one API call on the Power tab fails, the other sections still render.
- A React render error in any tab is caught and shows a recovery UI.

### Sprint 2 (Week 2-3): Data provenance

| Task | Files touched | Effort |
|---|---|---|
| Create `DataProvenanceBanner` component | `components/shared/DataProvenanceBanner.tsx` | Small |
| Add banner to all 9 tabs | All tab files or `App.tsx` TabContent wrapper | Small |
| Create `ConfidenceBadge` component | `components/shared/ConfidenceBadge.tsx` | Small |
| Add `ConfidenceBadge` to PowerTab KPI cards | `components/tabs/PowerTab.tsx` | Small |
| Add `ConfidenceBadge` to TriangulationTab region cards | `components/tabs/TriangulationTab.tsx` | Small |
| Create `SourceTooltip` component | `components/shared/SourceTooltip.tsx` | Medium |
| Replace default Recharts `<Tooltip>` with `<SourceTooltip>` in PowerTab | `components/tabs/PowerTab.tsx` | Medium |
| Add `CitationFooter` to PowerTab charts | `components/tabs/PowerTab.tsx` | Small |
| Create `tokens.ts` design tokens file | `tokens.ts` | Small |

**Acceptance criteria:**
- Every tab shows a banner indicating whether data is live, mock, or mixed.
- The mock banner has a pulsing animation that cannot be confused with real data.
- Power tab charts show source links and confidence in tooltips.
- Hovering over any bar in the "Contracted Power by Company" chart shows the source and confidence score.

### Sprint 3 (Week 3-4): Loading and filtering

| Task | Files touched | Effort |
|---|---|---|
| Create `LoadingSkeleton` component with 3 variants | `components/shared/LoadingSkeleton.tsx` | Medium |
| Add shimmer CSS animation | `index.css` or inline style injection | Small |
| Replace `LoadingSpinner` in all tabs with `LoadingSkeleton` | All tab files | Medium |
| Implement progressive loading in PowerTab | `components/tabs/PowerTab.tsx` | Medium |
| Create `FilterContext` | `context/FilterContext.tsx` | Medium |
| Create `GlobalFilterBar` with CompanyMultiSelect | `components/shared/GlobalFilterBar.tsx` | Medium |
| Wire FilterContext into PowerTab and PermitsTab | 2 tab files + `App.tsx` | Medium |

**Acceptance criteria:**
- Tab content shows skeleton placeholders instead of "Loading..." text.
- PowerTab renders each section as its data arrives (no all-or-nothing blocking).
- Company chip filters in the GlobalFilterBar persist when switching between Power and Permits tabs.

### Sprint 4 (Week 4-5): Triangulation redesign

| Task | Files touched | Effort |
|---|---|---|
| Build flow visualization (L1 through L4 boxes with arrows) | `components/tabs/TriangulationTab.tsx` | Large |
| Build assumption sliders | `components/tabs/TriangulationTab.tsx` | Medium |
| Client-side recalculation of GPU demand and power gap | `components/tabs/TriangulationTab.tsx` | Medium |
| Build source chain popover | `components/shared/SourceChainPopover.tsx` | Large |
| Wire clickable numbers in region cards | `components/tabs/TriangulationTab.tsx` | Medium |
| Add cross-tab navigation (click company in source chain -> Power tab filtered) | `App.tsx`, `FilterContext.tsx` | Medium |

**Acceptance criteria:**
- The Triangulation tab shows a clear visual flow from Power through Permits.
- Adjusting the GPU power draw slider immediately updates the gap analysis chart and region cards.
- Clicking any numeric value opens a popover explaining its derivation with links to source data.
- Clicking a company name in the source chain popover navigates to the Power tab filtered to that company.

### Sprint 5 (Week 5-6): Polish and remaining tabs

| Task | Files touched | Effort |
|---|---|---|
| Add `SourceTooltip` to all remaining charts (GPU, NICs, TSMC, Permits) | 4 tab files | Medium |
| Add `CitationFooter` to all remaining charts | 4 tab files | Small |
| Add `GeographySelect` to GlobalFilterBar | `GlobalFilterBar.tsx` | Small |
| Add `QuarterRangeSlider` to GlobalFilterBar | `GlobalFilterBar.tsx`, `QuarterRangeSlider.tsx` | Medium |
| Wire filters to all tabs | All tab files | Medium |
| Background refresh indicator | `components/shared/RefreshBar.tsx` | Small |
| Stale data warning banner | Uses existing `DataProvenanceBanner` | Small |

---

## 10. Accessibility Notes

### Keyboard navigation

- All interactive elements (buttons, chip toggles, sliders, chart drill-downs) must be reachable via Tab key.
- Focus ring: `2px solid #3b82f6`, offset `2px`. Apply via `outline` on `:focus-visible`, not `:focus` (avoid showing rings on mouse click).
- Escape key closes all popovers, modals, and dropdowns.
- Enter/Space activates buttons, toggles chips, expands rows.

### Screen reader support

- Error panels: use `role="alert"` so screen readers announce errors immediately.
- Loading skeletons: add `aria-busy="true"` and `aria-label="Loading data"` on the container.
- Confidence badges: add `aria-label="Confidence: 94 percent, high"`.
- DataProvenanceBanner: use `role="status"` for live/mixed and `role="alert"` for mock.
- Chart tooltips: Recharts tooltips are not keyboard-accessible. Add a visually hidden data table below each chart with `<caption>` explaining the data. This table is visible to screen readers and also serves as a fallback for users who cannot interact with the chart.

### Color contrast

- All text/background combinations already meet WCAG AA (4.5:1) for the existing palette:
  - `#94a3b8` on `#1e293b` = 5.1:1 (pass)
  - `#ffffff` on `#1e293b` = 12.6:1 (pass)
  - `#64748b` on `#1e293b` = 3.2:1 (**fails AA for body text**) -- use `#94a3b8` instead for any text smaller than 18px.
- Confidence badge colors: do not rely on color alone. The percentage label and tooltip text ("High confidence") provide the same information.

### Motion sensitivity

- The skeleton shimmer animation should respect `prefers-reduced-motion`:
  ```css
  @media (prefers-reduced-motion: reduce) {
    .skeleton-bar {
      animation: none;
      background: #1e293b;
    }
  }
  ```
- The mock data banner pulsing border should also be disabled under `prefers-reduced-motion`.

### Touch targets

- All clickable elements must be at least 44x44px (or have 44px of combined element + padding).
- The existing tab buttons (padding `12px 16px`, font `13px`) produce approximately 38px height. Increase padding to `14px 16px` to reach 44px.

---

### OCI %-Share KPI Tile (§5 of 00-DECISIONS-AND-CONSTRAINTS.md)

Every category tab (Power, GPU, NICs/Optics, TSMC, Permits, Triangulation) displays a small KPI tile showing OCI's percentage of the tracked total. **Role-parameterized** per the canonical computation in `03-architecture-design.md` — a single number is meaningless because OCI plays multiple roles (provider, end_user, financing, etc.) and the answer differs per role.

**Component:** `<OciShareTile tab="power" defaultRole="provider" />`
**Data source:** `GET /api/{tab}/oci-share?role=<role>`
**Display:**
- OCI logo + percentage value (e.g. "2.3%")
- Absolute value + unit (e.g. "150 MW")
- Trend arrow (vs prior quarter)
- **Role pill / segmented toggle** below the percentage: `Provider · End-user · Any` (set per-tab default; user can switch). The pill sits inline so the visual placement of the existing KPI tile does not change.
- `multi_tenant_warning` icon (small ⚠) when end-user aggregation may double-count multi-tenant sites; tooltip explains the rule.

**Placement:** Top-right of each tab's header area, next to existing KPI tiles. **Visual layout unchanged** — the role toggle is a small addition inside the tile, not a new tile.

**States:** Loading skeleton → real data → error fallback ("OCI share unavailable").

**Per-tab default role** (overridable via toggle, mirrors `03-architecture-design.md` §4):

| Tab | Default role | Reason |
|---|---|---|
| Power | `provider` | Owned footprint is the more conservative number for capacity-planning. |
| GPU / NICs / Optics / TSMC | `end_user` | Inferred from EDGAR; the "who is buying / running these chips" question. |
| Permits (building) | `provider` | Who's filing for new construction. |
| Permits (generator/air) | `permit_parent` | Resolved through the multi-signal LLC→parent scorer (§7.5 of `03-PIPELINE-ARCHITECTURE.md`). |
| Triangulation | `provider` | L1 (contracted GW) is naturally a provider concept. |

### Energy Supply Tab (New — §3.4 of 00-DECISIONS-AND-CONSTRAINTS.md)

A new tab added next to existing tabs (do not replace any existing tab).

**Data source:** `GET /api/energy-projects` (from `Energy Project Inventory Data Sample.xlsx`, 1695 rows × 65 cols)
**Key fields:** project_name, flg_btm_project, developer_companies, customer_companies, tot_contracted_power_mw, tot_project_cost, project_footprint_acreage
**Views:**
- Table view with sortable columns
- Map view showing project locations
- Developer/customer company filter
- BTM (behind-the-meter) toggle filter
**OCI %-share tile** included at top

### Companies Tab + Company Detail Page (New — additive, §5 of 00-DECISIONS-AND-CONSTRAINTS.md)

A new top-level **Companies** tab next to existing tabs (do not replace any existing tab). Two views: a directory and a per-company detail page.

#### Companies directory (`/companies`)

A leaderboard / directory of every tracked company, with role distribution at-a-glance.

**Component:** `<CompaniesDirectory />`
**Data source:** `GET /api/companies?top=N&order_by=site_count|mw_total&role=<role>` (see `03-architecture-design.md` §4)
**Display:**
- Sortable table: company name, public/private, ticker, parent, **role bar** (small horizontal stacked bar showing what % of this company's site associations fall into each role), total tracked MW (sum across `provider` role), # sites where it's `end_user`, # where it's `financing`, etc.
- Row click → Company detail page.
- Default sort: total MW (descending) for `provider` role.
- Role filter chip: filter the directory to companies that fill a specific role anywhere.

#### Company detail page (`/companies/{id}`)

Drill-down view per company. **This is the answer to "what is OCI's footprint and how does it compare to a hyperscaler?"**

**Component:** `<CompanyDetail companyId={id} />`
**Data sources:**
- `GET /api/companies/{id}` — canonical name, ticker, CIK, parent, aliases, public/private.
- `GET /api/companies/{id}/role-summary` — `{provider: {site_count, mw_total}, end_user: {site_count, mw_total}, financing: {...}, ...}`.
- `GET /api/companies/{id}/sites?role=<role>` — drill-down to the underlying site list.

**Sections (top to bottom):**

1. **Header.** Company name, logo (if available from a curated mapping), ticker / CIK, parent link if subsidiary, public/private badge, "Major role" tag (the role with the highest site_count for this company).
2. **Role distribution card.** A donut or stacked-bar showing this company's site-association count by role (Provider / End-user / Financing / Equipment / Utility / Developer / Customer / Permittee LLC / Permit parent). Click a slice → filters section 3 to that role.
3. **Footprint table.** Per role: site count, MW total (with note when `multi_tenant_warning` applies), top 3 geographies. Mirrors the queries the user asked for (self-owned vs end-user-only).
4. **Sites map + list.** Map view of all sites where this company plays *any* role; markers colored by role. List below with role chips per row. Filter chips: state, role, stage.
5. **Events timeline.** Reuse the `<EventsTimeline />` component, scoped to events on this company's sites.
6. **Lineage panel.** "How we attribute this company" — links to source URLs, alias confidence, parent-attribution evidence (relevant for resolved LLCs).

**States:** Loading skeleton → data → empty (rare; means no associations yet, surface "no recorded role yet" with a link to ingest sources).

**Visual rule:** This is a *new* page, not a modification of any existing page. Existing tabs and components untouched.

### Site Detail Role-Breakdown Card (New — additive, §5 of 00-DECISIONS-AND-CONSTRAINTS.md)

The site detail view (`/sites/{aterio_dc_uid}`) gains a new card showing **companies grouped by role on this site**. Existing site detail content is preserved.

**Component:** `<SiteRoleBreakdown siteId={id} />`
**Data source:** `GET /api/sites/{aterio_dc_uid}/role-summary` — returns `{provider: [...], provider_backer: [...], end_user: [...], financing: [...], equipment: [...], utility: [...], permittee_llc: [...], permit_parent: [...]}` with confidence per company.

**Display:**
- One row per role; left column = role label; right column = company chips.
- Each chip shows: company name + tiny confidence dot (green/yellow/red bands matching `<ConfidenceBadge />`).
- Click a chip → Company detail page.
- Empty roles render as muted "—" rather than being hidden, so absences are visible (e.g. "no `permittee_llc` recorded yet").
- For multi-tenant `end_user` lists, show `mw_share` next to each chip if populated (e.g. "Microsoft 60 MW / 200 MW").

**Placement:** New card inserted after the existing power/timeline/source-link cards on the site detail page. Existing layout untouched.

### Coverage Badge + Per-State Empty States (New — additive, §5.3 of 00-DECISIONS-AND-CONSTRAINTS.md)

National MVP scope means coverage varies per pillar per state. The UI **must** tell the truth — silent partial-coverage rendering is a defect. Three additive surfaces deliver this:

#### 1. `<CoverageBadge />` — small chip in every tab header

**Component:** `<CoverageBadge pillar="building_permits" />`
**Data source:** `GET /api/coverage/{pillar}` — returns coverage rows aggregated for that pillar.
**Display variants:**

| Status | Color | Label | Tooltip content |
|---|---|---|---|
| `full` (all 50 + DC) | Green | "All US — full coverage" | "Sourced from {sources}; last refreshed {last_ingested_at}." |
| `federal_baseline` only | Amber | "Federal baseline only" | "EPA ECHO/CAMD covers all 50 states at federal level. State-level depth pending." |
| `partial (N states)` | Amber | e.g. "6 states — VA, NY, WA, CO, OR, TX" | Lists the covered states. |
| `single_source` | Orange | "Single source / region" | e.g. "PJM territory only — covers 13 states + DC." |
| `unavailable` | Red | "No coverage" | "No free national source identified. Phase-2 paid alternative: {Shovels.ai/FMP/etc.}." |

**Placement:** top-right corner of the tab header, inline with existing KPI tiles. Visually compact (~24 px tall pill). Click → opens the Coverage page filtered to this pillar.

#### 2. Per-state empty states on geographic visualizations

When the user clicks/filters to a state with no data for the active pillar, the view renders an explicit message rather than an empty chart or zero bar.

**Component:** `<NoStateCoverage pillar={p} stateCode={s} />`
**Data source:** `GET /api/coverage/by-state/{state_code}`
**Display:** a card occupying the chart area:
```
[Iowa]  No building-permit coverage yet

  Federal air-permit baseline (EPA ECHO) is available — switch ↗
  Or see the Coverage roadmap: standing-records request to IA DNR pending.

  ↳ Try a state with full coverage: VA, NY, WA, CO, OR
```
**Behavior:** never shows "0 records" or a flat baseline; always names what *is* available and provides a one-click switch. Pulls suggested-alternative pillars from the same `/api/coverage/by-state/` payload.

#### 3. Coverage page (additive to the existing Sources tab)

A dedicated page summarizing per-pillar per-state coverage, last-ingested timestamps, freshness vs SLA, and the "what's missing and why" roadmap.

**Component:** `<CoveragePage />` mounted under the existing **Sources** tab as a new sub-route (does not replace existing Sources content).
**Data source:** `GET /api/coverage`
**Layout:**
- **Pillar × State matrix** at the top — rows = pillars (Power · SEC · building permits · generator permits · ISO queues · earnings · satellite · triangulation), columns = state codes (`US` first, then states). Each cell colored by `coverage_status`. Click any cell → drill-down panel with sources, record_count, last_ingested_at, roadmap text.
- **Source list panel** to the right — full list of sources with last-run status (reuses the existing Agents/Sources visual style; no new look).
- **Roadmap section** at the bottom — items with `coverage_status='pending'` listed as a backlog with target trigger conditions (drawn from the `roadmap` column and from `docs/OPEN-TENSIONS.md`).

**Visual rule:** matches the existing dashboard aesthetic; reuses `<ConfidenceBadge>` color palette for the matrix cells and the existing card components for source rows. No new design tokens beyond what's already in §3.

#### 4. API responses include a `coverage` envelope

Every endpoint that aggregates across states/sources adds a `coverage` block alongside the existing `lineage` envelope:
```json
{
  "data": [...],
  "lineage": {...},
  "coverage": {
    "pillar": "building_permits",
    "states_included": ["VA", "NY", "WA", "CO", "OR"],
    "states_excluded_with_reason": {
      "IA": "unavailable — pending standing-records request",
      "AZ": "unavailable — pending standing-records request",
      "*": "43 other states have no free building-permit feed in MVP"
    },
    "freshness_status": "ok"
  }
}
```
Frontend chart components read this and render the badge + empty-state automatically — no per-tab duplication of "is this covered" logic.

### Triangulation Q&A Chat Panel (New — additive, §4.2 Agent D of 00-DECISIONS-AND-CONSTRAINTS.md)

A docked chat panel powered by the Triangulation Q&A agent (Llama Stack `oci/openai.gpt-5.4` with tool-use). This is how the user's "is there enough power for the GPUs being shipped in Texas?" question becomes a typeable interaction, not a navigation puzzle. **Strictly additive** — no existing tab or component is modified.

**Component:** `<QaChatPanel />`
**Data source:** `POST /api/agent/qa` (SSE streaming) + `GET /api/agent/qa/conversations/{id}` (history).
**Placement:** small "Ask" button (chat icon, ~36 px) docked at the bottom-right corner of the dashboard, persistent across all tabs. Click → opens a side drawer (~480 px wide, full height); does NOT cover the existing layout, just slides in over it. Click outside or press Esc closes. Visual styling matches the existing card components — no new design tokens.

**Behavior:**
- Conversation persists across page navigation via `conversation_id` in localStorage; history fetched on open.
- Streamed responses render Markdown progressively. Tool calls render inline as collapsible cards as they happen — `query_oci_share(tab=power, role=provider, state=TX)` → small chip showing tool name, args (truncated), and the agent's interpretation of the result.
- Each numeric claim in the agent's response is **citation-linked** to the underlying `/api/...` endpoint or `<SourceTooltip />` it queried. Same source-link pattern as charts.
- "Open as page" button → expands the conversation to a full-page route (`/qa/{conversation_id}`) for longer reads or sharing.
- Empty state (first open): suggested prompts seeded from PRD success metrics, e.g. "How does OCI's contracted GW in Texas compare to Microsoft's?", "Which states have full triangulation coverage?", "What changed in NoVA permits this week?".
- **Service-degraded banner** when Llama Stack is unavailable (per the §4.2 fallback rule): chat goes read-only with a "Q&A agent is offline; tabs continue to work" message; no errors thrown.

**Suggested prompts use the role model (§5.1):** the agent has `role` enum knowledge baked into its system prompt and will ask clarifying questions ("Are you asking about OCI's owned footprint or total operational presence?") when role is ambiguous.

### Weekly Brief Card (New — additive, §4.2 Agent E of 00-DECISIONS-AND-CONSTRAINTS.md)

A dashboard card surfacing the latest Markdown briefing generated by the Weekly Brief agent (Llama Stack `oci/openai.gpt-5.4-mini`, runs Sunday 23:00 ET). Bridges the static dashboard to actionable insights — what *changed* this week, not just what *is*.

**Component:** `<WeeklyBriefCard />`
**Data source:** `GET /api/brief/weekly` (cached; `?as_of=YYYY-MM-DD` for historical).
**Placement:** new card at the top of the **Sources / Coverage** page. **Not** placed on the Power/GPU/etc. tabs (would clutter); a small "View this week's brief" link in the dashboard header points to it.

**Display:**
- Header: "Week of {date}" + agent run timestamp + freshness indicator (green if generated within the last 8 days; amber otherwise).
- Markdown body: 5–10 bullets covering new permits, MW deltas by company, coverage status changes, anomalies. Each bullet that references a metric carries the same `<SourceTooltip />` linking to the underlying record.
- "Why these bullets?" expandable: shows the agent's tool-call trace (which queries it ran to assemble the brief), backed by `LlmEvidenceTrail`.
- "View prior briefs" link → `<WeeklyBriefHistory />` modal listing past 12 weeks.

**Behavior:**
- Briefs are generated by the agent on cron; the card just reads the cached result. No latency on dashboard load.
- If the most recent brief is older than 14 days, card shows an explicit staleness state with a "Generate now" admin button (gated; for ops use during incidents). No silent staleness.

### LLM Evidence Trail (New — additive, supports agent C/D/E)

A reusable popover component that any number can opt into to show its provenance when the value was produced by an LLM agent (LLC parent attribution, Q&A claim, brief bullet).

**Component:** `<LlmEvidenceTrail llmRunId={id} />`
**Data source:** `GET /api/agent/runs/{llm_run_id}` (returns the row from `llm_extraction_runs` including `tool_calls` JSONB).
**Display:** on hover or click, a popover renders:
- Agent name + model + prompt version
- Each tool call: name, args, result excerpt, latency, confidence contribution
- Self-reported confidence + status (`success` / `fallback`)
- Direct link to view the raw run record (admin-only).

**Where it surfaces in MVP:**
- Next to every `permit_parent` (resolved LLC parent) chip in the Site detail role-breakdown card and Companies tab.
- Inline on Q&A chat agent responses next to each tool-call bubble.
- On every Weekly Brief bullet that references an LLM-extracted value.

**Visual rule:** identical visual treatment to the existing `<SourceTooltip />` — lineage UI is a single coherent affordance whether the source is a SEC URL or an agent run.

### Events Timeline (New — §3.3 of 00-DECISIONS-AND-CONSTRAINTS.md)

Additive sub-section on relevant tabs (Power, Permits, Satellite).

**Data source:** `GET /api/events` (from Data Centers Events sheet, 957 rows × 48 cols)
**Display:** Vertical timeline component showing: event_type icon, event_date, event_description, linked site name (clickable → site detail)
**Filters:** Date range, event type, site/provider
**Placement:** Below existing content on Power/Permits/Satellite tabs as a collapsible section

### Broken UI Fixes Required (§5 of 00-DECISIONS-AND-CONSTRAINTS.md)

| # | Issue | Fix | Target File(s) |
|---|---|---|---|
| 1 | Silent EDGAR `except Exception` | Replace with structured error handling + error UI | `edgar_agent.py`, error boundary component |
| 2 | Blocking sync `urllib` in FastAPI | Replace with `httpx` async | `edgar_agent.py` |
| 3 | `useApi` swallows errors with no error UI | Add error state rendering to all `useApi` consumers | Frontend API hooks |
| 4 | `random.*` mock confidence scores | Replace with deterministic formula: `base + MW_match + counterparty + source_type` | `mock_data.py` → real pipeline |
| 5 | Hardcoded `http://localhost:8000` API base | Use environment variable / relative URL | Frontend config |
| 6 | CORS `*` wildcard | Restrict to OCI VM origin | `main.py` CORS config |
| 7 | Google Maps API key in committed `.env.local` | Move to environment variable, add `.env.local` to `.gitignore` | `.env.local`, `.gitignore` |
| 8 | Missing `requirements.txt` | Generate from current dependencies | Project root |

---

## Appendix A: Interaction States Matrix

| Component | Default | Hover | Focus | Active | Disabled | Error | Loading |
|---|---|---|---|---|---|---|---|
| Card (`CARD_STYLE`) | `bg: #1e293b, border: #334155` | `bg: #253347` | `outline: 2px #3b82f6` | -- | `opacity: 0.5` | `border-left: 3px #ef4444` | Skeleton shimmer |
| Chip (company filter) | `bg: transparent, border: #334155, color: #64748b` | `border: company color` | `outline: 2px #3b82f6` | `bg: company color 20%` | `opacity: 0.4` | -- | -- |
| Button (primary) | `bg: #3b82f6, color: white` | `bg: #2563eb` | `outline: 2px #60a5fa` | `bg: #1d4ed8` | `bg: #334155, color: #64748b` | -- | spinner icon |
| Button (ghost) | `bg: transparent, border: #334155, color: #64748b` | `border: #94a3b8, color: #94a3b8` | `outline: 2px #3b82f6` | `bg: #1e293b` | `opacity: 0.4` | -- | -- |
| Table row | `bg: transparent` | `bg: #162032` | `outline: 2px #3b82f6` | `bg: #162032` | -- | -- | skeleton bars |
| Slider track | `bg: #334155` | -- | `outline on handle` | -- | `opacity: 0.4` | -- | -- |
| Slider handle | `bg: white, border: #3b82f6` | `scale: 1.15` | `outline: 2px #3b82f6, scale: 1.15` | `bg: #3b82f6` | `bg: #64748b` | -- | -- |
| Source link | `color: #60a5fa` | `color: #93c5fd, underline` | `outline: 2px #3b82f6` | `color: #3b82f6` | -- | -- | -- |

## Appendix B: Content/Copy Guidelines

### Error messages

- Use plain language. Do not expose raw HTTP status codes or stack traces to the user.
- Pattern: "[What happened]. [What the user can do]."
- Example: "Could not load power data. Check your connection and try again."
- Never blame the user. Say "Something went wrong" not "You made an error."

### Data labels

- Use consistent units: GW (not gigawatts or gw), MW, %, k (thousands).
- Always include the unit in chart axis labels and tooltip values.
- Quarter format: "Q1 2024" (not "2024Q1" or "1Q24").

### Mock data warnings

- Be direct and unambiguous. The word "simulated" is clearer than "sample" or "demo."
- Include the consequence: "Numbers change on each page refresh."
- Do not apologize ("Sorry, this is mock data"). State facts.

### Confidence labels

- >= 0.9: "High confidence -- verified against primary sources"
- >= 0.75: "Moderate confidence -- derived or cross-referenced"
- < 0.75: "Low confidence -- estimated, treat with caution"

### Source attribution

- Always name the source type: "SEC EDGAR 10-K", "Press Release", "County Permit Database", "NVIDIA Earnings Transcript".
- Include retrieval date in ISO format with timezone: "2024-12-15 09:00 UTC".
- For derived/calculated values: "Calculated from [input A] and [input B] using [method]."

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§5 UX Rule:** All changes are additive. No existing component, page, function, or endpoint removed. No visual changes to existing tabs.
- **New additions:** OCI %-share KPI tile (every tab), Energy Supply tab, Events Timeline section.
- **Broken UI fixes:** 8 issues identified and targeted.
- **OCI %-share computation:** Defined in `03-architecture-design.md`; this doc specifies the frontend presentation.
