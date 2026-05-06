import { useEffect, useMemo, useRef, useState } from "react";
import { Square } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import { useInsightStream } from "../../../hooks/useInsightStream";
import type {
  ChartPayload,
  CitationPayload,
  InsightSSEEvent,
  InsightStartedPayload,
  InsightCompletePayload,
  SessionStartedPayload,
  TokenPayload,
  WebCitation,
  WebSearchUnavailableEventData,
} from "../../../types/sseEvents";
import type { ChartSpec } from "../../../types/chartSpec";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import InsightCard from "./InsightCard";
import SkeletonStack from "./SkeletonStack";
import SurveyingBanner from "./SurveyingBanner";
import type { DataSourceUsed } from "./ProvenanceFooter";

/**
 * SessionRunner — orchestrates one insights session run.
 *
 *   - Reduces the SSE event log into a {sessionStarted, insights[]} struct.
 *   - Picks the right phase view: empty / surveying / skeletons / cards /
 *     error / cancelled.
 *   - Renders each in-flight or finished insight as an `<InsightCard>`.
 *
 * The actual POST that creates the session is owned by the parent
 * (`AIInsightsTab`) — this component receives the resulting `sessionId`
 * and a `start()` callback that wires up the stream.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

interface InsightInProgress {
  insight_id: string;
  index: number;
  headline: string;
  body: string;
  chart: ChartSpec | null;
  chartError: string | null;
  data_sources_used: DataSourceUsed[];
  citations: WebCitation[];
  complete: InsightCompletePayload | null;
}

export interface SessionRunnerProps {
  sessionId: string | null;
  /** Triggered by EmptyState's CTA. The parent must create the session and
   *  set `sessionId`, then call `onStart(prompt)` after the stream is ready. */
  onStart: (prompt?: string) => void;
  /** True when this runner is the live one (vs a read-only past session). */
  active: boolean;
  /** Total insights expected for surveying-banner ETA copy. */
  expectedInsights?: number;
  /** V2 feature flag — forwarded to InsightCard so Discuss/Subscribe show. */
  isV2Enabled?: boolean;
  /** Lifted up to AIInsightsTab so the tab-level banner renders once. */
  onWebSearchUnavailable?: (data: WebSearchUnavailableEventData) => void;
  /** Fired exactly once per session, the first time an `insight_complete`
   *  event lands. Used by AIInsightsTab to swap from snapshot -> live feed
   *  without flash-of-empty. Optional; existing callers pass nothing. */
  onFirstInsightComplete?: () => void;
  /** Fired when the stream goes terminal-error (pre any insight). Lets
   *  AIInsightsTab restore the snapshot insights it was holding. */
  onStreamError?: (msg: string) => void;
}

