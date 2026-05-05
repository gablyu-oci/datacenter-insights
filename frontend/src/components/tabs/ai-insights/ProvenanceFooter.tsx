import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import { SourcePill } from "../../agentchat";
import type { Confidence, Materiality } from "../../../types/sseEvents";

/**
 * ProvenanceFooter — per UX U3.5 (PRD §5.6).
 *
 * Collapsed by default; one-line summary. Expand reveals the full 7 fields:
 *   data sources used, skills run, confidence, materiality, generated_at,
 *   model, session_id.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

export interface DataSourceUsed {
  kind: "db_query" | "router_call" | "chart_data";
  /** Human-readable summary, e.g. "curated_deals" or "/api/triangulation/l2". */
  label: string;
  rows: number;
  fetched_at?: string;
  url?: string | null;
}

export interface ProvenanceFooterProps {
  dataSourcesUsed: DataSourceUsed[];
  skillsRun: string[];
  confidence: Confidence;
  materiality: Materiality;
  generatedAt: string; // ISO8601
  model: string;
  sessionId: string;
  defaultOpen?: boolean;
}

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  low: "low",
  medium: "medium",
  high: "high",
};

const MATERIALITY_LABEL: Record<Materiality, string> = {
  S: "small",
  M: "medium",
  L: "large",
};

export default function ProvenanceFooter({
  dataSourcesUsed,
  skillsRun,
  confidence,
  materiality,
  generatedAt,
  model,
  sessionId,
  defaultOpen = false,
}: ProvenanceFooterProps) {
  const [open, setOpen] = useState(defaultOpen);
  const sessionShort = sessionId.length > 8 ? `${sessionId.slice(0, 4)}-${sessionId.slice(4, 8)}…` : sessionId;
  const generatedShort = generatedAt ? formatTime(generatedAt) : "";

  return (
    <div
      style={{
        marginTop: s.s4,
        paddingTop: s.s3,
        borderTop: `1px solid ${c.border.weak}`,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          color: c.text.caption,
          fontSize: t.meta.fontSize,
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontFamily: "inherit",
        }}
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        Provenance:&nbsp;
        <span style={{ color: c.text.muted }}>
          {dataSourcesUsed.length} source{dataSourcesUsed.length === 1 ? "" : "s"} ·{" "}
          {skillsRun.length} skill{skillsRun.length === 1 ? "" : "s"} · {model} · session {sessionShort} · {generatedShort}
        </span>
      </button>
      {open ? (
        <div
          style={{
            marginTop: s.s3,
            display: "flex",
            flexDirection: "column",
            gap: s.s3,
            color: c.text.muted,
            fontSize: t.meta.fontSize,
          }}
        >
          <Section label="Data sources used">
            <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 2 }}>
              {dataSourcesUsed.length === 0 ? (
                <li style={{ color: c.text.faint }}>none</li>
              ) : (
                dataSourcesUsed.map((d, i) => (
                  <li key={i}>
                    <span style={{ color: c.text.faint }}>{d.kind}</span>{" "}
                    <span style={{ color: c.text.muted }}>· {d.label}</span>{" "}
                    <span style={{ color: c.text.faint }}>
                      · {d.rows.toLocaleString()} rows
                      {d.fetched_at ? ` · ${formatTime(d.fetched_at)}` : ""}
                    </span>
                    {d.url ? (
                      <>
                        {" "}
                        <a
                          href={d.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          style={{ color: c.brand.primaryHover }}
                        >
                          link
                        </a>
                      </>
                    ) : null}
                  </li>
                ))
              )}
            </ul>
          </Section>

          <Section label="Skills used">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {skillsRun.length === 0 ? (
                <span style={{ color: c.text.faint }}>none</span>
              ) : (
                skillsRun.map((sk) => <SourcePill key={sk} label={sk} />)
              )}
            </div>
          </Section>

          <Section label="Confidence">
            <span style={{ color: c.text.muted }}>{CONFIDENCE_LABEL[confidence]}</span>
          </Section>
          <Section label="Materiality">
            <span style={{ color: c.text.muted }}>{MATERIALITY_LABEL[materiality]}</span>
          </Section>
          <Section label="Generated">
            <span style={{ color: c.text.muted }}>{generatedAt}</span>
          </Section>
          <Section label="Model">
            <span style={{ color: c.text.muted, fontFamily: t.mono.fontFamily }}>{model}</span>
          </Section>
          <Section label="Session">
            <span style={{ color: c.text.muted, fontFamily: t.mono.fontFamily }}>{sessionId}</span>
          </Section>

          <div
            style={{
              padding: `${s.s2}px ${s.s3}px`,
              background: c.bg.surface,
              border: `1px solid ${c.border.default}`,
              borderRadius: r.md,
              color: c.text.faint,
              fontSize: t.meta.fontSize,
            }}
          >
            AI-generated. Treat as analysis, not fact.
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <div
        style={{
          color: c.text.deepest,
          fontSize: t.micro.fontSize,
          fontWeight: t.micro.fontWeight,
          letterSpacing: t.micro.letterSpacing,
          textTransform: t.micro.textTransform,
          width: 110,
          flexShrink: 0,
          paddingTop: 1,
        }}
      >
        {label}
      </div>
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
  } catch {
    return iso;
  }
}
