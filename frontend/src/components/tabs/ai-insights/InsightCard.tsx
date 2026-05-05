import { useState, type CSSProperties } from "react";
import { MessageSquare } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import InsightChart from "./InsightChart";
import ProvenanceFooter, { type DataSourceUsed } from "./ProvenanceFooter";
import { MarkdownRenderer, StreamingCaret } from "../../agentchat";
import type { ChartSpec } from "../../../types/chartSpec";
import type {
  Confidence,
  Materiality,
  WebCitation,
} from "../../../types/sseEvents";
import { CitationsRow } from "./CitationPill";
import InsightChatDock from "./InsightChatDock";
import SubscribeButton from "./SubscribeButton";

/**
 * InsightCard — a single insight per UX §U3.
 *
 * Composes:
 *   - Header (index, materiality + confidence chips OR drafting label)
 *   - Headline + subtitle (with streaming caret while drafting)
 *   - InsightChart from the ChartSpec
 *   - Figure caption
 *   - Provenance footer (collapsed by default)
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

export interface InsightCardProps {
  /** 1-based card index ("Insight 1 of 7"). */
  index: number;
  total?: number;
  /** Streaming = true while body/headline tokens are still arriving. */
  streaming?: boolean;
  headline: string;
  subtitle?: string;
  body?: string;
  chart?: ChartSpec | null;
  /** Cause string when chart failed to render (EE6). */
  chartError?: string | null;
  confidence?: Confidence;
  materiality?: Materiality;
  lowExternalSupport?: boolean;
  dataSourcesUsed: DataSourceUsed[];
  skillsRun: string[];
  generatedAt: string;
  model: string;
  sessionId: string;
  /** V2: web citations rendered as inline pills between body and provenance. */
  citations?: WebCitation[];
  /** V2 feature flag — gates Discuss/Subscribe affordances + citations row. */
  isV2Enabled?: boolean;
  /** Stable insight id (needed for V2 chat dock + subscribe). */
  insightId?: string;
  style?: CSSProperties;
}