export default function SessionRunner({
  sessionId,
  onStart,
  active,
  expectedInsights = 7,
  isV2Enabled = false,
  onWebSearchUnavailable,
  onFirstInsightComplete,
  onStreamError,
}: SessionRunnerProps) {
  const stream = useInsightStream(sessionId);
  const [retryStamp, setRetryStamp] = useState(0);
  const startedRef = useRef<string | null>(null);
  const seenWebSearchEventIds = useRef<Set<string>>(new Set());
  const firstCompleteFiredRef = useRef<string | null>(null);
  const streamErrorFiredRef = useRef<string | null>(null);

  // Auto-start the stream once we have a sessionId.
  useEffect(() => {
    if (!active) return;
    if (!sessionId) return;
    if (startedRef.current === sessionId) return;
    startedRef.current = sessionId;
    stream.start();
  }, [active, sessionId, stream, retryStamp]);

  // Surface web_search_unavailable events upward exactly once per event_id.
  useEffect(() => {
    if (!onWebSearchUnavailable) return;
    for (const evt of stream.events) {
      if (evt.event !== "web_search_unavailable") continue;
      if (seenWebSearchEventIds.current.has(evt.event_id)) continue;
      seenWebSearchEventIds.current.add(evt.event_id);
      onWebSearchUnavailable(evt.data);
    }
  }, [stream.events, onWebSearchUnavailable]);

  // Notify the parent the first time an insight_complete event lands per
  // session (used by AIInsightsTab to swap snapshot -> live feed). The
  // agentic path persists insights via OpenClaw + MCP and does NOT
  // emit per-insight insight_complete events on this stream — for that
  // path session_complete is the trigger to flip. Either signal is
  // enough to mean "stop showing the spinner; the new run is done."
  useEffect(() => {
    if (!onFirstInsightComplete) return;
    if (!sessionId) return;
    if (firstCompleteFiredRef.current === sessionId) return;
    const done = stream.events.some(
      (e) => e.event === "insight_complete" || e.event === "session_complete",
    );
    if (done) {
      firstCompleteFiredRef.current = sessionId;
      onFirstInsightComplete();
    }
  }, [stream.events, sessionId, onFirstInsightComplete]);

  // Notify the parent when the stream goes terminal-error so it can restore
  // the prior snapshot insights it was holding.
  useEffect(() => {
    if (!onStreamError) return;
    if (!sessionId) return;
    if (streamErrorFiredRef.current === sessionId) return;
    if (stream.status === "error" && stream.error) {
      streamErrorFiredRef.current = sessionId;
      onStreamError(stream.error.message);
    }
  }, [stream.status, stream.error, sessionId, onStreamError]);

  const reduced = useMemo(() => reduceEvents(stream.events), [stream.events]);

  if (!sessionId && stream.status === "idle") {
    return <EmptyState onRun={() => onStart()} />;
  }

  if (stream.status === "error" && stream.error) {
    return (
      <ErrorState
        title="AI service unavailable"
        message={stream.error.message}
        onRetry={() => {
          stream.reset();
          setRetryStamp((n) => n + 1);
        }}
      />
    );
  }

  const sessionMeta = reduced.session;
  const insights = reduced.insights;
  const isRunning = stream.status === "running" || stream.status === "connecting";

  const noInsightsYet = insights.length === 0;
  const surveying = noInsightsYet && (isRunning || stream.status === "reconnecting");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: s.s5 }}>
      {stream.status === "reconnecting" ? <ReconnectingToast /> : null}

      {surveying ? (
        <>
          <SurveyingBanner
            progress={Math.min(0.4, stream.events.length / 40)}
            message={
              reduced.surveyingMessage || "Surveying the platform…"
            }
            detail={`Hypotheses: ${reduced.surveyingCandidates} · Verified: ${
              insights.filter((i) => i.complete).length
            }`}
            eta="≤90 s"
          />
          <SkeletonStack count={3} total={expectedInsights} />
        </>
      ) : null}

      {insights.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: s.s6 }}>
          {insights.map((ins) => (
            <InsightCard
              key={ins.insight_id}
              index={ins.index + 1}
              total={sessionMeta?.max_insights}
              streaming={!ins.complete}
              headline={ins.complete?.headline || ins.headline}
              body={ins.body}
              chart={ins.chart}
              chartError={ins.chartError}
              confidence={ins.complete?.confidence}
              materiality={ins.complete?.materiality}
              lowExternalSupport={ins.complete?.low_external_support}
              dataSourcesUsed={ins.data_sources_used}
              skillsRun={ins.complete?.skills_run ?? []}
              generatedAt={sessionMeta?.started_at || ""}
              model={sessionMeta?.model || ""}
              sessionId={sessionMeta?.session_id || sessionId || ""}
              insightId={ins.insight_id}
              isV2Enabled={isV2Enabled}
              citations={ins.citations}
            />
          ))}
        </div>
      ) : null}

      {stream.status === "running" && insights.length > 0 && insights.some((i) => i.complete) ? (
        <SkeletonStack count={1} startIndex={insights.length} total={expectedInsights} />
      ) : null}

      {active ? (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            type="button"
            onClick={() => stream.stop()}
            disabled={!isRunning}
            style={{
              background: isRunning ? c.semantic.danger : c.border.default,
              color: c.text.primary,
              border: "none",
              borderRadius: r.md,
              padding: "8px 14px",
              fontSize: t.body.fontSize,
              fontWeight: 600,
              cursor: isRunning ? "pointer" : "not-allowed",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Square size={12} /> Cancel
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ReconnectingToast() {
  return (
    <div
      role="status"
      style={{
        position: "fixed",
        top: 80,
        right: 24,
        background: c.bg.card,
        color: c.text.caption,
        fontSize: t.meta.fontSize,
        padding: "8px 12px",
        borderRadius: r.md,
        border: `1px solid ${c.border.default}`,
        boxShadow: tokens.shadow.popover,
        zIndex: 1000,
      }}
    >
      Reconnecting…
    </div>
  );
}

interface ReducedSession {
  session: SessionStartedPayload | null;
  insights: InsightInProgress[];
  surveyingCandidates: number;
  surveyingMessage: string | null;
}

function reduceEvents(events: InsightSSEEvent[]): ReducedSession {
  let session: SessionStartedPayload | null = null;
  let surveyingCandidates = 0;
  let surveyingMessage: string | null = null;
  const byId = new Map<string, InsightInProgress>();
  const order: string[] = [];

  for (const evt of events) {
    if (evt.event === "session_started") {
      session = evt.data;
      continue;
    }
    if (evt.event === "surveying") {
      surveyingCandidates = evt.data.candidates_seen;
      surveyingMessage = evt.data.message;
      continue;
    }
    if (evt.event === "insight_started") {
      const p = evt.data as InsightStartedPayload;
      if (!byId.has(p.insight_id)) {
        byId.set(p.insight_id, {
          insight_id: p.insight_id,
          index: p.index,
          headline: p.headline_draft || "",
          body: "",
          chart: null,
          chartError: null,
          data_sources_used: [],
          citations: [],
          complete: null,
        });
        order.push(p.insight_id);
      }
      continue;
    }
    if (evt.event === "citation") {
      const p = evt.data as CitationPayload;
      const ins = byId.get(p.insight_id);
      if (!ins || !p.citation) continue;
      ins.citations.push(p.citation);
      continue;
    }
    if (evt.event === "token") {
      const p = evt.data as TokenPayload;
      const ins = byId.get(p.insight_id);
      if (!ins) continue;
      if (p.field === "headline") ins.headline += p.delta;
      else ins.body += p.delta;
      continue;
    }
    if (evt.event === "chart") {
      const p = evt.data as ChartPayload;
      const ins = byId.get(p.insight_id);
      if (!ins) continue;
      try {
        // Lightweight runtime guard — the spec is server-validated, but we
        // verify shape before handing off to Recharts.
        if (!p.chart || !p.chart.chart_type || !p.chart.encoding) {
          throw new Error("malformed chart spec");
        }
        ins.chart = p.chart;
        ins.chartError = null;
      } catch (e) {
        ins.chart = null;
        ins.chartError = e instanceof Error ? e.message : String(e);
      }
      continue;
    }
    if (evt.event === "tool_call") {
      // Track tool calls as data_sources_used in best-effort mode; the
      // server will deliver the canonical list at insight_complete.
      const ins = byId.get(evt.data.insight_id);
      if (!ins) continue;
      const name = evt.data.tool_name;
      if (name === "query_database") {
        ins.data_sources_used.push({
          kind: "db_query",
          label: evt.data.args_truncated.slice(0, 80),
          rows: 0,
        });
      } else if (name === "call_api") {
        ins.data_sources_used.push({
          kind: "router_call",
          label: evt.data.args_truncated.slice(0, 80),
          rows: 0,
        });
      } else if (name === "get_chart_data") {
        ins.data_sources_used.push({
          kind: "chart_data",
          label: evt.data.args_truncated.slice(0, 80),
          rows: 0,
        });
      }
      continue;
    }
    if (evt.event === "insight_complete") {
      const p = evt.data as InsightCompletePayload;
      const ins = byId.get(p.insight_id);
      if (!ins) continue;
      ins.complete = p;
      continue;
    }
  }

  return {
    session,
    insights: order.map((id) => byId.get(id)!),
    surveyingCandidates,
    surveyingMessage,
  };
}
