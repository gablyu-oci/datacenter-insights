import { tokens } from "../../../styles/insightTokens";
import InsightCard from "./InsightCard";
import type { ChartSpec } from "../../../types/chartSpec";
import type {
  Confidence,
  Materiality,
  WebCitation,
} from "../../../types/sseEvents";
import type {
  LatestCitation,
  LatestInsight,
  LatestSessionRow,
} from "../../../hooks/useLatestInsightSession";

/**
 * InsightDetailPane — right-hand pane of the mail-app layout. Wraps a single
 * InsightCard for the selected insight, or shows a placeholder when nothing is
 * selected. Per docs/planning/ai-insights-mail-layout/03-ux-spec.md §5.
 *
 * Helper functions adaptCitations and unwrapChart are inlined here (mirrors
 * the wiring used by SnapshotInsightFeed) so the detail pane has no source
 * dependency on the soon-to-be-unused legacy feed component.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

function adaptCitations(cits?: LatestCitation[] | null): WebCitation[] {
  if (!cits) return [];
  return cits.map((cit) => ({
    url: cit.url,
    title: cit.title ?? "",
    snippet: cit.snippet ?? "",
    agree_or_disagree:
      (cit.agree_or_disagree as "agree" | "disagree" | "context" | null) ??
      "context",
    rationale: "",
    search_query: cit.search_query ?? "",
    provider: cit.provider ?? undefined,
  }));
}

function unwrapChart(
  raw: Record<string, unknown> | null | undefined,
): ChartSpec | null {
  if (!raw) return null;
  const spec = raw["spec"];
  return ((spec ?? raw) as ChartSpec) ?? null;
}

export interface InsightDetailPaneProps {
  insight: LatestInsight | null;
  session: LatestSessionRow | null;
  total?: number;
  effectiveSaved: (id: string, fallback: boolean) => boolean;
  onSaveToggle: (id: string, next: boolean) => void;
}

export default function InsightDetailPane({
  insight,
  session,
  total,
  effectiveSaved,
  onSaveToggle,
}: InsightDetailPaneProps) {
  if (insight === null) {
    return (
      <div
        style={{
          background: c.bg.card,
          border: `1px dashed ${c.border.weak}`,
          borderRadius: r.lg,
          padding: s.s8,
          color: c.text.caption,
          fontSize: t.body.fontSize,
          textAlign: "center",
          minWidth: 0,
        }}
      >
        Pick an insight from the sidebar to read its detail.
      </div>
    );
  }

  return (
    <div style={{ minWidth: 0 }}>
      <InsightCard
        index={insight.idx + 1}
        total={total}
        streaming={false}
        headline={insight.headline}
        body={insight.body ?? undefined}
        chart={unwrapChart(
          insight.chart as Record<string, unknown> | null | undefined,
        )}
        confidence={insight.confidence as Confidence}
        materiality={insight.materiality as Materiality}
        lowExternalSupport={insight.low_external_support ?? false}
        dataSourcesUsed={[]}
        skillsRun={insight.skills_run ?? []}
        generatedAt={insight.created_at ?? session?.started_at ?? ""}
        model={session?.model ?? ""}
        sessionId={session?.id ?? insight.session_id}
        insightId={insight.id}
        isV2Enabled={true}
        citations={adaptCitations(insight.citations)}
        initialSaved={effectiveSaved(insight.id, insight.is_saved ?? false)}
        onSaveToggle={(next) => onSaveToggle(insight.id, next)}
      />
    </div>
  );
}
