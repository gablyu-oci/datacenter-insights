import { useCallback, useEffect, useRef, useState } from "react";
import type { OpenQuestion } from "../components/tabs/ai-insights/types";

/**
 * useOpenQuestionsPolling — owns the network lifecycle for the
 * Tracked Questions sidebar (AI Insights v2 Phase D).
 *
 * Behavior (per docs/ai_insights_v2_sidebar_design.md §10):
 *   - Mounts: fire one fetch immediately. `isLoading=true` only on the first.
 *   - Sets a 30,000 ms `setInterval`; each tick triggers a refetch IFF
 *     `document.visibilityState === "visible"`.
 *   - On `visibilitychange` -> visible: fire one fetch immediately and
 *     resume the interval. On hidden: clear the interval (silent pause).
 *   - AbortController cancels any in-flight request when a new one starts
 *     OR when the component unmounts.
 *   - Keeps prior `data` in place during a refetch (no flicker). A failed
 *     refetch sets `error` but does NOT clear `data` — the UI shows a
 *     banner above the stale list.
 */

const DEFAULT_INTERVAL_MS = 30_000;
const DEFAULT_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export interface UseOpenQuestionsPollingOptions {
  /** Override poll interval (ms). Default 30_000. */
  intervalMs?: number;
  /** Override base URL (defaults to import.meta.env.VITE_API_BASE_URL). */
  baseUrl?: string;
  /** Disable polling entirely (still allows manual refetch). */
  enabled?: boolean;
}

export interface UseOpenQuestionsPollingResult {
  data: OpenQuestion[] | null;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  refetch: () => void;
  lastFetchedAt: Date | null;
}

export function useOpenQuestionsPolling(
  opts?: UseOpenQuestionsPollingOptions,
): UseOpenQuestionsPollingResult {
  const intervalMs = opts?.intervalMs ?? DEFAULT_INTERVAL_MS;
  const baseUrl = opts?.baseUrl ?? DEFAULT_BASE_URL;
  const enabled = opts?.enabled ?? true;

  const [data, setData] = useState<OpenQuestion[] | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isFetching, setIsFetching] = useState<boolean>(false);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const firstLoadRef = useRef<boolean>(true);
  const unmountedRef = useRef<boolean>(false);

  const doFetch = useCallback(async () => {
    // Cancel any in-flight request before issuing a new one.
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setIsFetching(true);
    try {
      const res = await fetch(`${baseUrl}/api/insights/open-questions`, {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: ctrl.signal,
      });
      if (!res.ok) {
        throw new Error(`request failed: ${res.status}`);
      }
      const body = (await res.json()) as OpenQuestion[];
      if (unmountedRef.current || ctrl.signal.aborted) return;
      setData(Array.isArray(body) ? body : []);
      setError(null);
      setLastFetchedAt(new Date());
    } catch (e) {
      if (ctrl.signal.aborted) return;
      if (unmountedRef.current) return;
      setError(e instanceof Error ? e : new Error(String(e)));
      // Intentionally do NOT clear `data` on error — keep the stale list
      // visible per design spec §4.4 / §7.5.
    } finally {
      if (!unmountedRef.current && !ctrl.signal.aborted) {
        setIsFetching(false);
        if (firstLoadRef.current) {
          firstLoadRef.current = false;
          setIsLoading(false);
        }
      }
    }
  }, [baseUrl]);

  const startInterval = useCallback(() => {
    if (timerRef.current !== null) return;
    if (!enabled) return;
    timerRef.current = setInterval(() => {
      // Defensive: only fetch when visible.
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        return;
      }
      void doFetch();
    }, intervalMs);
  }, [doFetch, intervalMs, enabled]);

  const stopInterval = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const refetch = useCallback(() => {
    // Manual refetch resets the interval to "now + intervalMs".
    stopInterval();
    void doFetch();
    startInterval();
  }, [doFetch, startInterval, stopInterval]);

  // Initial mount: fire one fetch and start the interval.
  useEffect(() => {
    unmountedRef.current = false;
    void doFetch();
    if (enabled) startInterval();

    return () => {
      unmountedRef.current = true;
      stopInterval();
      if (abortRef.current) abortRef.current.abort();
    };
    // doFetch / startInterval / stopInterval are stable per useCallback
    // dependencies; we deliberately re-run when those change so test
    // overrides (intervalMs, baseUrl) take effect.
  }, [doFetch, startInterval, stopInterval, enabled]);

  // Visibility-aware polling: pause on hidden, resume + refetch on visible.
  useEffect(() => {
    if (typeof document === "undefined") return;
    function onVisibility() {
      if (document.visibilityState !== "visible") {
        stopInterval();
      } else {
        if (enabled) {
          void doFetch();
          startInterval();
        }
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [doFetch, startInterval, stopInterval, enabled]);

  return {
    data,
    isLoading,
    isFetching,
    error,
    refetch,
    lastFetchedAt,
  };
}
