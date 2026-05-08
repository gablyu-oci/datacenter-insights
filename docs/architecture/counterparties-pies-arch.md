# Architecture: Company Counterparty Pies

**Owner:** System Architect | **Status:** Final | **Date:** 2026-05-08
**Source PRD:** `docs/prds/counterparties-pies.md` | **Research:** `docs/research/counterparties-pies-research.md`

## System Overview
One new read-only endpoint `GET /api/companies/{id}/counterparties`, one self-join SQL, and two new React presentation components mounted inside the existing `CompanyDetailPanel`. Zero schema changes, zero new deps.

## Architecture Diagram
```
CompaniesTab (table, unchanged)
   └─ row click ─► CompanyDetailPanel (existing)
                      └─ <CounterpartyPies companyId/>      ◄── NEW
                            ├─ <CounterpartyPieCard side="as_provider"/>
                            └─ <CounterpartyPieCard side="as_end_user"/>
                                  └─ useApi("/api/companies/{id}/counterparties")
                                        │
                                  FastAPI router (companies.py)
                                        │
                                  _query_counterparties()  one self-join, 2 calls
                                        │
                                  Postgres: site_company_associations × sites
```

## Components & Responsibilities
| Layer | Component | Responsibility |
|---|---|---|
| API | `companies.router.company_counterparties` | Validate id, run two queries (provider→buyers, end_user→sellers), apply top-7+Other split, wrap in `CoverageEnvelope` |
| SQL | `_query_counterparties(db, company_id, x_roles, y_roles)` | Single async `select()` self-join returning `[(counterparty_id, n_sites, total_mw), ...]` ordered by `total_mw desc nullslast` |
| UI | `CounterpartyPies` | Lazy-fetch endpoint once, render two `CounterpartyPieCard` side-by-side |
| UI | `CounterpartyPieCard` | One donut + sites/MW toggle + custom HTML legend, 180px wide |

## SQL Queries (Final)

```python
# backend/routers/companies.py
async def _query_counterparties(
    db: AsyncSession,
    company_id: int,
    x_roles: list[str],   # roles the focal company plays  e.g. ["provider","developer"]
    y_roles: list[str],   # counterparty roles            e.g. ["end_user","customer"]
) -> list[tuple[int, int, float]]:
    sca_x = aliased(SiteCompanyAssociation)
    sca_y = aliased(SiteCompanyAssociation)
    mw_expr = func.coalesce(sca_y.mw_share, Site.power_capacity_mw)
    stmt = (
        select(
            sca_y.company_id.label("counterparty_id"),
            func.count(func.distinct(sca_x.site_id)).label("n_sites"),
            func.sum(mw_expr).label("total_mw"),
        )
        .join(sca_y, sca_y.site_id == sca_x.site_id)
        .join(Site, Site.id == sca_x.site_id)
        .where(sca_x.company_id.in_(company_ids),  # see rollup decision
               sca_x.role.in_(x_roles),
               sca_y.role.in_(y_roles),
               sca_y.company_id.notin_(company_ids))   # exclude self/children
        .group_by(sca_y.company_id)
        .order_by(literal_column("total_mw").desc().nullslast())
    )
    return [(r.counterparty_id, r.n_sites, float(r.total_mw or 0.0)) for r in (await db.execute(stmt)).all()]
```

**Child-company rollup: YES.** Both `/role-summary` and `/sites` resolve `[id] + children where parent_company_id == id` (depth=1) before querying. `/counterparties` MUST match — otherwise Amazon's pies would silently ignore AWS sites and contradict the role-summary numbers shown in the same panel.

## Response Shape
```json
{
  "data": {
    "company_id": 17,
    "as_provider": {
      "sites": [{"company_id": 2, "name": "Amazon", "n": 12}, ...],   // top-7, sorted desc by n_sites
      "mw":    [{"company_id": 2, "name": "Amazon", "v": 1840.0}, ...], // top-7, sorted desc by total_mw
      "other_sites": 4,
      "other_mw": 220.0,
      "total_counterparties": 11
    },
    "as_end_user": { ... same shape ... }
  },
  "lineage": { ...CoverageEnvelope... }
}
```
Both `sites` and `mw` arrays returned in one response so the toggle is purely client-side; top-7 membership may differ between metrics (intentional — research §Gotcha).

## Top-7 + Other Logic (Python, in router)
SQL returns the full ordered list; Python slices once per metric. Keeps SQL single-purpose and avoids duplicating the self-join for two orderings.
```python
def _split_top7(rows, key_fn):
    rows_sorted = sorted(rows, key=key_fn, reverse=True)
    top, rest = rows_sorted[:7], rows_sorted[7:]
    other_total = sum(key_fn(r) for r in rest)
    return top, other_total, len(rows_sorted)

# rows = await _query_counterparties(...)
top_sites, other_sites, total = _split_top7(rows, lambda r: r[1])   # n_sites
top_mw,    other_mw,    _     = _split_top7(rows, lambda r: r[2])   # total_mw
# then hydrate company names via one select(Company).where(Company.id.in_(ids_union))
```

