import { useCallback, useId, useState } from "react";
import { ChevronRight } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import Collapsible from "./Collapsible";
import InsightCard from "./InsightCard";
import {
  useSessionHistory,
  type SessionHistoryRow,
} from "../../../hooks/useSessionHistory";
import type { Confidence, Materiality } from "../../../types/sseEvents";

/**
 * PastRunsSection — collapsible list of completed AI sessions.
 *
 * Per docs/planning/save-and-history/04-ux-design.md §2.2/§2.3 and 00-PLAN.md
 * §3 D3:
 *   - Outer Collapsible lazy-loads the session list on first expand via the
 *     hook's `refetch()`.
 *   - Each row is itself a button that expands to reveal the session's
 *     insights. The first expand fires GET /api/insights/sessions/{id}/insights
 *     and the result is cached in component-local state.
 *   - Multi-expand allowed.
 *   - "Load more" appears at the bottom when `hasMore`.
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

type LoadState = "idle" | "loading" | "loaded" | "error";

interface SessionCacheEntry {
  state: LoadState;
  items: SessionInsightItem[];
  error: string | null;
}

export interface PastRunsSectionProps {
  /** Optional: hide the row matching this id (typically the current /latest session). */
  currentSessionId?: string | null;
}

export default function PastRunsSection({
  currentSessionId = null,
}: PastRunsSectionProps) {
  const sessions = useSessionHistory({ limit: 20, status: "completed" });
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [cache, setCache] = useState<Record<string, SessionCacheEntry>>({});
  // Per-row override map for save-button optimistic flips, scoped to the
  // expanded-region. Keyed by insight id, not session id.
  const [savedOverrides, setSavedOverrides] = useState<Record<string, boolean>>({});

  const visibleItems = sessions.items.filter(
    (row) => !currentSessionId || row.id !== currentSessionId,
  );

  const loadInsightsForSession = useCallback(
    async (sessionId: string) => {
      setCache((prev) => ({
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
          setCache((prev) => ({
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
        setCache((prev) => ({
          ...prev,
          [sessionId]: { state: "loaded", items, error: null },
        }));
      } catch (e) {
        setCache((prev) => ({
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

  const toggleRow = useCallback(
    (sessionId: string) => {
      setExpandedRows((prev) => {
        const next = { ...prev, [sessionId]: !prev[sessionId] };
        return next;
      });
      // Fire the fetch only on the first time this row expands.
      const entry = cache[sessionId];
      const willBeOpen = !expandedRows[sessionId];
      if (willBeOpen && (!entry || entry.state === "idle")) {
        void loadInsightsForSession(sessionId);
      }
    },
    [cache, expandedRows, loadInsightsForSession],
  );

  const effectiveSaved = (id: string, fallback: boolean): boolean =>
    savedOverrides[id] ?? fallback;

  return (
    <Collapsible
      title="Past runs"
      count={sessions.total || visibleItems.length}
      countPending={sessions.loading && sessions.items.length === 0}
      defaultOpen={false}
      onFirstExpand={() => sessions.refetch()}
    >
      {sessions.loading && sessions.items.length === 0 ? (
        <SkeletonRows count={3} />
      ) : sessions.error ? (
        <InlineError
          message="Couldn't load past runs."
          onRetry={() => sessions.refetch()}
        />
      ) : visibleItems.length === 0 ? (
        <EmptyState text="No past runs yet — kick off an AI session to see history here." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: s.s2 }}>
          {visibleItems.map((row) => (
            <PastRunRow
              key={row.id}
              row={row}
              expanded={!!expandedRows[row.id]}
              onToggle={() => toggleRow(row.id)}
              cacheEntry={cache[row.id]}
              onRetry={() => loadInsightsForSession(row.id)}
              effectiveSaved={effectiveSaved}
              onSaveToggle={(id, next) =>
                setSavedOverrides((m) => ({ ...m, [id]: next }))
              }
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
  );
}

interface PastRunRowProps {
  row: SessionHistoryRow;
  expanded: boolean;
  onToggle: () => void;
  cacheEntry: SessionCacheEntry | undefined;
  onRetry: () => void;
  effectiveSaved: (id: string, fallback: boolean) => boolean;
  onSaveToggle: (id: string, next: boolean) => void;
}

function PastRunRow({
  row,
  expanded,
  onToggle,
  cacheEntry,
  onRetry,
  effectiveSaved,
  onSaveToggle,
}: PastRunRowProps) {
  const regionId = useId() + "-region";
  const dateLabel = formatRowDate(row.started_at);
  const insightCountText =
    row.insights_emitted === 1 ? "1 insight" : `${row.insights_emitted} insights`;
  const focusLabel = row.focus && row.focus.trim().length > 0 ? row.focus : "General";

  return (
    <div>
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
          gap: s.s3,
          background: expanded ? c.bg.surfaceAlt : c.bg.card,
          color: expanded ? c.text.primary : c.text.body,
          border: `1px solid ${
            expanded ? c.border.default : c.border.weak
          }`,
          borderBottom: expanded
            ? `2px solid ${c.brand.primary}`
            : `1px solid ${c.border.weak}`,
          borderRadius: r.md,
          padding: `${s.s3}px ${s.s4}px`,
          fontFamily: "inherit",
          fontSize: t.body.fontSize,
          fontWeight: t.body.fontWeight,
          cursor: "pointer",
          transition: `${tokens.motion.transitionColor}, ${tokens.motion.transitionBg}`,
        }}
      >
        <ChevronRight
          size={14}
          aria-hidden="true"
          data-collapsible-chevron="true"
          style={{
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 150ms ease-out",
            flex: "0 0 auto",
          }}
        />
        <span style={{ flex: "1 1 auto" }}>{dateLabel}</span>
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
          }}
        >
          {insightCountText}
        </span>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: `2px ${s.s2}px`,
            background: c.bg.surfaceAlt,
            border: `1px solid ${c.border.default}`,
            borderRadius: r.pill,
            color: c.text.muted,
            fontSize: t.caption.fontSize,
            fontWeight: t.caption.fontWeight,
          }}
        >
          {focusLabel}
        </span>
      </button>
      {expanded ? (
        <div
          id={regionId}
          role="region"
          style={{
            paddingTop: s.s4,
            paddingBottom: s.s5,
            paddingLeft: s.s4,
            paddingRight: s.s4,
          }}
        >
          {!cacheEntry || cacheEntry.state === "loading" ? (
            <div
              style={{
                color: c.text.caption,
                fontSize: t.body.fontSize,
              }}
            >
              Loading insights…
            </div>
          ) : cacheEntry.state === "error" ? (
            <InlineError
              message="Couldn't load this session's insights."
              onRetry={onRetry}
            />
          ) : cacheEntry.items.length === 0 ? (
            <div
              style={{
                color: c.text.caption,
                fontSize: t.body.fontSize,
              }}
            >
              No insights were emitted in this session.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: s.s4 }}>
              {cacheEntry.items.map((ins) => (
                <InsightCard
                  key={ins.id}
                  index={ins.idx + 1}
                  total={cacheEntry.items.length}
                  streaming={false}
                  headline={ins.headline}
                  chart={null}
                  confidence={ins.confidence as Confidence}
                  materiality={ins.materiality as Materiality}
                  lowExternalSupport={ins.low_external_support ?? false}
                  dataSourcesUsed={[]}
                  skillsRun={ins.skills_run ?? []}
                  generatedAt={ins.created_at ?? row.started_at}
                  model={row.model ?? ""}
                  sessionId={row.id}
                  insightId={ins.id}
                  isV2Enabled={true}
                  initialSaved={effectiveSaved(ins.id, ins.is_saved ?? false)}
                  onSaveToggle={(next) => onSaveToggle(ins.id, next)}
                />
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: s.s2 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          aria-hidden="true"
          style={{
            height: 44,
            borderRadius: r.md,
            background: tokens.motion.skeletonGradient,
            backgroundSize: "200% 100%",
            animation: tokens.motion.skeletonAnimation,
          }}
        />
      ))}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div
      style={{
        border: `1px dashed ${c.border.weak}`,
        borderRadius: r.md,
        padding: `${s.s5}px ${s.s4}px`,
        color: c.text.caption,
        fontSize: t.body.fontSize,
        textAlign: "center",
      }}
    >
      {text}
    </div>
  );
}

function InlineError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      style={{
        background: c.bg.card,
        border: `1px solid ${c.semantic.danger}`,
        borderRadius: r.md,
        padding: `${s.s3}px ${s.s4}px`,
        color: c.text.body,
        fontSize: t.caption.fontSize,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: s.s3,
      }}
    >
      <span style={{ color: c.semantic.danger }}>{message}</span>
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
