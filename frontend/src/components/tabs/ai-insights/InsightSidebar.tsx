import { useCallback, useId, useState } from "react";
import { ChevronRight } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import Collapsible from "./Collapsible";
import SidebarRow from "./SidebarRow";
import {
  useSavedInsights,
  type SavedInsightRow,
} from "../../../hooks/useSavedInsights";
import {
  useSessionHistory,
  type SessionHistoryRow,
} from "../../../hooks/useSessionHistory";
import type { LatestInsight } from "../../../hooks/useLatestInsightSession";

/**
 * InsightSidebar — left column of the AI Insights mail-app layout.
 * Per docs/planning/ai-insights-mail-layout/02-architecture.md §4 and
 * 03-ux-spec.md §§1-4.
 *
 * Three collapsible groups:
 *   1. Today           — defaults open, lists `todayInsights`.
 *   2. Saved           — lazy-fetches via useSavedInsights on first expand.
 *   3. Past runs       — lazy-fetches via useSessionHistory on first expand;
 *                        each session expands inline to reveal nested rows.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

interface SessionInsightItem {
  id: string;
  session_id: string;
  idx: number;
  headline: string;
  confidence: string;
  materiality: string;
  skills_run: string[];
  low_external_support: boolean | null;
  created_at: string | null;
  is_saved?: boolean | null;
}

interface SessionInsightsResponse {
  items?: SessionInsightItem[] | null;
  total?: number | null;
}

type LoadState = "loading" | "loaded" | "error";

interface SessionCacheEntry {
  state: LoadState;
  items: SessionInsightItem[];
  error: string | null;
}

export interface InsightSidebarProps {
  todayInsights: LatestInsight[];
  selectedInsightId: string | null;
  effectiveSaved: (id: string, fallback: boolean) => boolean;
  onSelect: (insight: LatestInsight) => void;
  /** Optional initial-saved-count hint to decide whether to default-open Saved. */
  initialSavedOpen?: boolean;
}

/**
 * Adapter: SessionInsightItem (from /api/insights/sessions/{id}/insights)
 * carries headline + chips but NOT body/chart/citations. We emit a
 * LatestInsight-shaped object with nulls so the detail pane can still render
 * headline, chips, the Save button, and the chat dock. Full body/chart for
 * past-run insights is a future enhancement.
 */
function adaptSessionInsightToLatest(
  ins: SessionInsightItem,
): LatestInsight {
  return {
    id: ins.id,
    session_id: ins.session_id,
    idx: ins.idx,
    headline: ins.headline,
    body: null,
    confidence: ins.confidence,
    materiality: ins.materiality,
    skills_run: ins.skills_run ?? [],
    low_external_support: ins.low_external_support ?? false,
    created_at: ins.created_at,
    chart: null,
    citations: [],
    is_saved: ins.is_saved ?? false,
  };
}