## React State Structure
**Render location: inline at the bottom of the existing `CompanyDetailPanel`** (which already opens on row click). Rationale: zero table-row affordance churn, panel is the natural "drill-down" surface, lazy-mounts only when the user opted into details.

```tsx
// CounterpartyPieCard.tsx
const [metric, setMetric] = useState<"sites" | "mw">("sites");
// data prop is the side payload (provider OR end_user)
const slices = metric === "sites" ? data.sites : data.mw;
const otherVal = metric === "sites" ? data.other_sites : data.other_mw;
```
Two cards = two independent `metric` states. Data fetched once via `useApi("/api/companies/{id}/counterparties")` in `CounterpartyPies`, passed down as props. No global state, no second fetch.

## Component Split / File Layout
- `frontend/src/components/tabs/companies/CounterpartyPies.tsx` (NEW) — default export `<CounterpartyPies companyId>`. Calls `useApi`, handles loading/empty/error, renders two `<CounterpartyPieCard>`.
- `frontend/src/components/tabs/companies/CounterpartyPieCard.tsx` (NEW) — default export. Props: `{ side: "as_provider"|"as_end_user", title: string, data: SidePayload }`. Owns `metric` state, renders donut (`outerRadius=48`, `innerRadius=26`, `labelLine=false`, no `label` prop, `sortValues={false}`) + custom 2-col flex legend + grey "Other" `<Cell>`.
- `CompaniesTab.tsx` diff: ≤10 lines. One import + one JSX line inside `<CompanyDetailPanel>` body (or one render call alongside the panel).

## Tech Stack Decisions
- SQLAlchemy 2.0 async `select()` + `aliased()` self-join — matches existing router style.
- Recharts `<PieChart>` — already in bundle (used by `InsightChart.tsx`); reuse `pickColor(i)` for top-7, neutral grey `#6b7280` for Other.
- `useApi` hook — same envelope handling as every other tab; no SWR/React-Query introduction.

## ADRs

**ADR-1: Single self-join in SQL, top-7 split in Python.** Self-join is cheap with existing composite indexes (research §Q1); doing the top-7 split in Python lets one query feed both metric orderings without re-running SQL or duplicating logic.

**ADR-2: Roll up child companies (depth=1).** Mirrors `/role-summary` and `/sites`; inconsistent rollup across sibling endpoints would be a worse bug than the marginal cost of one extra `select(Company.id).where(parent_company_id==id)`.

**ADR-3: Full MW attribution via `coalesce(mw_share, power_capacity_mw)`, no even-split.** PRD US-3 says "split evenly" but research and existing `/role-summary` both use raw `power_capacity_mw` without splitting. Consistency with `/role-summary` wins; full attribution per role on a site is the documented platform convention. Flagged for PM sign-off but adopted as default.

**ADR-4: Render under `CompanyDetailPanel`, not as a row-expand affordance.** Avoids any change to table row chrome (sort/click semantics) and keeps the Companies table compact per PRD non-goal "no card-layout redesign."

**ADR-5: Custom HTML legend over Recharts `<Legend>`.** Deterministic 2-col flex layout at 180px, allows inline value pill, avoids wrapperStyle hacks (research §Q2).

## Edge Cases & Decisions
| Case | Decision |
|---|---|
| Self-edge (same company both sides of a site) | `sca_y.company_id NOT IN company_ids` excludes both self and rolled-up children |
| Child-company rollup | YES, depth=1, matches `/role-summary` and `/sites` |
| `mw_share` NULL | `coalesce(mw_share, sites.power_capacity_mw)`; `SUM` skips remaining NULLs |
| Both NULL | Row contributes 0 to `total_mw`, still counted in `n_sites`; legend footnote when `mw` view active |
| Empty result | `sites:[]`, `mw:[]`, `other_sites:0`, `other_mw:0`, `total_counterparties:0` |
| Order semantics | `sites` array desc by `n_sites`; `mw` array desc by `total_mw`; top-7 sets may differ |
| Recharts re-sort | `sortValues={false}` + push Other last |

## Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Self-join planner regression on larger row counts | Verify `EXPLAIN ANALYZE` against `(company_id, role)` and `(site_id, role)` composite indexes; add fixture-based regression test with > 1k associations |
| Two pies overflow at narrow viewport | Each pie in own `ResponsiveContainer`; parent flex with `minWidth: 0` (research §Gotcha) |
| Top-7 membership skew between metrics confuses analysts | Tooltip + legend value pill makes metric explicit; toggle label is high-contrast |
| Rollup divergence vs `/role-summary` | Same `company_ids = [id] + children` helper used in both endpoints; extract to private module fn in `companies.py` |
| Latency p95 > 300 ms | Two queries (provider, end_user) are independent — wrap in `asyncio.gather` if profiler shows sequential cost |
