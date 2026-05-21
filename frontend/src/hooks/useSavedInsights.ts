import { useCallback, useEffect, useRef, useState } from "react";

import type { LatestInsight } from "./useLatestInsightSession";

/**
 * useSavedInsights — lazy fetch over `GET /api/insights/saved`.
 *
 * Contract (per 03-architecture.md §6.2 + 00-PLAN.md §3 C2):
 *   - `autoload` defaults to false. Initial fetch fires only when the
 *     consumer calls `refetch()` (matches SavedInsightsSection's
 *     lazy-on-first-expand semantic).
 *   - No pagination — the server caps at 100 items.
 *   - Same cancelledRef pattern as useLatestInsightSession.
 *   - `error` is a string for 5xx, non-OK, or network failures.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export interface SavedInsightRow extends LatestInsight {
  /** Always true from the server, but typed as boolean for flexibility. */
  is_saved: boolean;
  /** ISO timestamp the subscription row was created. */
  saved_at: string;
  // session_id is already on LatestInsight; nothing to add for it here.
}

export interface UseSavedInsightsOptions {
  /** If true, fires the initial fetch on mount. Default false (lazy). */
  autoload?: boolean;
}

export interface UseSavedInsightsResult {
  items: SavedInsightRow[];
  total: number;
  loading: boolean;
  error: string | null;
  /** Idempotent — first call triggers initial fetch when autoload=false. */
  refetch: () => void;
}

interface SavedInsightsResponse {
  items?: SavedInsightRow[] | null;
  total?: number | null;
}

export function useSavedInsights(
  opts?: UseSavedInsightsOptions,
): UseSavedInsightsResult {
  const autoload = opts?.autoload === true;

  const [items, setItems] = useState<SavedInsightRow[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const cancelledRef = useRef<boolean>(false);
  const loadingRef = useRef<boolean>(false);
  const hasFetchedOnceRef = useRef<boolean>(false);

  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const runFetch = useCallback(async (): Promise<void> => {
    if (loadingRef.current) {
      return;
    }
    loadingRef.current = true;
    hasFetchedOnceRef.current = true;

    if (!cancelledRef.current) {
      setLoading(true);
      setError(null);
    }

    const url = `${API_BASE}/api/insights/saved`;

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

      const body = (await res.json()) as SavedInsightsResponse | null;
      if (cancelledRef.current) {
        return;
      }

      const nextItems = Array.isArray(body?.items)
        ? (body!.items as SavedInsightRow[])
        : [];
      const nextTotal =
        typeof body?.total === "number" && Number.isFinite(body.total)
          ? body.total
          : nextItems.length;

      setItems(nextItems);
      setTotal(nextTotal);
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
  }, []);

  const refetch = useCallback((): void => {
    void runFetch();
  }, [runFetch]);

  useEffect(() => {
    if (!autoload) {
      return;
    }
    if (hasFetchedOnceRef.current) {
      return;
    }
    void runFetch();
  }, [autoload, runFetch]);

  return {
    items,
    total,
    loading,
    error,
    refetch,
  };
}
