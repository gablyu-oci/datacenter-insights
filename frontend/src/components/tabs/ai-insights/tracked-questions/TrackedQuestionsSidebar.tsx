import {
  useEffect,
  useMemo,
  useRef,
  type CSSProperties,
} from "react";
import { RefreshCw, X } from "lucide-react";
import { tokens } from "../../../../styles/insightTokens";
import {
  useOpenQuestionsPolling,
  type UseOpenQuestionsPollingResult,
} from "../../../../hooks/useOpenQuestionsPolling";
import StatusPill from "./StatusPill";
import TrackedQuestionCard from "./TrackedQuestionCard";
import { compareQuestions } from "./constants";
import type { OpenQuestion, OpenQuestionStatus } from "../types";

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

/**
 * TrackedQuestionsSidebar — Phase D root component.
 *
 * Owns: layout (rail / drawer), polling lifecycle (via the hook), header
 * controls, count summary, list rendering, and the four state branches
 * (loading / error / empty / data).
 *
 * Spec: docs/ai_insights_v2_sidebar_design.md
 */

export interface TrackedQuestionsSidebarProps {
  /** Controlled-open mode for the AIInsightsTab parent. If omitted, no
   *  controlled behavior — the sidebar is always rendered (rail) or shown
   *  per `open` (drawer). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** "rail" sticks to the right column at xl+; "drawer" overlays the page. */
  variant?: "rail" | "drawer";
  /** Test seam — bypass the hook and render against a fixed result. */
  __testHookResult?: UseOpenQuestionsPollingResult;
}

const POLL_PULSE_KEYFRAMES = `
@keyframes tqPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}
@media (prefers-reduced-motion: reduce) {
  [data-tq-pulse] { animation: none !important; opacity: 0.6 !important; }
}
`;

export default function TrackedQuestionsSidebar({
  open,
  onOpenChange,
  variant = "rail",
  __testHookResult,
}: TrackedQuestionsSidebarProps) {
  const hookResult = useOpenQuestionsPolling();
  const result = __testHookResult ?? hookResult;
  const { data, isLoading, isFetching, error, refetch } = result;

  const sorted = useMemo<OpenQuestion[]>(() => {
    if (!data) return [];
    return [...data].sort(compareQuestions);
  }, [data]);

  const counts = useMemo(() => {
    const acc: Record<OpenQuestionStatus, number> = {
      watching: 0,
      confirmed: 0,
      disproved: 0,
      stale: 0,
    };
    if (data) {
      for (const q of data) acc[q.status] += 1;
    }
    return acc;
  }, [data]);

  const drawerCloseRef = useRef<HTMLButtonElement | null>(null);
  const drawerTriggerSourceRef = useRef<HTMLElement | null>(null);

  // Drawer focus management + Escape close.
  useEffect(() => {
    if (variant !== "drawer" || !open) return;
    drawerTriggerSourceRef.current =
      (document.activeElement as HTMLElement | null) ?? null;
    drawerCloseRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange?.(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      // Restore focus to the element that opened the drawer.
      drawerTriggerSourceRef.current?.focus?.();
    };
  }, [variant, open, onOpenChange]);

  // Drawer hidden -> render nothing.
  if (variant === "drawer" && !open) return null;

  const isEmpty = !isLoading && !error && data !== null && data.length === 0;
  const isErrorWithoutData = !!error && (data === null || data.length === 0);

  const containerStyle: CSSProperties =
    variant === "drawer"
      ? {
          position: "fixed",
          right: 0,
          top: 0,
          bottom: 0,
          width: "min(420px, 92vw)",
          maxWidth: "92vw",
          background: c.bg.card,
          borderLeft: `1px solid ${c.border.default}`,
          padding: s.s4,
          display: "flex",
          flexDirection: "column",
          gap: s.s3,
          zIndex: 50,
          overflowY: "auto",
          overscrollBehavior: "contain",
        }
      : {
          width: 340,
          background: c.bg.card,
          border: `1px solid ${c.border.default}`,
          borderRadius: r.xl,
          padding: s.s4,
          display: "flex",
          flexDirection: "column",
          gap: s.s3,
          position: "sticky",
          top: s.s4,
          maxHeight: `calc(100vh - ${s.s4 * 2}px)`,
          overflowY: "auto",
          overscrollBehavior: "contain",
        };

  const sidebarBody = (
    <aside
      role={variant === "drawer" ? "dialog" : "complementary"}
      aria-modal={variant === "drawer" ? true : undefined}
      aria-labelledby="tq-title"
      style={containerStyle}
    >
      <style>{POLL_PULSE_KEYFRAMES}</style>

      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: s.s2,
          minHeight: 32,
        }}
      >
        <h2
          id="tq-title"
          style={{
            margin: 0,
            color: c.text.primary,
            fontSize: 14,
            fontWeight: 600,
            flex: "1 1 auto",
            minWidth: 0,
          }}
        >
          Tracked questions
        </h2>
        <span
          aria-label="Refreshing tracked questions"
          aria-hidden={isFetching ? undefined : "true"}
          data-tq-pulse
          data-testid="tq-polling-dot"
          title={
            result.lastFetchedAt
              ? `Updated nightly via memory consolidation. Last fetched ${result.lastFetchedAt.toISOString()}.`
              : "Updated nightly via memory consolidation."
          }
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            borderRadius: "50%",
            backgroundColor: c.brand.primary,
            opacity: isFetching ? 1 : 0,
            animation: isFetching ? "tqPulse 2s ease-in-out infinite" : "none",
            transition: "opacity 150ms",
          }}
        />
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          aria-label="Refresh tracked questions"
          style={iconButtonStyle(isFetching)}
        >
          <RefreshCw size={14} aria-hidden="true" />
        </button>
        {variant === "drawer" ? (
          <button
            ref={drawerCloseRef}
            type="button"
            onClick={() => onOpenChange?.(false)}
            aria-label="Close tracked questions"
            style={iconButtonStyle(false)}
          >
            <X size={14} aria-hidden="true" />
          </button>
        ) : null}
      </header>

      <p
        role="status"
        aria-live="polite"
        style={{
          margin: 0,
          color: c.text.caption,
          fontSize: t.meta.fontSize,
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        {data === null ? (
          <span aria-hidden="true">&nbsp;</span>
        ) : (
          [
            ["watching", counts.watching] as const,
            ["confirmed", counts.confirmed] as const,
            ["stale", counts.stale] as const,
            ["disproved", counts.disproved] as const,
          ]
            .filter(([, n]) => n > 0)
            .map(([status, n]) => (
              <StatusPill
                key={status}
                status={status}
                count={n}
              />
            ))
        )}
      </p>

      {error && (data?.length ?? 0) > 0 ? (
        <InlineError
          message={error.message}
          onRetry={refetch}
          variant="banner-above-stale"
        />
      ) : null}

      <ul
        aria-live="polite"
        aria-busy={isLoading ? true : undefined}
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: s.s3,
        }}
      >
        {isLoading ? (
          <SkeletonList count={3} />
        ) : isErrorWithoutData ? (
          <li>
            <InlineError
              message={error?.message ?? "Unknown error"}
              onRetry={refetch}
              variant="standalone"
            />
          </li>
        ) : isEmpty ? (
          <li>
            <EmptyState />
          </li>
        ) : (
          sorted.map((q) => (
            <li key={q.id}>
              <TrackedQuestionCard question={q} />
            </li>
          ))
        )}
      </ul>
    </aside>
  );

  if (variant === "drawer") {
    return (
      <>
        <div
          aria-hidden="true"
          onClick={() => onOpenChange?.(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            zIndex: 49,
          }}
        />
        {sidebarBody}
      </>
    );
  }

  return sidebarBody;
}

