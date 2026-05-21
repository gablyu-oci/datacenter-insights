# Companies Directory — Search & Pagination Notes

Date: 2026-05-13
Scope: React 19 + Vite + Vitest. No new deps (lodash, use-debounce, swr, react-query all out).

## Q1 — 250 ms Debounced Search Input

**Recommendation:** tiny custom `useDebouncedValue` hook built on `useEffect` + `setTimeout` cleanup. It is ~8 lines, reusable across the Companies tab and any future filter input, and avoids the "stale closure inside the timeout" footgun you get when inlining `setTimeout` in a handler.

```tsx
// hooks/useDebouncedValue.ts
import { useEffect, useState } from 'react';

export function useDebouncedValue<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);   // cancels prior timer on each keystroke
  }, [value, delayMs]);
  return debounced;
}

// usage
const [query, setQuery] = useState('');
const debouncedQuery = useDebouncedValue(query, 250);
useEffect(() => { fetchCompanies(debouncedQuery); }, [debouncedQuery]);
```

The cleanup function is the whole trick: React runs it before re-running the effect, so each keystroke clears the previous timer. Final keystroke is the only one that survives to fire.

Cleanup-as-cancellation is the same shape React docs use for `setInterval`/event listeners (see useEffect ref below).

## Q2 — Pagination Window (max 7 numbered tiles)

```ts
// utils/paginationWindow.ts
export type PageToken = number | 'ellipsis';

export function paginationWindow(
  current: number,
  totalPages: number,
  maxTiles = 7,
): PageToken[] {
  if (totalPages <= maxTiles) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  // Reserve 2 slots for first/last, up to 2 for ellipses -> 3 "inner" slots.
  const inner = maxTiles - 4;            // = 3 when maxTiles = 7
  const half = Math.floor(inner / 2);    // = 1

  const showLeftDots  = current > 2 + half + 1;          // current > 4
  const showRightDots = current < totalPages - half - 2; // current < 19 when total=22

  if (!showLeftDots && showRightDots) {
    // near the start: 1 2 3 4 5 … N
    const left = Array.from({ length: maxTiles - 2 }, (_, i) => i + 1);
    return [...left, 'ellipsis', totalPages];
  }
  if (showLeftDots && !showRightDots) {
    // near the end: 1 … N-4 N-3 N-2 N-1 N
    const right = Array.from(
      { length: maxTiles - 2 },
      (_, i) => totalPages - (maxTiles - 3) + i,
    );
    return [1, 'ellipsis', ...right];
  }
  // middle: 1 … c-1 c c+1 … N
  const mid: PageToken[] = [];
  for (let p = current - half; p <= current + half; p++) mid.push(p);
  return [1, 'ellipsis', ...mid, 'ellipsis', totalPages];
}
```

Worked examples (maxTiles = 7):

| input                  | output                                  |
|------------------------|-----------------------------------------|
| `(1, 22)`              | `[1, 2, 3, 4, 5, 'ellipsis', 22]`       |
| `(5, 22)`              | `[1, 2, 3, 4, 5, 'ellipsis', 22]`       |
| `(11, 22)`             | `[1, 'ellipsis', 10, 11, 12, 'ellipsis', 22]` |
| `(22, 22)`             | `[1, 'ellipsis', 18, 19, 20, 21, 22]`   |
| `(2, 3)`               | `[1, 2, 3]` (totalPages <= maxTiles)    |

Pure function, deterministic, trivial to unit-test in Vitest (`it.each` over the table above).

Render notes: when mapping, use a stable key — `'ellipsis'` can appear twice, so key on `idx` or compose `${token}-${idx}`.

## Q3 — Keep Previous Rows Visible While Fetching

**Recommendation:** plain `useState` for `data` + `fetching` + a tiny "request id" guard against out-of-order responses. Dim the table with inline opacity (mirrors React's own useDeferredValue example). No SWR, no react-query.

```tsx
const [data, setData] = useState<Row[]>([]);
const [fetching, setFetching] = useState(false);
const reqIdRef = useRef(0);

useEffect(() => {
  const myReq = ++reqIdRef.current;
  setFetching(true);
  fetchCompanies({ q: debouncedQuery, page })
    .then((rows) => {
      if (myReq !== reqIdRef.current) return; // stale response, drop
      setData(rows);                          // only replace on success
    })
    .finally(() => {
      if (myReq === reqIdRef.current) setFetching(false);
    });
}, [debouncedQuery, page]);

return (
  <div
    style={{
      opacity: fetching ? 0.5 : 1,
      transition: 'opacity 0.2s 0.2s linear',
      pointerEvents: fetching ? 'none' : 'auto',
    }}
    aria-busy={fetching}
  >
    <CompaniesTable rows={data} />
  </div>
);
```

Key points: (a) we never call `setData([])` on the new request, so the table height is stable and the user keeps seeing the prior page; (b) the `reqIdRef` guard makes rapid typing safe — only the latest response wins; (c) `aria-busy` keeps it accessible.

## React Docs References

- useEffect cleanup semantics: https://react.dev/reference/react/useEffect
- useState: https://react.dev/reference/react/useState
- useRef (request-id pattern): https://react.dev/reference/react/useRef
- useDeferredValue — opacity-dim example we mirror in Q3: https://react.dev/reference/react/useDeferredValue#indicating-that-the-content-is-stale

## Warnings / Gotchas

- Do NOT debounce the `setQuery` call itself — debounce the *derived* value. Keeping the input controlled (`value={query}`) is what makes typing feel instant.
- `setTimeout` cleanup must clear via the id captured in the same effect run; pulling the id from a ref breaks under StrictMode double-invoke.
- In Vitest, prefer `vi.useFakeTimers()` + `vi.advanceTimersByTime(250)` to test the debounce hook — avoids flake.
- Pagination function: guard `totalPages === 0` at the call site; the function assumes `totalPages >= 1`.
- The opacity-dim pattern intentionally still allows clicks unless you set `pointerEvents: 'none'`; do set it, otherwise a user can fire a second page-change before the first resolves and create yet more in-flight requests.
- React 19's `useActionState` / `useTransition` are tempting alternatives for Q3, but they pair more naturally with form actions; for a `fetch` driven by `useEffect` the explicit `fetching` boolean is clearer.