export default function InsightSidebar({
  todayInsights,
  selectedInsightId,
  effectiveSaved,
  onSelect,
  initialSavedOpen = false,
}: InsightSidebarProps) {
  const saved = useSavedInsights();
  const sessions = useSessionHistory({ limit: 20, status: "completed" });

  const [expandedSessions, setExpandedSessions] = useState<
    Record<string, boolean>
  >({});
  const [sessionCache, setSessionCache] = useState<
    Record<string, SessionCacheEntry>
  >({});

  const loadInsightsForSession = useCallback(
    async (sessionId: string) => {
      setSessionCache((prev) => ({
        ...prev,
        [sessionId]: { state: "loading", items: [], error: null },
      }));
      try {
        const res = await fetch(
          `${API_BASE}/api/insights/sessions/${encodeURIComponent(
            sessionId,
          )}/insights`,
          { method: "GET", headers: { Accept: "application/json" } },
        );
        if (!res.ok) {
          setSessionCache((prev) => ({
            ...prev,
            [sessionId]: {
              state: "error",
              items: [],
              error: `request failed: ${res.status}`,
            },
          }));
          return;
        }
        const body = (await res.json()) as SessionInsightsResponse | null;
        const items = Array.isArray(body?.items)
          ? (body!.items as SessionInsightItem[])
          : [];
        setSessionCache((prev) => ({
          ...prev,
          [sessionId]: { state: "loaded", items, error: null },
        }));
      } catch (e) {
        setSessionCache((prev) => ({
          ...prev,
          [sessionId]: {
            state: "error",
            items: [],
            error: e instanceof Error ? e.message : String(e),
          },
        }));
      }
    },
    [],
  );

  const toggleSession = useCallback(
    (sessionId: string) => {
      const willBeOpen = !expandedSessions[sessionId];
      setExpandedSessions((prev) => ({
        ...prev,
        [sessionId]: !prev[sessionId],
      }));
      if (willBeOpen && !sessionCache[sessionId]) {
        void loadInsightsForSession(sessionId);
      }
    },
    [expandedSessions, sessionCache, loadInsightsForSession],
  );

  return (
    <aside
      aria-label="Insight list"
      style={{
        position: "sticky",
        top: 24,
        alignSelf: "flex-start",
        maxHeight: "calc(100vh - 80px)",
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: s.s2,
        background: c.bg.card,
        border: `1px solid ${c.border.default}`,
        borderRadius: r.lg,
        padding: s.s2,
      }}
    >
      {/* Today ----------------------------------------------------------- */}
      <Collapsible
        title="Today"
        count={todayInsights.length}
        defaultOpen={true}
      >
        {todayInsights.length === 0 ? (
          <div
            style={{
              color: c.text.caption,
              fontSize: t.body.fontSize,
              padding: `${s.s2}px ${s.s3}px`,
            }}
          >
            No insights for today.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {todayInsights.map((ins) => (
              <SidebarRow
                key={ins.id}
                headline={ins.headline}
                selected={selectedInsightId === ins.id}
                saved={effectiveSaved(ins.id, ins.is_saved ?? false)}
                onClick={() => onSelect(ins)}
              />
            ))}
          </div>
        )}
      </Collapsible>

      {/* Saved ----------------------------------------------------------- */}
      <Collapsible
        title="Saved"
        count={saved.total || saved.items.length}
        countPending={saved.loading && saved.items.length === 0}
        defaultOpen={initialSavedOpen}
        onFirstExpand={() => saved.refetch()}
      >
        {saved.loading && saved.items.length === 0 ? (
          <div
            style={{
              color: c.text.caption,
              fontSize: t.body.fontSize,
              padding: `${s.s2}px ${s.s3}px`,
              textAlign: "center",
            }}
          >
            Loading…
          </div>
        ) : saved.error ? (
          <div
            role="alert"
            style={{
              color: c.semantic.danger,
              fontSize: t.body.fontSize,
              padding: `${s.s2}px ${s.s3}px`,
            }}
          >
            Couldn't load saved insights.
          </div>
        ) : saved.items.length === 0 ? (
          <div
            style={{
              color: c.text.caption,
              fontSize: t.body.fontSize,
              padding: `${s.s2}px ${s.s3}px`,
            }}
          >
            No saved insights yet.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {saved.items.map((row: SavedInsightRow) => (
              <SidebarRow
                key={row.id}
                headline={row.headline}
                selected={selectedInsightId === row.id}
                saved={effectiveSaved(row.id, true)}
                onClick={() => onSelect(row)}
              />
            ))}
          </div>
        )}
      </Collapsible>

      {/* Past runs ------------------------------------------------------- */}
      <Collapsible
        title="Past runs"
        count={sessions.total || sessions.items.length}
        countPending={sessions.loading && sessions.items.length === 0}
        defaultOpen={false}
        onFirstExpand={() => sessions.refetch()}
      >
        {sessions.loading && sessions.items.length === 0 ? (
          <div
            style={{
              color: c.text.caption,
              fontSize: t.body.fontSize,
              padding: `${s.s2}px ${s.s3}px`,
              textAlign: "center",
            }}
          >
            Loading…
          </div>
        ) : sessions.error ? (
          <div
            role="alert"
            style={{
              color: c.semantic.danger,
              fontSize: t.body.fontSize,
              padding: `${s.s2}px ${s.s3}px`,
            }}
          >
            Couldn't load past runs.
          </div>
        ) : sessions.items.length === 0 ? (
          <div
            style={{
              color: c.text.caption,
              fontSize: t.body.fontSize,
              padding: `${s.s2}px ${s.s3}px`,
            }}
          >
            No past runs yet.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {sessions.items.map((session: SessionHistoryRow) => (
              <PastRunSessionGroup
                key={session.id}
                session={session}
                expanded={!!expandedSessions[session.id]}
                onToggle={() => toggleSession(session.id)}
                cacheEntry={sessionCache[session.id]}
                onRetry={() => loadInsightsForSession(session.id)}
                selectedInsightId={selectedInsightId}
                effectiveSaved={effectiveSaved}
                onSelect={(ins) => onSelect(adaptSessionInsightToLatest(ins))}
              />
            ))}
            {sessions.hasMore ? (
              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  paddingTop: s.s2,
                }}
              >
                <button
                  type="button"
                  onClick={() => sessions.loadMore()}
                  disabled={sessions.loading}
                  style={{
                    background: c.bg.surfaceAlt,
                    color: c.text.body,
                    border: `1px solid ${c.border.default}`,
                    borderRadius: r.md,
                    padding: `${s.s2}px ${s.s4}px`,
                    fontSize: t.body.fontSize,
                    fontWeight: 500,
                    cursor: sessions.loading ? "not-allowed" : "pointer",
                    opacity: sessions.loading ? 0.7 : 1,
                    fontFamily: "inherit",
                  }}
                >
                  {sessions.loading ? "Loading…" : "Load more"}
                </button>
              </div>
            ) : null}
          </div>
        )}
      </Collapsible>
    </aside>
  );
}

