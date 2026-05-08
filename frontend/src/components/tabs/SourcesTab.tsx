import { useApi } from "../../hooks/useApi";
import ErrorPanel from "../shared/ErrorPanel";
import CitationFooter from "../shared/CitationFooter";
import { ExternalLink } from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────

interface Pipeline {
  key: string;
  name: string;
  description: string;
  source_system: string;
  source_url: string;
  last_run_at: string | null;
  status: "ok" | "stale" | "error" | string;
  row_count: number;
}

interface SourceLink {
  pipeline: string;
  name: string;
  url: string;
}

interface Agent {
  name: string;
  description: string;
  used_by: string;
  model: string;
}

interface OverviewResponse {
  pipelines: Pipeline[];
  sources: SourceLink[];
  agents: Agent[];
}

// ── Theme ──────────────────────────────────────────────────────────────────

const CARD_STYLE: React.CSSProperties = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const TH_STYLE: React.CSSProperties = {
  color: "#64748b",
  textAlign: "left",
  padding: "8px 12px",
  fontWeight: 500,
  fontSize: 11,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  whiteSpace: "nowrap",
  borderBottom: "1px solid #334155",
};

const TD_STYLE: React.CSSProperties = {
  padding: "10px 12px",
  fontSize: 12,
  color: "#e2e8f0",
  borderBottom: "1px solid #1e293b",
  verticalAlign: "top",
};

