# Company Directory — Search / Filter / Pagination Architecture

Scope: backend `list_companies` (backend/routers/companies.py:83) and frontend
`CompaniesTab` (frontend/src/components/tabs/CompaniesTab.tsx:601). Return
envelope is `CoverageEnvelope` — unchanged.

---

## 1. Component Diagram

```
+---------+    React state    +-------------+   useApi    +--------------------+
| Browser | ----------------> | CompaniesTab| ----------> | GET /api/companies/|
+---------+                   +-------------+             +--------------------+
                                                                  |
                                                                  v
                                                          +----------------+
                                                          | list_companies |
                                                          | (FastAPI)      |
                                                          +----------------+
                                                                  |
                                                          aggregated SELECT
                                                                  |
                                                                  v
                                                          +----------------+
                                                          |   Postgres     |
                                                          |  companies +   |
                                                          |  associations  |
                                                          |  + sites       |
                                                          +----------------+
```

`useApi` is the existing hook — handles loading / error / retry. The list URL
is rebuilt on every state change; stale rows stay rendered while the new
request is in flight (see §7).

---

## 2. Backend Data Flow

`list_companies` already takes the aggregated branch unconditionally because
`order_by` has a default value of `site_count` (see §below on dead branch).
The three new query params layer onto the existing pipeline as additional
`WHERE` predicates that must be applied to BOTH the paginated `base` query and
to `count_base`.

New params:

| param            | type                          | notes                                  |
|------------------|-------------------------------|----------------------------------------|
| `q`              | `Optional[str]`               | substring match, ILIKE `%q%`           |
| `public_private` | `Optional[Literal['public','private']]` | maps to `Company.public_private` |
| `direction`      | `Literal['asc','desc']` = `desc` |                                        |
| `order_by`       | regex `^(site_count\|mw_total\|canonical_name\|ticker)$` | widened |

Important: the `%` wildcards are wrapped in **Python** before binding (e.g.
`f"%{q}%"`), not embedded in the SQL literal — this is how the existing
`/filings` endpoint already does it (companies.py:630) and keeps parameter
binding safe.

### SQL shape (illustrative)

```python
# base — paginated aggregated query
if q:
    pattern = f"%{q}%"
    base = base.where(or_(Company.canonical_name.ilike(pattern),
                          Company.ticker.ilike(pattern)))
    count_base = count_base.where(or_(Company.canonical_name.ilike(pattern),
                                      Company.ticker.ilike(pattern)))

if public_private:
    base = base.where(Company.public_private == public_private)
    count_base = count_base.where(Company.public_private == public_private)

# direction + widened order_by — applied after group_by
col = {"site_count": literal_column("site_count"),
       "mw_total":   literal_column("mw_total"),
       "canonical_name": Company.canonical_name,
       "ticker":     Company.ticker}[order_by]
base = base.order_by(col.desc() if direction == "desc" else col.asc(),
                     Company.id)
```

Both predicates are mirrored on `count_base` so `total` reflects the filtered
universe; without that mirror, pagination math breaks.

### Dead simple-paginated branch

Lines 167+ are unreachable because `order_by` defaults to `"site_count"`,
making `if role or top or order_by:` always truthy. Verified — leave as-is
per spec. A future cleanup can delete it, but not in this slice.

---

## 3. Frontend State Model

All atoms live in `CompaniesTab()`. Existing `sortField` is widened from the
current 3-value union to include `"ticker"`. `sortAsc` is replaced by an
explicit `sortDir`.

```ts
const [q,          setQ]          = useState<string>("");
const [roleFilter, setRoleFilter] = useState<string>("");        // "" = any
const [ppFilter,   setPpFilter]   = useState<"" | "public" | "private">("");
const [minMW,      setMinMW]      = useState<number | "">("");   // client-only
const [sortField,  setSortField]  = useState<
  "site_count" | "mw_total" | "canonical_name" | "ticker"
>("site_count");
const [sortDir,    setSortDir]    = useState<"asc" | "desc">("desc");
const [page,       setPage]       = useState<number>(1);

const pageSize = 50; // const, not state
```

`page` resets to `1` whenever any of `q`, `roleFilter`, `ppFilter`,
`sortField`, `sortDir` change — wired in the same `useEffect` that builds
the fetch URL, before the fetch fires.

