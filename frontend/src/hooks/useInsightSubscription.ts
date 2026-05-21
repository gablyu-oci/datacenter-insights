import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useInsightSubscription — hook backing the Save / Saved toggle on an
 * InsightCard.
 *
 * Contract (per 03-architecture.md §6.3 + 04-ux-design.md §5.3 / §7):
 *   - `saved` mirrors `initialSaved` on first render. The hook re-syncs to
 *     `initialSaved` ONLY when `insightId` changes, so a re-render with a
 *     stale prop does not clobber an in-flight optimistic toggle.
 *   - `toggle()` flips state optimistically, then POSTs (save) or DELETEs
 *     (unsave) against the subscribe endpoint. On any non-2xx OR network
 *     failure it reverts the optimistic flip and surfaces an inline error
 *     string using the exact microcopy from 04-ux-design.md §7.
 *   - A `pendingRef` guards rapid double-clicks — concurrent toggles are
 *     dropped (early-return) rather than queued.
 *   - `cancelledRef` ensures state setters become no-ops after unmount.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const ERROR_SAVE = "Couldn't save — try again.";
const ERROR_UNSAVE = "Couldn't update — try again.";

export interface UseInsightSubscriptionResult {
  saved: boolean;
  pending: boolean;
  error: string | null;
  toggle: () => Promise<void>;
}

export function useInsightSubscription(
  insightId: string,
  initialSaved: boolean,
): UseInsightSubscriptionResult {
  const [saved, setSaved] = useState<boolean>(initialSaved);
  const [pending, setPending] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const pendingRef = useRef<boolean>(false);
  const cancelledRef = useRef<boolean>(false);

  // Resync ONLY when the insightId changes. Re-renders with the same
  // insightId but a different initialSaved (e.g. parent refetch races
  // an in-flight toggle) intentionally do NOT reset `saved`.
  useEffect(() => {
    setSaved(initialSaved);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [insightId]);

  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const toggle = useCallback(async (): Promise<void> => {
    if (pendingRef.current) {
      return;
    }
    pendingRef.current = true;

    // Capture previous before mutating, so revert is exact.
    const previous = saved;
    const next = !previous;
    const failureMessage = next ? ERROR_SAVE : ERROR_UNSAVE;

    if (!cancelledRef.current) {
      setSaved(next);
      setPending(true);
      setError(null);
    }

    const url = `${API_BASE}/api/insights/insights/${encodeURIComponent(
      insightId,
    )}/subscribe`;

    try {
      const res = await fetch(url, {
        method: next ? "POST" : "DELETE",
        headers: { Accept: "application/json" },
      });

      if (cancelledRef.current) {
        return;
      }

      if (!res.ok) {
        setSaved(previous);
        setError(failureMessage);
        return;
      }

      // Success: leave saved=next, clear any prior error.
      setError(null);
    } catch {
      if (cancelledRef.current) {
        return;
      }
      setSaved(previous);
      setError(failureMessage);
    } finally {
      if (!cancelledRef.current) {
        setPending(false);
      }
      pendingRef.current = false;
    }
  }, [insightId, saved]);

  return { saved, pending, error, toggle };
}
