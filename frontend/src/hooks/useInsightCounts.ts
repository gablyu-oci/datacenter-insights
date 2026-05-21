import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useInsightCounts — fetch `GET /api/insights/counts`.
 *
 * Contract (per 03-architecture.md + 04-ux.md §3/§4/§7):
 *   - `saved` is the per-user count of insight_subscription rows owned by
 *     the current X-Forwarded-Email identity.
 *   - `sessions` is the global count of completed ai_session rows (shared
 *     across the team; Past Runs is intentionally not per-user).
 *   - `autoload` defaults to TRUE so the collapsed section headers can
 *     render a real badge on first paint (no `(0)` flicker — see UX §3
 *     rows 1–3 and §12 decision #1).
 *   - On ANY error (5xx, non-OK like 401, or network), both counts are
 *     set to `null` so the consuming Collapsible hides the badge entirely
 *     (UX §4 row "Counts endpoint errored" + §7 graceful-degradation
 *     rule). We never fall back to `0` — `(0)` is reserved for a
 *     successful response of zero.
 *   - Same cancelledRef / loadingRef / hasFetchedOnceRef pattern as
 *     useSavedInsights to stay consistent with the rest of the codebase
 *     (no TanStack Query, no SWR, raw fetch only).
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export interface UseInsightCountsOptions {
  /** If true, fires the initial fetch on mount. Default true. */
  autoload?: boolean;
}

export interface UseInsightCountsResult {
  saved: number | null;
  sessions: number | null;
  loading: boolean;
  error: string | null;
  /** Idempotent — in-flight requests are de-duped via loadingRef. */
  refetch: () => void;
}

interface InsightCountsResponse {
  saved?: number | null;
  sessions?: number | null;
}

export function useInsightCounts(
  opts?: UseInsightCountsOptions,
): UseInsightCountsResult {
  const autoload = opts?.autoload !== false;

  const [saved, setSaved] = useState<number | null>(null);
  const [sessions, setSessions] = useState<number | null>(null);
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

    const url = `${API_BASE}/api/insights/counts`;

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
        // UX §4 / §7: on error, drop both badges. Never show stale or
        // half-rendered counts.
        setSaved(null);
        setSessions(null);
        return;
      }

      const body = (await res.json()) as InsightCountsResponse | null;
      if (cancelledRef.current) {
        return;
      }

      const nextSaved =
        typeof body?.saved === "number" && Number.isFinite(body.saved)
          ? body.saved
          : null;
      const nextSessions =
        typeof body?.sessions === "number" && Number.isFinite(body.sessions)
          ? body.sessions
          : null;

      setSaved(nextSaved);
      setSessions(nextSessions);
    } catch (e) {
      if (cancelledRef.current) {
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
      setSaved(null);
      setSessions(null);
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
    saved,
    sessions,
    loading,
    error,
    refetch,
  };
}
