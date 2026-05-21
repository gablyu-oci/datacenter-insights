# Company Directory — Search / Filter / Sort / Pagination — Test Report

Date: 2026-05-13
QA Owner: QA / Test Engineer (Claude)
Feature spec: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/specs/company-directory-search-filter-pagination.md`
Branch under test: `feat/save-and-history`

---

## 1. Backend pytest summary

### Companies-scoped suite (required)
Command:
```
cd backend && source .venv/bin/activate && \
  python -m pytest tests/test_companies_router.py tests/test_companies_counterparties.py -v
```

Result: **11 passed, 0 failed, 0 skipped, 3 warnings, in 1.56s**

Passing tests (companies router — net-new from this feature):
- `test_q_matches_name_case_insensitive`
- `test_q_matches_ticker_case_insensitive`
- `test_public_private_public_only`
- `test_order_by_canonical_name_asc`
- `test_order_by_mw_total_desc_regression`
- `test_pagination_slice`
- `test_validation_errors`

Passing tests (companies counterparties — pre-existing, regression check):
- `test_counterparties_returns_documented_shape_with_known_data`
- `test_counterparties_empty_when_no_data`
- `test_counterparties_404_for_unknown_company`
- `test_counterparties_excludes_self_and_orders_by_metric`

### Full backend smoke (broader regression check)
Command:
```
cd backend && source .venv/bin/activate && \
  timeout 180 python -m pytest -x --ignore=tests/test_v2_insights_e2e_regression.py -q