function iconButtonStyle(disabled: boolean): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 32,
    height: 32,
    background: "transparent",
    border: "none",
    borderRadius: r.sm,
    color: c.text.muted,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    padding: 0,
  };
}

function SkeletonList({ count }: { count: number }) {
  const items = Array.from({ length: count }, (_, i) => i);
  return (
    <>
      {items.map((i) => (
        <li
          key={i}
          aria-hidden="true"
          data-testid="tq-skeleton-card"
          className="animate-pulse"
          style={{
            background: c.bg.card,
            border: `1px dashed ${c.border.default}`,
            borderRadius: r.lg,
            padding: s.s3,
            height: 84,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <div
            style={{
              height: 12,
              width: "60%",
              background: c.border.default,
              borderRadius: 4,
            }}
          />
          <div
            style={{
              height: 10,
              width: "100%",
              background: c.border.default,
              borderRadius: 4,
              opacity: 0.7,
            }}
          />
          <div
            style={{
              height: 10,
              width: "40%",
              background: c.border.default,
              borderRadius: 4,
              opacity: 0.5,
            }}
          />
        </li>
      ))}
    </>
  );
}

function InlineError({
  message,
  onRetry,
  variant,
}: {
  message: string;
  onRetry: () => void;
  variant: "standalone" | "banner-above-stale";
}) {
  return (
    <div
      role="alert"
      data-testid="tq-error"
      style={{
        background: c.bg.warningSubtle,
        border: `1px solid ${c.semantic.warning}`,
        borderRadius: r.md,
        padding: s.s3,
        color: c.semantic.warning,
        fontSize: t.body.fontSize,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        marginBottom: variant === "banner-above-stale" ? 0 : undefined,
      }}
    >
      <strong style={{ fontWeight: 600 }}>
        Couldn{"\u2019"}t load tracked questions.
      </strong>
      <span style={{ color: c.text.caption, fontSize: t.meta.fontSize }}>
        {message}
      </span>
      <button
        type="button"
        onClick={onRetry}
        aria-label="Retry loading tracked questions"
        style={{
          alignSelf: "flex-start",
          background: "transparent",
          color: c.semantic.warning,
          border: `1px solid ${c.semantic.warning}`,
          borderRadius: r.sm,
          padding: "4px 10px",
          height: 28,
          cursor: "pointer",
          fontWeight: 600,
          fontSize: t.meta.fontSize,
        }}
      >
        Retry
      </button>
    </div>
  );
}

function EmptyState() {
  // Single-string copy per the Phase D acceptance test ("No tracked
  // questions yet — they appear after the agent's first session.").
  return (
    <div
      data-testid="tq-empty"
      style={{
        background: c.bg.card,
        border: `1px dashed ${c.border.default}`,
        borderRadius: r.lg,
        padding: s.s5,
        textAlign: "center",
        color: c.text.caption,
        fontSize: t.body.fontSize,
      }}
    >
      {"No tracked questions yet \u2014 they appear after the agent\u2019s first session."}
    </div>
  );
}