export default function InsightCard({
  index,
  total,
  streaming = false,
  headline,
  subtitle,
  body,
  chart,
  chartError,
  confidence,
  materiality,
  lowExternalSupport = false,
  dataSourcesUsed,
  skillsRun,
  generatedAt,
  model,
  sessionId,
  citations,
  isV2Enabled = false,
  insightId,
  style,
}: InsightCardProps) {
  const headlineColor = streaming ? c.text.caption : c.text.primary;
  const [chatOpen, setChatOpen] = useState(false);
  const showV2Affordances = isV2Enabled && !streaming && Boolean(insightId);
  const visibleCitations = isV2Enabled && citations ? citations : [];
  return (
    <article
      aria-label={`insight ${index}${total ? ` of ${total}` : ""}`}
      style={{
        background: c.bg.card,
        border: streaming
          ? `1px dashed ${c.border.strong}`
          : `1px solid ${c.border.default}`,
        borderRadius: r.xl,
        padding: s.s5,
        display: "flex",
        flexDirection: "column",
        gap: s.s3,
        ...style,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          color: c.text.faint,
          fontSize: t.meta.fontSize,
        }}
      >
        <span>
          Insight {index}
          {total ? ` of ${total}` : ""}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {streaming ? (
            <span
              aria-label="drafting"
              style={{ color: c.text.caption, fontStyle: "italic" }}
            >
              drafting…
            </span>
          ) : (
            <>
              {materiality ? <MaterialityChip level={materiality} /> : null}
              {confidence ? <ConfidenceChip level={confidence} /> : null}
              {lowExternalSupport ? <LowSupportPill /> : null}
            </>
          )}
        </div>
      </header>

      <h2
        style={{
          color: headlineColor,
          fontSize: t.title.fontSize,
          fontWeight: t.title.fontWeight,
          lineHeight: t.title.lineHeight,
          margin: 0,
        }}
      >
        {headline || (streaming ? "" : "")}
        {streaming ? <StreamingCaret active /> : null}
      </h2>

      {subtitle ? (
        <p
          style={{
            color: c.text.muted,
            fontSize: t.body.fontSize,
            lineHeight: 1.5,
            margin: 0,
          }}
        >
          {subtitle}
        </p>
      ) : null}

      {chart && !chartError ? (
        <div
          style={{
            background: c.bg.surface,
            border: `1px solid ${c.border.default}`,
            borderRadius: r.lg,
            padding: s.s3,
          }}
        >
          {chart.title ? (
            <div
              style={{
                color: c.text.primary,
                fontSize: t.caption.fontSize,
                fontWeight: 600,
                marginBottom: 4,
              }}
            >
              {chart.title}
            </div>
          ) : null}
          <InsightChart spec={chart} />
          <FigureCaption chart={chart} />
        </div>
      ) : chartError ? (
        <div
          style={{
            background: c.bg.surface,
            border: `1px solid ${c.border.default}`,
            borderRadius: r.lg,
            padding: s.s3,
            color: c.text.caption,
            fontSize: t.meta.fontSize,
          }}
        >
          Chart unavailable; reasoning preserved.
          <div style={{ color: c.text.faint, marginTop: 4 }}>{chartError}</div>
        </div>
      ) : null}

      {body ? (
        <MarkdownRenderer
          content={body}
          style={{ color: c.text.body, fontSize: t.body.fontSize }}
        />
      ) : null}

      {visibleCitations.length > 0 ? (
        <CitationsRow citations={visibleCitations} />
      ) : null}

      <ProvenanceFooter
        dataSourcesUsed={dataSourcesUsed}
        skillsRun={skillsRun}
        confidence={confidence ?? "low"}
        materiality={materiality ?? "S"}
        generatedAt={generatedAt}
        model={model}
        sessionId={sessionId}
      />

      {showV2Affordances && insightId ? (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              type="button"
              onClick={() => setChatOpen((v) => !v)}
              aria-expanded={chatOpen}
              aria-controls={`insight-chat-${insightId}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                height: 32,
                padding: "0 12px",
                background: c.brand.tintDark,
                color: c.brand.primaryHover,
                border: `1px solid ${c.brand.primaryDeep}`,
                borderRadius: r.md,
                fontSize: t.body.fontSize,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              <MessageSquare size={14} aria-hidden="true" />
              {chatOpen ? "Close discussion" : "Discuss this insight"}
            </button>
            <SubscribeButton insightId={insightId} />
          </div>
          <div id={`insight-chat-${insightId}`}>
            <InsightChatDock
              insightId={insightId}
              insightHeadline={headline}
              isOpen={chatOpen}
              onClose={() => setChatOpen(false)}
            />
          </div>
        </>
      ) : null}
    </article>
  );
}

function FigureCaption({ chart }: { chart: ChartSpec }) {
  const ds = chart.data_source;
  const summary =
    ds.kind === "db_query"
      ? typeof ds.spec?.sql === "string"
        ? `db_query: ${truncate(ds.spec.sql as string, 64)}`
        : "db_query"
      : ds.kind === "router_call"
        ? typeof ds.spec?.endpoint === "string"
          ? `router_call: ${ds.spec.endpoint as string}`
          : "router_call"
        : "chart_data";
  return (
    <div
      style={{
        color: c.text.caption,
        fontSize: t.meta.fontSize,
        marginTop: 6,
      }}
    >
      Source: {summary} · n={ds.rows.toLocaleString()}
    </div>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function MaterialityChip({ level }: { level: Materiality }) {
  const palette =
    level === "L"
      ? { bg: c.brand.tintDark, border: c.brand.primary, text: c.brand.primaryHover }
      : level === "M"
        ? { bg: c.bg.card, border: c.border.strong, text: c.text.muted }
        : { bg: "transparent", border: c.border.default, text: c.text.caption };
  return (
    <span
      aria-label={`materiality: ${level === "L" ? "large" : level === "M" ? "medium" : "small"}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        height: 20,
        padding: "0 6px",
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        color: palette.text,
        borderRadius: r.sm,
        fontFamily: t.mono.fontFamily,
        fontSize: t.meta.fontSize,
      }}
    >
      {level}
    </span>
  );
}

function ConfidenceChip({ level }: { level: Confidence }) {
  const color =
    level === "high"
      ? c.semantic.success
      : level === "medium"
        ? c.semantic.warning
        : c.text.caption;
  return (
    <span
      aria-label={`confidence: ${level}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        height: 20,
        padding: "0 6px",
        background: "transparent",
        border: `1px solid ${color}44`,
        color: color,
        borderRadius: r.sm,
        fontSize: t.meta.fontSize,
      }}
    >
      conf: {level}
    </span>
  );
}

function LowSupportPill() {
  return (
    <span
      aria-label="low external support"
      title="Web search returned <2 supporting citations."
      style={{
        display: "inline-flex",
        alignItems: "center",
        height: 20,
        padding: "0 6px",
        background: "transparent",
        border: `1px solid ${c.semantic.warning}`,
        color: c.semantic.warning,
        borderRadius: r.sm,
        fontSize: t.meta.fontSize,
      }}
    >
      ! low external support
    </span>
  );
}
