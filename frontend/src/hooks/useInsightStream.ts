import { useCallback, useEffect, useRef, useState } from "react";
import type {
  InsightSSEEvent,
  SSEEventName,
  StreamStatus,
} from "../types/sseEvents";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const RECONNECT_BACKOFF_MS = [1000, 2000, 5000];

/**
 * Known SSE event names the frontend dispatches. Any incoming `event:` line
 * outside this set is dropped (with a console warning) so we don't leak
 * unknown shapes into reducers.
 */
const KNOWN_EVENTS = new Set<SSEEventName>([
  "session_started",
  "surveying",
  "insight_started",
  "token",
  "reasoning_step",
  "tool_call",
  "tool_result",
  "chart",
  "citation",
  "insight_complete",
  "session_complete",
  "error",
  "ping",
  "web_search_unavailable",
]);

export interface UseInsightStreamResult {
  /** Append-only event log, in arrival order, ready for replay/reducer. */
  events: InsightSSEEvent[];
  /** Stream lifecycle. */
  status: StreamStatus;
  /** True while we're actively reconnecting after a disconnect. */
  reconnecting: boolean;
  /** Most recent terminal error (if any). */
  error: { code: string; message: string } | null;
  /** Last-Event-ID we've successfully processed. */
  lastEventId: string | null;
  /**
   * Open a new session. `prompt` is forwarded as the optional `focus` field
   * on the session payload. No-op if a stream is already open.
   */
  start: (prompt?: string) => void;
  /** Close the current stream (does not POST cancel server-side). */
  stop: () => void;
  /** Drop all events + reset to idle. */
  reset: () => void;
  /** Replay the event log (e.g. for a fresh reducer). */
  replay: () => InsightSSEEvent[];
}

interface InternalESHandle {
  es: EventSource;
  /** Bound listener fns so we can detach on cleanup. */
  listeners: Array<{ name: string; fn: (e: MessageEvent) => void }>;
}

/**
 * useInsightStream — wraps EventSource for the AI Insights SSE endpoint.
 *
 *  - Parses each `event:` frame into a typed `InsightSSEEvent`.
 *  - Tracks the last seen `event_id` and resumes via `Last-Event-ID` query
 *    parameter on reconnect (browsers add the header automatically only when
 *    EventSource itself reconnects; we hand-roll reconnects with explicit
 *    backoff so we pass the id as a URL param to be unambiguous).
 *  - Backoff: 1s -> 2s -> 5s on disconnect, then sticks at 5s.
 */
