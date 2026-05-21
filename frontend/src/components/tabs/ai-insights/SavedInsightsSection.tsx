import { tokens } from "../../../styles/insightTokens";
import Collapsible from "./Collapsible";
import InsightCard from "./InsightCard";
import { useSavedInsights } from "../../../hooks/useSavedInsights";
import type { ChartSpec } from "../../../types/chartSpec";
import type {
  Confidence,
  Materiality,
  WebCitation,
} from "../../../types/sseEvents";
import type { LatestCitation } from "../../../hooks/useLatestInsightSession";

/**
 * SavedInsightsSection — collapsible list of currently-saved insights.
 *
 * Per 00-PLAN.md §3 D4 and docs/planning/save-and-history/04-ux-design.md
 * §2.4 / §2.5:
 *   - Collapsible lazy-loads `/api/insights/saved` on first expand.
 *   - Each saved insight renders via InsightCard with `initialSaved=true`.
 *   - When the user un-saves a row from inside this section, we refetch so
 *     the row disappears (per plan default #4).
 *   - Empty state copy per 04-ux-design §4.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

function adaptCitations(cits?: LatestCitation[] | null): WebCitation[] {
  if (!cits) return [];
  return cits.map((c) => ({
    url: c.url,
    title: c.title ?? "",
    snippet: c.snippet ?? "",
    agree_or_disagree:
      (c.agree_or_disagree as "agree" | "disagree" | "context" | null) ??
      "context",
    rationale: "",
    search_query: c.search_query ?? "",
    provider: c.provider ?? undefined,
  }));
}

function unwrapChart(raw: Record<string, unknown> | null | undefined): ChartSpec | null {
  if (!raw) return null;
  const spec = raw["spec"];
  return ((spec ?? raw) as ChartSpec) ?? null;
}

export default function SavedInsightsSection() {
  const saved = useSavedInsights();

  return (
    <Collapsible
      title="Saved insights"
      count={saved.total || saved.items.length}
      countPending={saved.loading && saved.items.length === 0}
      defaultOpen={false}
      onFirstExpand={() => saved.refetch()}
    >
      {saved.loading && saved.items.length === 0 ? (
        <SkeletonCards count={2} />
      ) : saved.error ? (
        <InlineError
          message="Couldn't load saved insights."
          onRetry={() => saved.refetch()}
        />
      ) : saved.items.length === 0 ? (
        <EmptyState text="No saved insights yet — tap the bell on any insight to save it." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: s.s4 }}>
          {saved.items.map((ins) => (
            <InsightCard
              key={ins.id}
              index={ins.idx + 1}
              total={saved.items.length}
              streaming={false}
              headline={ins.headline}
              body={ins.body ?? undefined}
              chart={unwrapChart(ins.chart as Record<string, unknown> | null | undefined)}
              confidence={ins.confidence as Confidence}
              materiality={ins.materiality as Materiality}
              lowExternalSupport={ins.low_external_support ?? false}
              dataSourcesUsed={[]}
              skillsRun={ins.skills_run ?? []}
              generatedAt={ins.created_at ?? ins.saved_at ?? ""}
              model={""}
              sessionId={ins.session_id}
              insightId={ins.id}
              isV2Enabled={true}
              citations={adaptCitations(ins.citations)}
              initialSaved={true}
              onSaveToggle={(next) => {
                if (!next) {
                  saved.refetch();
                }
              }}
            />
          ))}
        </div>
      )}
    </Collapsible>
  );
}

function SkeletonCards({ count }: { count: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: s.s4 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          aria-hidden="true"
          style={{
            height: 160,
            borderRadius: r.lg,
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
