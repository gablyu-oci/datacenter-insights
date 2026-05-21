# Company Directory — Search, Filter, Sort, Pagination

Status: Draft
Owner: PM (Strategic Insights Tool)
Date: 2026-05-13
Surface: `frontend/src/components/tabs/CompaniesTab.tsx`
Related backend spec: Companies list API (drafted separately)

## Problem Statement

The Company Directory on the Companies tab loads `/api/companies/?order_by=site_count&page_size=50` exactly once on mount and renders the first 50 rows, while the header proudly reports `"{total} companies tracked"` — so users see a count (often well over 50) that does not match the visible table. Column-header sort only reorders the already-loaded slice, which silently produces wrong results (e.g. clicking "Total MW desc" misses larger companies sitting on page 2+). There is no search box, no role / public-private filter, and no pagination control. Analysts cannot find a company by name or ticker, cannot scope to Operators or Public companies, and cannot trust the sort order. The directory is effectively a truncated, mis-sortable preview rather than a directory.

## Goals

- Show all companies, not just the first 50, via real pagination.
- Server-side search by company name OR ticker substring.
- Server-side filter by Role (Operator / Owner / Tenant / Developer / Lessor) and by Public / Private.
- Server-side sort by Company, Ticker, Sites, Total MW — ascending or descending — across the full dataset.
- Pagination control with "Showing X–Y of TOTAL" affordance, 50 rows per page.
- Minimum-MW threshold input (v1: client-side over the current page; explicitly flagged in UI as a v1 limitation).
- Header count and visible rows must be consistent with the active filter set.

## Non-Goals (Out of Scope for v1)

- Server-side `minMW` filter (v1 is client-side, current page only).
- Column resize / reorder.
- Saved filter presets or shareable filter URLs beyond basic query-state.
- CSV / Excel export.
- Per-column inline filters (e.g. a filter dropdown inside each header cell).
- Multi-column / tri-state sort.

## User Stories

1. **Search by name or ticker**
   As an analyst, I want to type "vist" or "VST" in a search box so that the directory narrows to companies whose name or ticker contains that substring, server-side, across the entire dataset.

2. **Filter by Role**
   As an analyst, I want to pick one or more Roles (Operator, Owner, Tenant, Developer, Lessor) so that I only see companies playing that role in our tracked sites.

3. **Filter by Public / Private**
   As an analyst, I want to toggle Public vs Private (or both) so that I can scope analysis to publicly-traded names when cross-referencing earnings data.

4. **Sort across the full dataset**
   As an analyst, I want to click any of the Company / Ticker / Sites / Total MW headers and have the server re-sort the entire result set ascending or descending, not just the page I am looking at.

5. **Paginate 50 at a time**
   As an analyst, I want Prev / Next (and page number) controls with a clear "Showing 51–100 of 312" label so I know exactly where I am and that nothing is hidden.

6. **Minimum MW threshold (v1, client-side)**
   As an analyst, I want to enter a minimum Total MW value and immediately drop rows below it on the current page, with a small note that this filter is page-local in v1.

7. **Consistent counts**
   As an analyst, I want the header `"N companies tracked"` to reflect the TOTAL matching my current filters, not the unfiltered universe, so the number and the table agree.

## Acceptance Criteria

- [ ] Mounting CompaniesTab issues a single request with current `q`, `roles`, `public_private`, `order_by`, `direction`, `page`, `page_size=50`.
- [ ] Typing in the search box debounces (~300ms) and refetches; empty `q` is omitted from the request.
- [ ] Role filter supports multi-select; selecting zero roles is treated as "no role filter".
- [ ] Public/Private filter is tri-state: Public, Private, Both (default Both).
- [ ] Clicking a sortable header sets `order_by` and toggles `direction` (asc↔desc); active sort is visually indicated with an arrow.
- [ ] Pagination renders "Showing X–Y of TOTAL" where TOTAL is the filtered total returned by the API.
- [ ] Prev is disabled on page 1; Next is disabled when `X + page_size > TOTAL`.
- [ ] Changing any filter or sort resets to `page=1`.
- [ ] Min-MW input filters rows on the current page only and shows the helper text "v1: applies to current page".
- [ ] Header label reads `"{filtered_total} companies tracked"` and matches API `total`.
- [ ] No console errors; loading and empty states are handled (spinner on fetch, "No companies match these filters" when total=0).
- [ ] Existing row click / drill-through behavior is preserved.

## API Contract Delta

The frontend will rely on the already-drafted backend spec. New / widened query params on `GET /api/companies/`:

| Param            | Type    | Notes                                                                 |
|------------------|---------|-----------------------------------------------------------------------|
| `q`              | string  | Case-insensitive substring match over `name` OR `ticker`.             |
| `roles`          | string  | Comma-separated subset of `operator,owner,tenant,developer,lessor`.    |
| `public_private` | enum    | `public` \| `private` \| `both` (default `both`).                     |
| `order_by`       | enum    | Widened to `name` \| `ticker` \| `site_count` \| `total_mw`.          |
| `direction`      | enum    | `asc` \| `desc` (default `desc` for numeric, `asc` for text).         |
| `page`           | int     | 1-indexed; default 1.                                                 |
| `page_size`      | int     | Default 50, max 100.                                                  |

Response shape (unchanged besides `total` being post-filter):
```
{ "items": [...], "total": <int>, "page": <int>, "page_size": <int> }
```

## Open Questions

1. Should `q` also match ticker aliases / former tickers (e.g. FB→META), or strict current-ticker only for v1?
2. Do we persist filter/sort/page state in the URL query string so analysts can share a link, or keep it component-local for v1?
