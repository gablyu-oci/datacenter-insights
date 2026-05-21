import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useSessionHistory — lazy paginated fetch over
 * `GET /api/insights/sessions?limit=&offset=&status=`.
 *
 * Contract (per 03-architecture.md §6.1 + 00-PLAN.md §3 C1):
 *   - `autoload` defaults to false. The initial network call only fires
 *     when the consumer calls `refetch()` or `loadMore()`. This matches
 *     PastRunsSection's lazy-on-first-expand semantic.
 *   - `refetch()` resets offset to 0 and REPLACES `items`.
 *   - `loadMore()` bumps offset by `limit` and APPENDS the new page to
 *     `items`. No-op while `loading` or when `!hasMore`.
 *   - `cancelledRef` mirrors useLatestInsightSession: setters become
 *     no-ops after unmount or before a newer fetch resolves.
 *   - `error` is a string for any 5xx, non-OK, or network failure.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const DEFAULT_LIMIT = 20;
const DEFAULT_STATUS = "completed";

export interface SessionHistoryRow {
  id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  model: string | null;
  focus: string | null;
  insights_emitted: number;
  duration_ms: number | null;
  created_by: string | null;
}

export type SessionHistoryStatus =
  | "completed"
  | "all"
  | "cancelled"
  | "failed"
  | "complete";

export interface UseSessionHistoryOptions {
  /** Page size. Default 20. */
  limit?: number;
  /** Server-side status filter. Default "completed". */
  status?: SessionHistoryStatus;
  /** If true, fires the initial fetch on mount. Default false (lazy). */
  autoload?: boolean;
}

export interface UseSessionHistoryResult {
  items: SessionHistoryRow[];
  total: number;
  hasMore: boolean;
  loading: boolean;
  error: string | null;
  /** Idempotent — first call triggers initial fetch when autoload=false. */
  refetch: () => void;
  /** Fetches the next page and APPENDS to items. No-op while loading or when !hasMore. */
  loadMore: () => void;
}

interface SessionsPageResponse {
  items?: SessionHistoryRow[] | null;
  total?: number | null;
  limit?: number | null;
  offset?: number | null;
  has_more?: boolean | null;
}

export function useSessionHistory(
  opts?: UseSessionHistoryOptions,
): UseSessionHistoryResult {
  const limit = opts?.limit ?? DEFAULT_LIMIT;
  const status = opts?.status ?? DEFAULT_STATUS;
  const autoload = opts?.autoload === true;

  const [items, setItems] = useState<SessionHistoryRow[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef<boolean>(false);
  const hasFetchedOnceRef = useRef<boolean>(false);
  const loadingRef = useRef<boolean>(false);
  const offsetRef = useRef<number>(0);

  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const runFetch = useCallback(
    async (offset: number, mode: "replace" | "append"): Promise<void> => {
      if (loadingRef.current) {
        return;
      }
      loadingRef.current = true;
      hasFetchedOnceRef.current = true;

      if (!cancelledRef.current) {
        setLoading(true);
        setError(null);
      }

      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      params.set("status", status);
      const url = `${API_BASE}/api/insights/sessions?${params.toString()}`;

      try {
        const res = await fetch(url, {
          method: "GET",
          headers: { Accept: "application/json" },
        });

        if (cancelledRef.current) {
          return;
        }

        if (!res.ok) {
          setError(
            res.status >= 500
              ? `server error ${res.status}`
              : `request failed: ${res.status}`,
          );
          return;
        }

        const body = (await res.json()) as SessionsPageResponse | null;
        if (cancelledRef.current) {
          return;
        }

        const nextItems = Array.isArray(body?.items)
          ? (body!.items as SessionHistoryRow[])
          : [];
        const nextTotal =
          typeof body?.total === "number" && Number.isFinite(body.total)
            ? body.total
            : 0;
        const nextHasMore =
          typeof body?.has_more === "boolean"
            ? body.has_more
            : offset + nextItems.length < nextTotal;

        setItems((prev) =>
          mode === "append" ? [...prev, ...nextItems] : nextItems,
        );
        setTotal(nextTotal);
        setHasMore(nextHasMore);
        offsetRef.current = offset + nextItems.length;
      } catch (e) {
        if (cancelledRef.current) {
          return;
        }
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        loadingRef.current = false;
        if (!cancelledRef.current) {
          setLoading(false);
        }
      }
    },
    [limit, status],
  );

  const refetch = useCallback((): void => {
    offsetRef.current = 0;
    void runFetch(0, "replace");
  }, [runFetch]);

  const loadMore = useCallback((): void => {
    if (loadingRef.current) {
      return;
    }
    if (hasFetchedOnceRef.current && !hasMore) {
      return;
    }
    const nextOffset = hasFetchedOnceRef.current ? offsetRef.current : 0;
    void runFetch(nextOffset, hasFetchedOnceRef.current ? "append" : "replace");
  }, [hasMore, runFetch]);

  useEffect(() => {
    if (!autoload) {
      return;
    }
    if (hasFetchedOnceRef.current) {
      return;
    }
    offsetRef.current = 0;
    void runFetch(0, "replace");
    // We deliberately depend only on autoload + runFetch identity. runFetch
    // changes when limit/status change; that's the desired re-trigger.
  }, [autoload, runFetch]);

  return {
    items,
    total,
    hasMore,
    loading,
    error,
    refetch,
    loadMore,
  };
}
