import { tokens } from "../../../styles/insightTokens";
import InsightCard from "./InsightCard";
import type { ChartSpec } from "../../../types/chartSpec";
import type { Confidence, Materiality, WebCitation } from "../../../types/sseEvents";
import type {
  LatestCitation,
  LatestInsight,
  LatestSessionRow,
} from "../../../hooks/useLatestInsightSession";

function adaptCitations(cits?: LatestCitation[] | null): WebCitation[] {
  if (!cits) return [];
  return cits.map((c) => ({
    url: c.url,
    title: c.title ?? "",
    snippet: c.snippet ?? "",
    // Prefetch-time citations don't run the agree/disagree judge — surface
    // them as neutral "context" so InsightCard renders them without a bias.
    agree_or_disagree:
      (c.agree_or_disagree as "agree" | "disagree" | "context" | null) ??
      "context",
    rationale: "",
    search_query: c.search_query ?? "",
    provider: c.provider ?? undefined,
  }));
}

/**
 * SnapshotInsightFeed — renders persisted insights from `GET /api/insights/latest`
 * using the same `InsightCard` component as the live feed, with V2 features
 * (Discuss / Subscribe / inline chart) enabled.
 *
 * Streaming-only affordances (token caret, surveying spinner) are skipped
 * because this is a static snapshot — the SSE pipe is not attached.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;

export interface SnapshotInsightFeedProps {
  insights: LatestInsight[];
  /** True total expected for "Insight {idx} of {total}" header. */
  total?: number;
  /** Session row, used to source `model` + `sessionId` for InsightCard. */
  session?: LatestSessionRow | null;
}

export default function SnapshotInsightFeed({
  insights,
  total,
  session,
}: SnapshotInsightFeedProps) {
  if (insights.length === 0) {
    return (
      <div
        aria-label="snapshot insight feed"
        style={{
          color: c.text.caption,
          fontSize: t.body.fontSize,
          padding: s.s4,
        }}
      >
        No insights to show in this snapshot.
      </div>
    );
  }

  const model = session?.model ?? "";
  const sessionId = session?.id ?? "";

  return (
    <div
      aria-label="snapshot insight feed"
      aria-live="polite"
      style={{ display: "flex", flexDirection: "column", gap: s.s6 }}
    >
      {insights.map((ins) => (
        <InsightCard
          key={ins.id}
          index={ins.idx + 1}
          total={total}
          streaming={false}
          headline={ins.headline}
          body={ins.body ?? undefined}
          chart={(() => {
            // Backend wraps the chart as {chart_id, spec, data_source, row_hash};
            // SSE path emits a flat ChartSpec. Unwrap for InsightCard.
            const c = ins.chart as Record<string, unknown> | null | undefined;
            if (!c) return null;
            const spec = c["spec"];
            return ((spec ?? c) as ChartSpec) ?? null;
          })()}
          confidence={ins.confidence as Confidence}
          materiality={ins.materiality as Materiality}
          lowExternalSupport={ins.low_external_support ?? false}
          dataSourcesUsed={[]}
          skillsRun={ins.skills_run ?? []}
          generatedAt={ins.created_at ?? session?.started_at ?? ""}
          model={model}
          sessionId={sessionId}
          insightId={ins.id}
          isV2Enabled={true}
          citations={adaptCitations(ins.citations)}
        />
      ))}
    </div>
  );
}
