# Counterparty Self-Join + Pie Sizing Research

## Question 1 — Counterparty self-join SQL pattern

Recommendation: **single self-join (option b)** in one async `select()`.
At ~15k rows on Postgres with composite indexes on `(company_id, role)` and
`(site_id, role)`, the planner uses the first index for the `sca_x` filter
(small driver set) and a nested-loop or hash join via `site_id` for `sca_y`.
The two-step IN-subquery pattern in `companies.py /sites` is fine for "give me
sites for company X", but for per-counterparty aggregation it forces a second
GROUP BY round-trip and an extra planner barrier. One self-join keeps the
aggregation in a single statement and lets Postgres push the role filter into
both index scans.

```python
# pseudocode, async session like /api/companies/{id}/sites
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
    .where(sca_x.company_id == X, sca_x.role.in_(R1))
    .where(sca_y.role.in_(R2), sca_y.company_id != X)
    .group_by(sca_y.company_id)
    .order_by(literal_column("total_mw").desc().nullslast())
)
```
Use `func.sum(mw_expr)` — Postgres `SUM` already skips NULLs, so no extra
filter is needed; `coalesce` handles per-row NULL fallback to site capacity.

## Question 2 — Recharts pie inside 180px card

Recommendation for ~180px container with toggle row (~28px) + legend (~36px),
leaving ~116px for the plotting area:
- `outerRadius={48}`, `innerRadius={26}` (donut). Donut reads cleaner at this
  size and frees the center for a small total label if needed later.
- `<ResponsiveContainer width="100%" height={116}>` inside the 180px card;
  put the Sites/MW toggle in a sibling div above, not inside `PieChart`.
- **Custom HTML legend, not Recharts `<Legend>`.** Built-in `<Legend>` eats
  vertical space unpredictably and wraps awkwardly at narrow widths
  (existing `InsightChart.tsx` pie branch shows the wrapperStyle approach,
  but it's tuned for 220px). A 2-column flex grid below the chart with
  fixed-height swatches gives deterministic layout and lets you append the
  count/MW value next to each name.
- Top-7 + "Other" rollup: bucket slices 8..N into one `Other` row before
  passing to `<Pie>`. Color "Other" with a neutral grey
  (e.g. `tokens.color.text.faint` or `#6b7280`) so it visually recedes; do
  **not** pull the next categorical color, which falsely implies a peer.
- **Drop on-slice labels.** At outerRadius 48, Recharts' label placement
  collides constantly. Keep `<Tooltip>` only and rely on the legend for
  names. Set `labelLine={false}` and omit the `label` prop entirely.
- Reuse `pickColor(i)` from `InsightChart.tsx` for the top-7 to stay on
  the OCI categorical palette; render `Other` last with `<Cell fill={grey}/>`.

## Gotchas
- `count(distinct site_id)` on the self-join can double-count if `sca_x` has
  multiple roles per site for X — the `distinct` guards this; verify with the
  same fixture used in `/sites` (a site with both `provider` and `end_user`).
- Recharts `<Pie>` re-sorts by value; pre-sort + push `Other` last, or set
  `sortValues={false}` to keep your bucket order.
- Two pies side-by-side in one card: wrap each in its own
  `ResponsiveContainer` — don't share a parent flex without `minWidth: 0` or
  the SVG will overflow on narrow viewports.