---

## 4. Debounce Strategy

Only `q` is debounced. 250 ms via `useEffect` + `setTimeout`:

```ts
const [qDebounced, setQDebounced] = useState(q);
useEffect(() => {
  const t = setTimeout(() => setQDebounced(q), 250);
  return () => clearTimeout(t);
}, [q]);
```

`roleFilter`, `ppFilter`, `sortField`, `sortDir`, `page` fire immediately —
they are discrete-choice controls where debounce would feel laggy. `minMW`
is client-side filtering only (see §5) and does not trigger a fetch.

---

## 5. Fetch URL Builder

Pure function. Skips empty string / null params. `order_by`, `direction`,
`page`, `page_size` are always present.

```ts
function buildUrl(s: {
  q: string; roleFilter: string; ppFilter: string;
  sortField: string; sortDir: string; page: number;
}): string {
  const p = new URLSearchParams();
  p.set("order_by", s.sortField);
  p.set("direction", s.sortDir);
  p.set("page", String(s.page));
  p.set("page_size", "50");
  if (s.q)          p.set("q", s.q);
  if (s.roleFilter) p.set("role", s.roleFilter);
  if (s.ppFilter)   p.set("public_private", s.ppFilter);
  return `/api/companies/?${p.toString()}`;
}
```

`minMW` is applied client-side on the rendered page only — it is a quick
visual filter, not a server-side predicate, so it does NOT enter the URL.

---

## 6. Pagination Math

```
totalPages = Math.max(1, Math.ceil(total / pageSize))
showingFrom = total === 0 ? 0 : (page - 1) * pageSize + 1
showingTo   = Math.min(page * pageSize, total)
label       = `Showing ${showingFrom}-${showingTo} of ${total}`
```

Window function returns at most 7 tiles. Algorithm: always include 1 and
`totalPages`; include `page-1`, `page`, `page+1`; insert `"..."` sentinels
when there is a gap > 1. Examples (totalPages=20):

```
page=1   -> [1,2,3, "...", 20]
page=10  -> [1, "...", 9,10,11, "...", 20]
page=20  -> [1, "...", 18,19,20]
```

Tile click sets `page`; Prev/Next clamp at `[1, totalPages]`.

---

## 7. Non-Functional

- Idempotency: every request is a pure GET keyed by URL — safe to retry,
  cache, and replay. No mutation surface added.
- No new dependencies: no debounce library, no react-query, no router.
  `useState` + `useEffect` + the existing `useApi` hook only.
- No new design tokens — reuse existing `CARD_STYLE`, color palette,
  spacing from this file.
- Icons: reuse lucide-react (`Search`, `ChevronUp/Down`, `ChevronLeft/Right`)
  already imported elsewhere in the bundle.
- Stale-while-refetch: `useApi` keeps the last successful `data` visible
  during the next fetch; only `loading` flips. Apply a subtle opacity on
  the table while `loading && data` to telegraph the refetch without
  destroying scroll position.
- Server cost: each request is one aggregated query + one count + one
  roles hydration — same shape as today, just with extra WHERE clauses.
  The new predicates hit indexed columns (`canonical_name`, `ticker`,
  `public_private`); no new index required for prototype scale (~hundreds
  of rows).

---

## 8. Edge Cases & Error Contract

- **422 from FastAPI**: `direction` or `order_by` outside the allowed
  literals raises FastAPI's standard validation error. `useApi` surfaces
  it via `errorInfo` and the existing `ErrorPanel` renders with a Retry
  button — no new error UI.
- **Empty result, filters active**: `total = 0`, `data = []`. The table
  renders a single "No companies match the current filters. Clear filters
  to see all." row, with a button that resets `q`, `roleFilter`,
  `ppFilter`, `minMW` to defaults.
- **`total = 0`, no filters**: the existing empty-state card (line ~629)
  continues to render — "No company data available yet."
- **`page` past `totalPages`** (e.g. user filters down): on receiving a
  response whose `total` would place `page > totalPages`, snap `page` to
  `totalPages` and let the next render refetch. Prevents an infinite empty
  state.
- **`q` whitespace-only**: trim before debouncing; treat as empty.
- **Race conditions**: `useApi` keys on URL; a stale in-flight response
  whose URL no longer matches the latest state is dropped. No new
  coordination needed.