export function useInsightStream(sessionId: string | null): UseInsightStreamResult {
  const [events, setEvents] = useState<InsightSSEEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [lastEventId, setLastEventId] = useState<string | null>(null);

  const lastEventIdRef = useRef<string | null>(null);
  const handleRef = useRef<InternalESHandle | null>(null);
  const promptRef = useRef<string | undefined>(undefined);
  const attemptRef = useRef(0);
  const backoffTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);
  const attachRef = useRef<((sid: string) => void) | null>(null);

  const detach = useCallback(() => {
    if (handleRef.current) {
      const { es, listeners } = handleRef.current;
      for (const { name, fn } of listeners) {
        es.removeEventListener(name, fn as EventListener);
      }
      es.close();
      handleRef.current = null;
    }
    if (backoffTimerRef.current) {
      clearTimeout(backoffTimerRef.current);
      backoffTimerRef.current = null;
    }
  }, []);

  const attach = useCallback(
    (sid: string) => {
      detach();
      const url = new URL(
        `${API_BASE}/api/insights/sessions/${encodeURIComponent(sid)}/stream`,
        window.location.origin,
      );
      if (lastEventIdRef.current) {
        url.searchParams.set("last_event_id", lastEventIdRef.current);
      }
      if (promptRef.current) {
        url.searchParams.set("focus", promptRef.current);
      }

      let es: EventSource;
      try {
        es = new EventSource(url.toString(), { withCredentials: false });
      } catch (e) {
        setStatus("error");
        setError({
          code: "stream_construct_failed",
          message: e instanceof Error ? e.message : String(e),
        });
        return;
      }

      const listeners: InternalESHandle["listeners"] = [];

      const dispatchTyped = (name: SSEEventName, raw: MessageEvent) => {
        let parsed: unknown;
        try {
          parsed = raw.data ? JSON.parse(raw.data as string) : {};
        } catch (parseErr) {
          // Bad JSON from server: surface as an error event but don't crash
          // the stream — keep listening for the next frame.
          console.warn("[useInsightStream] invalid JSON for", name, parseErr);
          return;
        }
        const evtId = raw.lastEventId || `${Date.now()}`;
        lastEventIdRef.current = evtId;
        setLastEventId(evtId);

        if (name === "ping") {
          // Ignore heartbeats but still record the id so resume works.
          return;
        }

        const evt = {
          event: name,
          event_id: evtId,
          data: parsed,
        } as InsightSSEEvent;

        setEvents((prev) => [...prev, evt]);

        if (name === "session_started") {
          setStatus("running");
          setReconnecting(false);
          attemptRef.current = 0;
        } else if (name === "session_complete") {
          setStatus("complete");
          setReconnecting(false);
          detach();
        } else if (name === "error") {
          const payload = parsed as { code?: string; message?: string; retryable?: boolean };
          if (payload && payload.retryable === false) {
            setStatus("error");
            setError({
              code: payload.code || "stream_error",
              message: payload.message || "Unknown stream error",
            });
            detach();
          }
        }
      };

      for (const name of KNOWN_EVENTS) {
        const fn = (e: MessageEvent) => dispatchTyped(name, e);
        es.addEventListener(name, fn as EventListener);
        listeners.push({ name, fn });
      }

      es.onopen = () => {
        if (status !== "running") setStatus("connecting");
        setReconnecting(false);
      };

      es.onerror = () => {
        // EventSource sets readyState to CLOSED on hard failure.
        if (cancelledRef.current) return;
        if (es.readyState === EventSource.CLOSED) {
          setReconnecting(true);
          setStatus("reconnecting");
          const delay =
            RECONNECT_BACKOFF_MS[
              Math.min(attemptRef.current, RECONNECT_BACKOFF_MS.length - 1)
            ];
          attemptRef.current += 1;
          backoffTimerRef.current = setTimeout(() => {
            attachRef.current?.(sid);
          }, delay);
        }
      };

      handleRef.current = { es, listeners };
    },
    [detach, status],
  );

  // Keep a ref to the latest `attach` so reconnect timers can call the current
  // closure without violating the rules-of-hooks "access before declared" rule.
  useEffect(() => {
    attachRef.current = attach;
  }, [attach]);

  const start = useCallback(
    (prompt?: string) => {
      if (!sessionId) {
        setStatus("error");
        setError({
          code: "missing_session_id",
          message: "Cannot start stream without a session id.",
        });
        return;
      }
      if (handleRef.current) return;
      cancelledRef.current = false;
      promptRef.current = prompt;
      setEvents([]);
      setError(null);
      lastEventIdRef.current = null;
      setLastEventId(null);
      attemptRef.current = 0;
      setStatus("connecting");
      attach(sessionId);
    },
    [attach, sessionId],
  );

  const stop = useCallback(() => {
    cancelledRef.current = true;
    detach();
    setStatus((prev) => (prev === "complete" || prev === "error" ? prev : "cancelled"));
    setReconnecting(false);
  }, [detach]);

  const reset = useCallback(() => {
    cancelledRef.current = true;
    detach();
    setEvents([]);
    setError(null);
    lastEventIdRef.current = null;
    setLastEventId(null);
    attemptRef.current = 0;
    setStatus("idle");
    setReconnecting(false);
  }, [detach]);

  const replay = useCallback(() => events.slice(), [events]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      cancelledRef.current = true;
      detach();
    };
  }, [detach]);

  return {
    events,
    status,
    reconnecting,
    error,
    lastEventId,
    start,
    stop,
    reset,
    replay,
  };
}