const STATUS_PILL: Record<string, { bg: string; fg: string; label: string }> = {
  ok:    { bg: "#052e16", fg: "#4ade80", label: "ok" },
  stale: { bg: "#451a03", fg: "#fbbf24", label: "stale" },
  error: { bg: "#450a0a", fg: "#f87171", label: "error" },
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtTs(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mi = String(d.getUTCMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}Z`;
}

function StatusPill({ status }: { status: string }) {
  const cfg = STATUS_PILL[status] ?? STATUS_PILL.stale;
  return (
    <span
      style={{
        display: "inline-block",
        background: cfg.bg,
        color: cfg.fg,
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
      }}
    >
      {cfg.label}
    </span>
  );
}

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <h2 style={{ color: "white", fontSize: 16, fontWeight: 700, margin: 0 }}>{title}</h2>
      <p style={{ color: "#64748b", fontSize: 12, margin: "4px 0 0" }}>{subtitle}</p>
    </div>
  );
}

function ExtLink({ url, label }: { url: string; label?: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        color: "#60a5fa",
        textDecoration: "none",
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 12,
      }}
    >
      {label ?? url}
      <ExternalLink size={11} />
    </a>
  );
}

// ── Section: Pipelines ─────────────────────────────────────────────────────

function PipelinesTable({ rows }: { rows: Pipeline[] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={TH_STYLE}>Pipeline</th>
            <th style={TH_STYLE}>What it ingests</th>
            <th style={TH_STYLE}>Source system</th>
            <th style={TH_STYLE}>Last run (UTC)</th>
            <th style={TH_STYLE}>Status</th>
            <th style={{ ...TH_STYLE, textAlign: "right" }}>Rows</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.key}>
              <td style={{ ...TD_STYLE, fontWeight: 600, color: "white", whiteSpace: "nowrap" }}>
                {p.name}
              </td>
              <td style={{ ...TD_STYLE, color: "#cbd5e1", maxWidth: 480 }}>{p.description}</td>
              <td style={TD_STYLE}>
                <ExtLink url={p.source_url} label={p.source_system} />
              </td>
              <td style={{ ...TD_STYLE, color: "#94a3b8", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                {fmtTs(p.last_run_at)}
              </td>
              <td style={TD_STYLE}>
                <StatusPill status={p.status} />
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right", fontVariantNumeric: "tabular-nums", color: "#cbd5e1" }}>
                {p.row_count.toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Section: Sources per Pipeline ──────────────────────────────────────────

function SourcesTable({ pipelines, sources }: { pipelines: Pipeline[]; sources: SourceLink[] }) {
  // Map pipeline key -> human name for the left column.
  const pipelineLabel = new Map(pipelines.map((p) => [p.key, p.name]));
  // Group sources by pipeline key, preserving the order they appear in
  // the API response.
  const grouped = new Map<string, SourceLink[]>();
  for (const s of sources) {
    const arr = grouped.get(s.pipeline) ?? [];
    arr.push(s);
    grouped.set(s.pipeline, arr);
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={TH_STYLE}>Pipeline</th>
            <th style={TH_STYLE}>Source</th>
            <th style={TH_STYLE}>Link</th>
          </tr>
        </thead>
        <tbody>
          {Array.from(grouped.entries()).flatMap(([pipelineKey, items]) =>
            items.map((s, i) => (
              <tr key={`${pipelineKey}-${i}`}>
                <td
                  style={{
                    ...TD_STYLE,
                    color: i === 0 ? "white" : "#475569",
                    fontWeight: i === 0 ? 600 : 400,
                    whiteSpace: "nowrap",
                  }}
                >
                  {i === 0 ? (pipelineLabel.get(pipelineKey) ?? pipelineKey) : ""}
                </td>
                <td style={TD_STYLE}>{s.name}</td>
                <td style={TD_STYLE}>
                  <ExtLink url={s.url} />
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Section: Agents ────────────────────────────────────────────────────────

function AgentsTable({ rows }: { rows: Agent[] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={TH_STYLE}>Agent</th>
            <th style={TH_STYLE}>What it does</th>
            <th style={TH_STYLE}>Used by</th>
            <th style={TH_STYLE}>Model</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.name}>
              <td style={{ ...TD_STYLE, fontWeight: 600, color: "white", whiteSpace: "nowrap" }}>
                {a.name}
              </td>
              <td style={{ ...TD_STYLE, color: "#cbd5e1", maxWidth: 520 }}>{a.description}</td>
              <td style={{ ...TD_STYLE, color: "#94a3b8", whiteSpace: "nowrap" }}>{a.used_by}</td>
              <td style={{ ...TD_STYLE, color: "#94a3b8", fontFamily: "ui-monospace, SFMono-Regular, monospace", fontSize: 11 }}>
                {a.model}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main ───────────────────────────────────────────────────────────────────

export default function SourcesTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } =
    useApi<OverviewResponse>("/api/sources/overview");

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 400, color: "#3b82f6" }}>
        Loading data sources...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <ErrorPanel
          title={errorInfo?.title}
          message={errorInfo?.message}
          onRetry={retry}
          lastAttempt={lastFetchedAt}
        />
      </div>
    );
  }

  const pipelines = data?.pipelines ?? [];
  const sources = data?.sources ?? [];
  const agents = data?.agents ?? [];

  // Top KPI strip — keeps the user's quick reference of "what am I looking at".
  const okCount = pipelines.filter((p) => p.status === "ok").length;
  const totalRows = pipelines.reduce((s, p) => s + (p.row_count ?? 0), 0);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: 20 }}>
      {/* KPIs */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {[
          { label: "Ingestion Pipelines", value: String(pipelines.length) },
          { label: "Pipelines OK (< 7d)",  value: `${okCount} / ${pipelines.length}` },
          { label: "Underlying Sources",   value: String(sources.length) },
          { label: "Active Agents",        value: String(agents.length) },
          { label: "Total Rows Ingested",  value: totalRows.toLocaleString() },
        ].map(({ label, value }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, minWidth: 140 }}>
            <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 4 }}>{label}</div>
            <div style={{ color: "white", fontSize: 22, fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* (a) Ingestion Pipelines */}
      <div style={CARD_STYLE}>
        <SectionHeader
          title="Ingestion Pipelines"
          subtitle="One row per real pipeline. Status reflects the latest run: ok = ran in the last 7 days, stale = older, error = last run failed."
        />
        <PipelinesTable rows={pipelines} />
      </div>

      {/* (b) Data Sources per Pipeline */}
      <div style={CARD_STYLE}>
        <SectionHeader
          title="Data Sources per Pipeline"
          subtitle="The underlying source systems each pipeline pulls from. Every link opens the source's public homepage or API."
        />
        <SourcesTable pipelines={pipelines} sources={sources} />
      </div>

      {/* (c) Agents */}
      <div style={CARD_STYLE}>
        <SectionHeader
          title="Agents"
          subtitle="LLM and analytic agents that run on top of the ingested data. Pruned from 28 raw scheduler/adapter rows down to 8 distinct agents."
        />
        <AgentsTable rows={agents} />
      </div>

      <CitationFooter
        sources={["ingestion_runs + curated registry"]}
        retrievedAt={lineage?.retrieved_at}
        confidence={lineage?.confidence}
        sourceUrl={lineage?.source_url}
      />
    </div>
  );
}
