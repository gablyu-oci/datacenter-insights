# QA: Company Counterparty Pies — Test Plan

**Owner:** QA | **Date:** 2026-05-08
**Feature:** `GET /api/companies/{id}/counterparties` + `<CounterpartyPies>` UI
**Refs:** `docs/architecture/counterparties-pies-arch.md`,
`backend/routers/companies.py` (route at line ~234),
`backend/tests/test_companies_counterparties.py` (regression).

## Scope
Two donut charts inside `CompanyDetailPanel`: `as_provider` (focal sells/builds) and
`as_end_user` (focal buys/uses). Each pie supports a Sites / MW toggle and shows top-7
counterparties + grey **Other** slice. Out of scope: row-expand affordance, table sort
changes.

## Manual QA — 5 named companies
For each, click the company row in the Companies tab and verify the panel shows two pies.
Failure = wrong pie absent or numbers contradict `/role-summary` for the same company.

| Company | Expect on `as_provider` (selling) | Expect on `as_end_user` (buying) | Notes |
|---|---|---|---|
| **Crusoe** | Multiple end-users (40+ provider sites in seed). Top-7 + Other slice visible. | Likely empty — Crusoe is a builder. | Empty side renders an "(no counterparties)" stub, not an exception. |
| **Tract** | Several end-users; values consistent with /role-summary `provider.site_count`. | Likely empty. | Long names should truncate w/ tooltip. |
| **Meta** | Likely empty. | Multiple providers (Crusoe, etc). | Verify Meta does not appear in its own `as_end_user` list. |
| **AWS** | Likely empty. | Providers (and rolled-up parent Amazon should NOT leak as a counterparty — depth=1 self-exclusion). | Cross-check with Amazon view: same data. |
| **Microsoft** | Mixed if any provider rows exist; otherwise empty. | Multiple providers. | Toggle to MW; confirm reordering vs Sites view. |

**Acceptance fail signals:** focal company appears in its own list; numbers contradict
`/role-summary` shown in same panel; pie animates infinitely / never settles; legend rows
do not render in the documented 2-column flex layout.

## Browser smoke test (Crusoe)
1. Open Companies tab.
2. Click the Crusoe row -> `CompanyDetailPanel` opens.
3. Verify two pies render side-by-side (`as_provider` left, `as_end_user` right).
4. Click **MW** toggle on `as_provider`. Slices reorder; legend value pill switches from
   site count to MW. Top-7 membership may differ between Sites and MW (intentional).
5. Toggle back to **Sites**. Order returns to descending by site count.
6. If `other_sites > 0`, verify a grey **Other** slice appears last (custom legend, not
   Recharts default).

## Manual edge cases
- **Empty-state company**: pick any utility-only company. Both pies should render an empty
  state placeholder; `other_sites=0`, `other_mw=0`. No console errors.
- **Long counterparty names** (>30 chars): legend rows truncate with ellipsis; full name
  visible on hover via `title=`.
- **>7 counterparties**: confirm exactly 7 named slices + 1 grey **Other** slice.
- **NULL `mw_share`** rows: switch to MW view on a company whose counterparties have NULL
  `mw_share`. `coalesce(mw_share, power_capacity_mw)` should still produce non-zero MW; if
  both are NULL, that counterparty is silently dropped from the MW ranking but still
  counted under Sites.

## Backend curl checks
Run from a host that can reach the FastAPI backend (default `http://localhost:8000`):
```sh
for name in Crusoe Tract Meta AWS Microsoft; do
  ID=$(psql -At -c "select id from companies where canonical_name='$name'")
  echo "=== $name (id=$ID) ==="
  curl -s "http://localhost:8000/api/companies/$ID/counterparties" \
    | jq '.data | {as_provider_sites: .as_provider.sites|length,
                   as_provider_other: .as_provider.other_sites,
                   as_end_user_sites: .as_end_user.sites|length,
                   as_end_user_other: .as_end_user.other_sites}'
done
```
Expectation: HTTP 200, every `*_sites` length <= 7, `other_*` >= 0. Any 5xx is a fail.

## Accessibility
- Tab order: focus enters the panel, lands on `as_provider` Sites toggle, then MW toggle,
  then `as_end_user` Sites/MW. No focus traps.
- `aria-pressed="true"` on the active metric button; `aria-pressed="false"` on the inactive
  one.
- Each toggle has an `aria-label` of the form "Show as_provider counterparties by Sites".
- Screen reader (VoiceOver / NVDA) announces button state change on toggle.

## Regression coverage (automated)
`backend/tests/test_companies_counterparties.py` covers: documented response shape,
empty-state, 404 for unknown id, self-exclusion, and metric-descending order. Tests skip
cleanly when local Postgres is unreachable so CI without a DB is not blocked.
