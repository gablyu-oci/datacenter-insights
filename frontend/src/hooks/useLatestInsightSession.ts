import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useLatestInsightSession — hook that fetches `GET /api/insights/latest`
 * on mount and exposes the snapshot to the AI Insights tab.
 *
 * Contract (per architecture §6 / 03-architecture.md):
 *   - 200 with a session: returns `{ session, insights, ... }`.
 *   - 200 with `{ session: null }` (cold start): returns it as-is so the tab
 *     can render the empty-state path.
 *   - 404: same as cold start — exposes `data = { session: null, insights: [], ... }`
 *     and does NOT raise. (The backend may serve either; both are valid.)
 *   - 5xx / network: sets `error` and leaves `data === null`.
 *
 * `refetch()` is exposed so the tab can refresh the snapshot once a manual
 * "Run again" finishes or after the backend grows the include_failed=true
 * variant.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export interface LatestSessionRow {
  id: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  model: string | null;
  focus: string | null;
  max_insights: number | null;
  insights_emitted: number | null;
  duration_ms: number | null;
  budget_status: string | null;
  /** "scheduler" | "manual" | null  */
  created_by: string | null;
  cron_run_date: string | null;
}

export interface LatestCitation {
  id: string;
  url: string;
  title?: string | null;
  snippet?: string | null;
  search_query?: string | null;
  provider?: string | null;
  agree_or_disagree?: string | null;
}

export interface LatestInsight {
  id: string;
  session_id: string;
  idx: number;
  headline: string;
  body?: string | null;
  confidence: string;
  materiality: string;
  skills_run: string[];
  low_external_support?: boolean | null;
  created_at?: string | null;
  chart?: Record<string, unknown> | null;
  citations?: LatestCitation[] | null;
  /**
   * Phase A: backend includes a per-insight `is_saved` boolean. Missing /
   * undefined is treated as false on the consumer side.
   */
  is_saved?: boolean;
}

export interface LatestSessionResponse {
  session: LatestSessionRow | null;
  insights: LatestInsight[];
  is_today?: boolean;
  generated_at?: string | null;
  source?: "scheduler" | "manual" | null;
}

/**
 * Extended response shape returned when the caller passes
 * `includeFailed=true`. The backend then surfaces the most recent
 * session of any status as `session`, plus an optional
 * `last_successful` block holding the most recent fully complete
 * session and its insights (used to render the failed-banner +
 * yesterday-snapshot path described in
 * docs/plans/ai-insights-automation/09-arch-phase4-followups.md §3).
 */
export interface LatestSessionResponseFull extends LatestSessionResponse {
  last_successful?: {
    session: LatestSessionRow;
    insights: LatestInsight[];
  } | null;
}

export interface UseLatestResult {
  loading: boolean;
  error: string | null;
  data: LatestSessionResponseFull | null;
  refetch: () => void;
}

export interface UseLatestInsightSessionOptions {
  /**
   * When true, append `?include_failed=true` to the request URL so the
   * backend returns the most recent session of any status (plus a
   * `last_successful` block when the chosen row is failed). Defaults to
   * false to preserve every existing call-site.
   */
  includeFailed?: boolean;
}

const COLD_START: LatestSessionResponseFull = {
  session: null,
  insights: [],
  is_today: false,
  generated_at: null,
  source: null,
};

type FetchState =
  | { loading: true; error: null; data: null }
  | { loading: false; error: string; data: null }
  | { loading: false; error: null; data: LatestSessionResponseFull };

const INITIAL: FetchState = { loading: true, error: null, data: null };

export function useLatestInsightSession(
  options?: UseLatestInsightSessionOptions,
): UseLatestResult {
  const includeFailed = options?.includeFailed === true;
  const [state, setState] = useState<FetchState>(INITIAL);
  const [tick, setTick] = useState<number>(0);
  const cancelledRef = useRef<boolean>(false);

  const refetch = useCallback(() => {
    // Bump the tick AND mark loading via the same setState — the actual
    // fetch happens inside the effect's async IIFE.
    setState(INITIAL);
    setTick((n) => n + 1);
  }, []);

  useEffect(() => {
    cancelledRef.current = false;

    (async () => {
      try {
        const url = `${API_BASE}/api/insights/latest${
          includeFailed ? "?include_failed=true" : ""
        }`;
        const res = await fetch(url, {
          method: "GET",
          headers: { Accept: "application/json" },
        });
        if (cancelledRef.current) return;

        if (res.status === 404) {
          setState({ loading: false, error: null, data: COLD_START });
          return;
        }

        if (res.status >= 500) {
          setState({
            loading: false,
            error: `server error ${res.status}`,
            data: null,
          });
          return;
        }

        if (!res.ok) {
          // 4xx other than 404 — surface as error so the tab can render
          // the inline error per UX spec §1.2 step 5.
          setState({
            loading: false,
            error: `request failed: ${res.status}`,
            data: null,
          });
          return;
        }

        const body = (await res.json()) as Partial<LatestSessionResponseFull> | null;
        if (cancelledRef.current) return;

        // Normalise: backend may omit fields entirely on cold-start 200.
        // `last_successful` is preserved verbatim when the include_failed=true
        // branch returns it (see plans/ai-insights-automation/09 §2).
        const normalised: LatestSessionResponseFull = {
          session: body?.session ?? null,
          insights: Array.isArray(body?.insights) ? (body!.insights as LatestInsight[]) : [],
          is_today: body?.is_today ?? false,
          generated_at: body?.generated_at ?? null,
          source: (body?.source as LatestSessionResponse["source"]) ?? null,
          ...(body && "last_successful" in body
            ? { last_successful: body.last_successful ?? null }
            : {}),
        };
        setState({ loading: false, error: null, data: normalised });
      } catch (e) {
        if (cancelledRef.current) return;
        setState({
          loading: false,
          error: e instanceof Error ? e.message : String(e),
          data: null,
        });
      }
    })();

    return () => {
      cancelledRef.current = true;
    };
  }, [tick, includeFailed]);

  return {
    loading: state.loading,
    error: state.error,
    data: state.data,
    refetch,
  };
}