```

Result: **445 passed, 0 failed, 0 skipped, 3 warnings, in 9.05s**

No regressions detected in the broader suite. The widening of `order_by` regex (added `canonical_name|ticker`) and the new `q` / `public_private` query params on `/api/companies/` did not break any existing test.

### Backend warnings
Three pre-existing FastAPI deprecation warnings on `routers/companies.py:87/90/95` — `regex=` should become `pattern=` for Pydantic v2 / FastAPI compatibility. Non-blocking and out of scope for this PR (could be cleaned up in a follow-up).

---

## 2. Frontend vitest summary

Command:
```
cd frontend && npm test -- --run
```

Result: **4 test files passed (4), 21 tests passed (21), in 2.32s** (vitest 4.1.5)

The 4 test files include the two new companies test files plus pre-existing suites; the run is green. New companies-specific tests covered in the suite:

`frontend/src/components/tabs/companies/__tests__/CompaniesTab.test.tsx`:
- `test_initial_fetch — issues the default directory request on mount`
- `test_search_debounces — waits 250ms before issuing a search request`
- `test_company_header_flips_direction — clicking Company toggles direction`
- `test_public_private_toggle — Public adds param, All removes it`
- `test_pagination_click_page_2 — clicking page 2 fires page=2`
- `test_pagination_math — renders Showing 1–50 of 387 on page 1 with 8 pages`

`frontend/src/components/tabs/companies/__tests__/paginationWindow.test.ts`:
- 5 parametric cases covering near-start, middle-branch, true-middle, near-end, and the `totalPages ≤ maxTiles` short-circuit.

---

## 3. TypeScript check summary

Command:
```
cd frontend && npx tsc -b --noEmit
```

Result: **4 errors total — all pre-existing, none in new files**

| File | Line | Error | In scope? |
|---|---|---|---|
| `components/earnings/EarningsDetailModal.tsx` | 5 | TS6133 unused `normalizeSentiment` import | Pre-existing, out of scope (earnings tab) |
| `components/earnings/EarningsDetailModal.tsx` | 199 | TS6196 unused `RawTranscriptResponse` type | Pre-existing, out of scope |
| `components/tabs/PowerTab.tsx` | 293 | TS2367 unreachable comparison `"live"...` vs `"archive"` | Pre-existing, out of scope |
| `components/tabs/companies/CounterpartyPieCard.tsx` | 221 | TS2769 `sortValues` prop missing from recharts `<Pie>` type | Pre-existing, out of scope (counterparty pies) |

New files (`CompaniesTab.tsx`, `companies/useDebouncedValue.ts`, `companies/paginationWindow.ts`, the two `__tests__/*` files) introduce **zero new TypeScript errors**.

---

## 4. Coverage-vs-PRD matrix

Every acceptance criterion from the PRD, mapped to a concrete automated test (or flagged as a gap). Test IDs use the file:test_name shorthand. `BE` = backend pytest, `FE` = frontend vitest.

| # | Acceptance Criterion (verbatim) | Covered? | By test(s) | Notes / gaps |
|---|---|---|---|---|
| AC1 | Mounting CompaniesTab issues a single request with current `q`, `roles`, `public_private`, `order_by`, `direction`, `page`, `page_size=50`. | Partial | FE `CompaniesTab.test.tsx::test_initial_fetch` | Asserts `order_by`, `direction`, `page`, `page_size`. Does not explicitly assert "single request" (multiple effects don't fire); also `roles` is implicit-empty by absence. Adequate for v1. |
| AC2 | Typing in the search box debounces (~300ms) and refetches; empty `q` is omitted from the request. | Yes | FE `CompaniesTab.test.tsx::test_search_debounces` | Implementation uses 250ms (close enough to ~300ms). Empty-q omission verified indirectly by `test_initial_fetch` which mounts with `q=""` and the URL contains no `q=` param. |
| AC3 | Role filter supports multi-select; selecting zero roles is treated as "no role filter". | **No** | — | **GAP.** Current UI is a single-select `<select>` (`roleFilter` is a `string`, not `string[]`). Spec says multi-select. Either downgrade the PRD AC or add multi-select + tests. Backend `role` param is single-valued today, so multi-select would need a backend change too. Flag to PM. |
| AC4 | Public/Private filter is tri-state: Public, Private, Both (default Both). | Yes | FE `CompaniesTab.test.tsx::test_public_private_toggle` | Segmented control with All/Public/Private buttons; default is `all` which omits the param. |
| AC5 | Clicking a sortable header sets `order_by` and toggles `direction` (asc↔desc); active sort is visually indicated with an arrow. | Yes (direction) / Partial (arrow) | FE `CompaniesTab.test.tsx::test_company_header_flips_direction`; BE `test_order_by_canonical_name_asc` + `test_order_by_mw_total_desc_regression` | The toggle behavior is covered. No test currently asserts the chevron/arrow icon renders for the active column. Low-risk gap. |
| AC6 | Pagination renders "Showing X–Y of TOTAL" where TOTAL is the filtered total returned by the API. | Yes | FE `CompaniesTab.test.tsx::test_pagination_math` | Asserts exact string "Showing 1–50 of 387" using `node.textContent`. |
| AC7 | Prev is disabled on page 1; Next is disabled when X + page_size > TOTAL. | **No** | — | **GAP.** No test verifies `disabled` state of Prev on page 1 or Next on the last page. The implementation does set `disabled={page === 1}` / `disabled={page >= totalPages}` in `PageTile`, so behavior is present but unverified. Recommend adding 2 short assertions. |
| AC8 | Changing any filter or sort resets to `page=1`. | Partial | FE `test_pagination_click_page_2` (indirectly: after click, page becomes 2; tests don't navigate to p2 then change filter) | **GAP.** No direct test: "navigate to page 2, change `q`, expect `page=1` in next URL". The `useEffect` that does `setPage(1)` on `[debouncedQ, roleFilter, ppFilter, sortField, sortDir]` exists at CompaniesTab.tsx:674. Recommend one explicit test. |
| AC9 | Min-MW input filters rows on the current page only and shows the helper text "v1: applies to current page". | **No** | — | **GAP.** Min MW filtering is implemented (`companies` memo at line 742) but there is no test asserting (a) rows below threshold are dropped, or (b) the helper text "v1: applies to current page" is rendered. Quick visual check of the rendered component (lines 977–1001) shows the input exists but **the helper text from the PRD is not present in the UI either** — neither the test nor the implementation covers this AC. Flag to PM / frontend dev. |
| AC10 | Header label reads "{filtered_total} companies tracked" and matches API `total`. | Partial | FE `test_pagination_math` (asserts total 387 rendered) | The badge text `"{total} companies tracked"` is rendered at CompaniesTab.tsx:822 using `total` from the response, which is the post-filter total per backend impl. No explicit test asserts the header re-renders when a filter changes the count. Low-risk; acceptable. |
| AC11 | No console errors; loading and empty states are handled (spinner on fetch, "No companies match these filters" when total=0). | Partial | — | The empty state literal "No companies match these filters." is wired at CompaniesTab.tsx:1015, and a `<Loader />` renders when `loading && !data`. **GAP:** no test asserts the empty-state copy when `total=0`, and no test asserts the spinner. Console-error assertions also absent (consider `vi.spyOn(console, 'error')` in beforeEach). |
| AC12 | Existing row click / drill-through behavior is preserved. | **No** | — | **GAP.** No test clicks a row and asserts `CompanyDetailPanel` opens (or that `selectedCompanyId` changes). This was the pre-existing behavior; worth one smoke test to prevent regression. |
| AC (extra) | `order_by` widened to include `name`/`canonical_name` and `ticker`; pagination slice correct. | Yes | BE `test_order_by_canonical_name_asc`, `test_order_by_mw_total_desc_regression`, `test_pagination_slice`, `test_validation_errors` | Backend regex `^(site_count|mw_total|canonical_name|ticker)$` verified. |
| AC (extra) | `q` is case-insensitive substring over name OR ticker. | Yes | BE `test_q_matches_name_case_insensitive`, `test_q_matches_ticker_case_insensitive` | ILIKE-based; cases covered. |
| AC (extra) | `public_private` filter works server-side. | Yes | BE `test_public_private_public_only` | |

### Gap summary (prioritized)

| Priority | AC | Gap |
|---|---|---|
| P0 (blocker for PRD-completeness) | AC3 | Role filter is single-select in code; PRD says multi-select. Either the PRD changes or the implementation does. |
| P0 | AC9 | "v1: applies to current page" helper text required by PRD is missing from the UI; no test for min-MW filtering behavior. |
| P1 | AC7 | Add tests for Prev disabled on page 1 / Next disabled on last page. |
| P1 | AC8 | Add explicit test: changing q after navigating to page 2 resets to page 1. |
| P2 | AC11 | Add empty-state copy assertion (`No companies match these filters.`) when API returns `total: 0`. Add spinner assertion. |
| P2 | AC12 | Add row-click drill-through smoke test. |
| P3 | AC5 | Add arrow-icon assertion for active sort column. |
| P3 | Hygiene | Migrate `regex=` to `pattern=` in `routers/companies.py` (Pydantic v2 deprecation, non-blocking). |

---

## 5. Failures encountered & resolutions

None. All commands returned green on first execution:
- 11/11 companies-scoped backend tests passed.
- 445/445 broader backend tests passed.
- 21/21 frontend tests passed (4 files).
- TypeScript: 4 errors total, all pre-existing in files outside this PR's scope (EarningsDetailModal.tsx, PowerTab.tsx, CounterpartyPieCard.tsx).

No code was modified during this QA pass.

---

## 6. Recommendation

**Ship the backend changes as-is.** The router is well-covered with 7 dedicated tests plus the broader 445-test regression net.

**For the frontend, flag two PRD-vs-implementation discrepancies to PM before merge:**
1. AC3 (multi-select roles) — current UI is single-select. Either PRD wording is adjusted or scope grows.
2. AC9 (min-MW helper text "v1: applies to current page") — the input is there, the filtering works, but the required helper-text affordance is missing from the rendered component.

The remaining gaps (AC7/AC8/AC11/AC12/AC5 arrow) are test-coverage gaps, not functional bugs — the underlying code paths exist. Recommend adding ~6 short tests in a follow-up before sign-off; they are not strictly blockers because the behavior is implemented.