interface PastRunSessionGroupProps {
  session: SessionHistoryRow;
  expanded: boolean;
  onToggle: () => void;
  cacheEntry: SessionCacheEntry | undefined;
  onRetry: () => void;
  selectedInsightId: string | null;
  effectiveSaved: (id: string, fallback: boolean) => boolean;
  onSelect: (ins: SessionInsightItem) => void;
}

function PastRunSessionGroup({
  session,
  expanded,
  onToggle,
  cacheEntry,
  onRetry,
  selectedInsightId,
  effectiveSaved,
  onSelect,
}: PastRunSessionGroupProps) {
  const regionId = useId() + "-region";
  const dateLabel = formatRowDate(session.started_at);
  const insightCountText =
    session.insights_emitted === 1
      ? "1 insight"
      : `${session.insights_emitted} insights`;

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={regionId}
        aria-label={
          expanded
            ? `Collapse session from ${dateLabel}`
            : `Expand session from ${dateLabel}`
        }
        style={{
          display: "flex",
          alignItems: "center",
          width: "100%",
          textAlign: "left",
          gap: s.s2,
          background: expanded ? c.bg.surfaceAlt : "transparent",
          color: expanded ? c.text.primary : c.text.body,
          border: "none",
          borderBottom: `1px solid ${c.border.weak}`,
          padding: "10px 12px",
          fontFamily: "inherit",
          fontSize: t.body.fontSize,
          fontWeight: t.body.fontWeight,
          cursor: "pointer",
          transition: `${tokens.motion.transitionColor}, ${tokens.motion.transitionBg}`,
        }}
      >
        <ChevronRight
          size={12}
          aria-hidden="true"
          style={{
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 150ms ease-out",
            flex: "0 0 auto",
          }}
        />
        <span style={{ flex: "1 1 auto", minWidth: 0 }}>{dateLabel}</span>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: `2px ${s.s2}px`,
            background: c.brand.tintDark,
            border: `1px solid ${c.brand.primary}`,
            borderRadius: r.pill,
            color: c.text.primary,
            fontSize: t.caption.fontSize,
            fontWeight: t.caption.fontWeight,
            flex: "0 0 auto",
          }}
        >
          {insightCountText}
        </span>
      </button>
      {expanded ? (
        <div
          id={regionId}
          role="region"
          style={{ display: "flex", flexDirection: "column" }}
        >
          {!cacheEntry || cacheEntry.state === "loading" ? (
            <div
              style={{
                color: c.text.caption,
                fontSize: t.body.fontSize,
                padding: `${s.s2}px ${s.s3}px ${s.s2}px ${12 + 16}px`,
              }}
            >
              Loading insights…
            </div>
          ) : cacheEntry.state === "error" ? (
            <div
              role="alert"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: `${s.s2}px ${s.s3}px ${s.s2}px ${12 + 16}px`,
                color: c.semantic.danger,
                fontSize: t.body.fontSize,
              }}
            >
              <span>Couldn't load insights.</span>
              <button
                type="button"
                onClick={onRetry}
                style={{
                  background: "transparent",
                  border: "none",
                  color: c.brand.primary,
                  fontFamily: "inherit",
                  fontSize: t.caption.fontSize,
                  fontWeight: 600,
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                Retry
              </button>
            </div>
          ) : cacheEntry.items.length === 0 ? (
            <div
              style={{
                color: c.text.caption,
                fontSize: t.body.fontSize,
                padding: `${s.s2}px ${s.s3}px ${s.s2}px ${12 + 16}px`,
              }}
            >
              No insights in this session.
            </div>
          ) : (
            cacheEntry.items.map((ins) => (
              <SidebarRow
                key={ins.id}
                headline={ins.headline}
                selected={selectedInsightId === ins.id}
                saved={effectiveSaved(ins.id, ins.is_saved ?? false)}
                onClick={() => onSelect(ins)}
                indent={16}
              />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

function formatRowDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
      timeZoneName: "short",
    });
  } catch {
    return iso;
  }
}
