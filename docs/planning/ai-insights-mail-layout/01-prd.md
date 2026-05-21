# PRD: AI Insights Tab — Mail App Layout

**Owner:** PM | **Date:** 2026-05-13 | **Status:** For live demo today

## Problem
Today the AI Insights tab stacks Snapshot, Past Runs, and Saved sections vertically, producing a long scroll and making it hard to compare insights across runs. We need a mail-app feel: a left sidebar of headlines plus a right detail pane so analysts can switch context instantly.

## Target Layout
```
+-----------------------------------------------------------+
|  Header banner (spans both columns)                       |
+----------------------+------------------------------------+
| Sidebar (320px)      | Main detail pane                   |
|                      |                                    |
| v Today (4)          |  [Full InsightCard for selected]   |
|   - headline 1  *    |   - title, body, chart             |
|   - headline 2       |   - Save button, citations         |
|   - headline 3       |                                    |
|   - headline 4       |                                    |
| v Saved (N)          |                                    |
|   - compact row      |                                    |
| > Past Runs (12)     |                                    |
+----------------------+------------------------------------+
```
- Sidebar = 320px fixed; 3 collapsible groups: **Today (4)** open by default, **Saved (N)** open if N>0, **Past Runs (12)** collapsed.
- Main pane renders the full `InsightCard` for the selected row.
- Below 1024px viewport: fall back to single column (sidebar stacked above detail).

## User Stories

**US1** — As an analyst, I want a sidebar of all my insight headlines so I can switch contexts without scrolling.
- All three groups render with correct counts in their headers.
- Clicking any row sets it as selected and updates the main pane.
- Selected row has a visible active-state style.

**US2** — As an analyst, I want today's insights selected by default so the demo opens to a useful state.
- On page load, Today group is expanded and its first headline is auto-selected.
- Main pane renders that insight's full card (body, chart, Save) on first paint.

**US3** — As an analyst, I want past-run sessions to expand inline in the sidebar so I can dig into history without leaving the detail view.
- Clicking Past Runs header toggles the group open/closed.
- Clicking a session row reveals that session's insight headlines nested beneath it.
- Clicking a nested headline loads it into the main pane; main layout does not shift.

## Acceptance Criteria (must-pass for demo)
- Page load shows today's 4 headlines in the sidebar; first auto-selected; its body/chart/Save renders on the right.
- Clicking another Today row updates the main pane within 1 frame (no spinner flash).
- Clicking the Saved header expands the group and shows compact saved rows.
- Clicking Past Runs expands the group; clicking a session reveals its insights inline; clicking one loads it in the detail pane.
- Saving in the detail pane flips the saved indicator on the corresponding sidebar row immediately.
- `vitest` passes.

## Out of Scope
- Mobile/responsive polish below 1024px (single-column fallback only).
- Resizable sidebar.
- Search, filter, or sort in the sidebar.
- Keyboard navigation between rows.
- Backend changes.

## Risks / Non-Risks
Main risk: lifting selection state out of `SnapshotInsightFeed` and `PastRunsSection` could regress the existing Save flow or saved-indicator wiring. Mitigation: the detail pane re-uses `InsightCard` verbatim with its existing props; we only lift `selectedInsightId` up to `AIInsightsTab` and pass it down. Existing hooks (`useSavedInsights`, `useLatestInsightSession`, `useSessionHistory`) remain untouched. No API contract changes, so backend regression risk is zero.
