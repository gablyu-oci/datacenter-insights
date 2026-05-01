import { useState } from "react";
import { useApi } from "../../hooks/useApi";
import type { SourceRecord, AgentStatus } from "../../types";
import { ExternalLink, Activity, CheckCircle, Clock, Grid3X3 } from "lucide-react";
import ErrorPanel from "../shared/ErrorPanel";
import CitationFooter from "../shared/CitationFooter";

interface SourcesResponse { sources: SourceRecord[]; agents: AgentStatus[]; }

interface CoverageRow {
  pillar: string;
  state_code: string;
  source: string | null;
  coverage_status: string;
  last_ingested_at: string | null;
  missing_reason: string | null;
  notes: string | null;
  roadmap: string | null;
  record_count: number;
}

interface CoverageResponse {
  data: CoverageRow[];
  total: number;
}

const PILLAR_COLORS: Record<string, string> = {
  Power: "#3b82f6",
  "GPU Supply": "#f59e0b",
  TSMC: "#8b5cf6",
  Permits: "#22c55e",
  Satellite: "#06b6d4",
  "NICs & Optics": "#ec4899",
  "Power / GPU": "#6366f1",
  sites: "#3b82f6",
  companies: "#f59e0b",
  events: "#22c55e",
  energy_projects: "#06b6d4",
  permits: "#ec4899",
  power_announcements: "#8b5cf6",
};

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const STATUS_CELL_COLORS: Record<string, { bg: string; text: string }> = {
  full: { bg: "#052e16", text: "#4ade80" },
  complete: { bg: "#052e16", text: "#4ade80" },
  partial: { bg: "#451a03", text: "#fbbf24" },
  federal_baseline: { bg: "#451a03", text: "#fbbf24" },
  pending: { bg: "#1f2937", text: "#9ca3af" },
  unavailable: { bg: "#450a0a", text: "#f87171" },
  none: { bg: "#450a0a", text: "#f87171" },
  empty: { bg: "#450a0a", text: "#f87171" },
};

function CoverageMatrix() {
  const { data: covData, loading: covLoading, error: covError, errorInfo: covErrorInfo, retry: covRetry, lineage: covLineage } = useApi<CoverageResponse | CoverageRow[]>("/api/coverage/");

  if (covLoading) {
    return <div style={{ color: "#3b82f6", textAlign: "center", padding: "40px 0" }}>Loading coverage matrix...</div>;
  }

  if (covError) {
    return <ErrorPanel title={covErrorInfo?.title} message={covErrorInfo?.message} onRetry={covRetry} variant="inline" />;
  }

  // Handle both array and {data: [...]} shapes
  const rows: CoverageRow[] = Array.isArray(covData) ? covData : (covData?.data ?? []);

  if (rows.length === 0) {
    return (
      <div style={{ color: "#64748b", textAlign: "center", padding: "40px 0" }}>
        No coverage data available yet.
      </div>
    );
  }

  // Build pillar x state matrix
  const pillars = Array.from(new Set(rows.map(r => r.pillar))).sort();
  const states = Array.from(new Set(rows.map(r => r.state_code))).sort();

  // Create lookup
  const lookup = new Map<string, CoverageRow>();
  rows.forEach(r => lookup.set(`${r.pillar}:${r.state_code}`, r));

  return (
    <div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155" }}>
              <th style={{ color: "#64748b", textAlign: "left", padding: "6px 8px", fontWeight: 500, position: "sticky", left: 0, background: "#1e293b", zIndex: 1, minWidth: 100 }}>
                Pillar / State
              </th>
              {states.map(s => (
                <th key={s} style={{ color: "#94a3b8", textAlign: "center", padding: "6px 4px", fontWeight: 500, minWidth: 36 }}>
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pillars.map(pillar => (
              <tr key={pillar} style={{ borderBottom: "1px solid #1e293b" }}>
                <td style={{
                  padding: "6px 8px",
                  color: PILLAR_COLORS[pillar] ?? "#94a3b8",
                  fontWeight: 600,
                  fontSize: "10px",
                  position: "sticky",
                  left: 0,
                  background: "#1e293b",
                  zIndex: 1,
                }}>
                  {pillar}
                </td>
                {states.map(state => {
                  const row = lookup.get(`${pillar}:${state}`);
                  const status = (row?.coverage_status ?? "none").toLowerCase();
                  const cellColors = STATUS_CELL_COLORS[status] ?? STATUS_CELL_COLORS.none;
                  return (
                    <td
                      key={state}
                      title={row?.missing_reason ? `Missing: ${row.missing_reason}` : `${row?.record_count ?? 0} records`}
                      style={{
                        padding: "4px",
                        textAlign: "center",
                      }}
                    >
                      <div style={{
                        background: cellColors.bg,
                        color: cellColors.text,
                        borderRadius: "3px",
                        padding: "2px 0",
                        fontSize: "9px",
                        fontWeight: 600,
                        cursor: "default",
                      }}>
                        {row?.record_count ?? 0}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: "16px", marginTop: "12px", flexWrap: "wrap" }}>
        {[
          { label: "Full Coverage", color: "#4ade80", bg: "#052e16" },
          { label: "Partial Coverage", color: "#fbbf24", bg: "#451a03" },
          { label: "No Coverage", color: "#f87171", bg: "#450a0a" },
        ].map(({ label, color, bg }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <div style={{ width: 12, height: 12, borderRadius: "3px", background: bg, border: `1px solid ${color}44` }} />
            <span style={{ color: "#64748b", fontSize: "10px" }}>{label}</span>
          </div>
        ))}
      </div>

      {/* Per-pillar grouped breakdown */}
      <div style={{ marginTop: 24 }}>
        <h4 style={{ color: "white", fontWeight: 600, fontSize: 13, margin: "0 0 10px" }}>
          Coverage by Pillar
        </h4>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {pillars.map(pillar => {
            const pillarRows = rows.filter(r => r.pillar === pillar);
            const missing = pillarRows.filter(r => {
              const s = (r.coverage_status ?? "").toLowerCase();
              return s !== "full" && s !== "complete";
            });
            return (
              <PillarSection key={pillar} pillar={pillar} rows={pillarRows} missing={missing} />
            );
          })}
        </div>
      </div>

      <CitationFooter
        sources={["Data Coverage Matrix"]}
        retrievedAt={covLineage?.retrieved_at}
        confidence={covLineage?.confidence}
        sourceUrl={covLineage?.source_url}
      />
    </div>
  );
}

function PillarSection({ pillar, rows, missing }: { pillar: string; rows: CoverageRow[]; missing: CoverageRow[] }) {
  const [open, setOpen] = useState(false);
  const color = PILLAR_COLORS[pillar] ?? "#94a3b8";
  const fullCount = rows.filter(r => {
    const s = (r.coverage_status ?? "").toLowerCase();
    return s === "full" || s === "complete";
  }).length;
  return (
    <div style={{
      background: "#0f172a",
      border: "1px solid #1e293b",
      borderLeft: `3px solid ${color}`,
      borderRadius: 8,
      overflow: "hidden",
    }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          width: "100%",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "10px 14px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          color: "inherit",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color, fontSize: 13, fontWeight: 700 }}>{pillar}</span>
          <span style={{ color: "#64748b", fontSize: 11 }}>{rows.length} rows</span>
          <span style={{ color: "#4ade80", fontSize: 10 }}>{fullCount} full</span>
          {missing.length > 0 && (
            <span style={{ color: "#fbbf24", fontSize: 10 }}>{missing.length} not full</span>
          )}
        </div>
        <span style={{ color: "#64748b", fontSize: 11 }}>{open ? "Hide" : "Show"}</span>
      </button>

      {open && (
        <div style={{ padding: "0 14px 14px" }}>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #1e293b" }}>
                  {["State", "Source", "Status", "Records", "Last Ingested", "Notes / Roadmap"].map(h => (
                    <th key={h} style={{ color: "#64748b", textAlign: "left", padding: "6px 8px", fontWeight: 500 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const status = (r.coverage_status ?? "none").toLowerCase();
                  const cellColors = STATUS_CELL_COLORS[status] ?? STATUS_CELL_COLORS.none;
                  return (
                    <tr key={`${r.pillar}-${r.state_code}-${i}`} style={{ borderBottom: "1px solid #1e293b" }}>
                      <td style={{ padding: "6px 8px", color: "#e2e8f0", fontWeight: 600 }}>{r.state_code}</td>
                      <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{r.source ?? "--"}</td>
                      <td style={{ padding: "6px 8px" }}>
                        <span style={{
                          padding: "1px 7px",
                          borderRadius: 3,
                          background: cellColors.bg,
                          color: cellColors.text,
                          fontSize: 10,
                          fontWeight: 600,
                        }}>
                          {r.coverage_status ?? "none"}
                        </span>
                      </td>
                      <td style={{ padding: "6px 8px", color: "#cbd5e1" }}>{r.record_count?.toLocaleString() ?? 0}</td>
                      <td style={{ padding: "6px 8px", color: "#64748b" }}>
                        {r.last_ingested_at ? r.last_ingested_at.split("T")[0] : "--"}
                      </td>
                      <td style={{ padding: "6px 8px", color: "#94a3b8" }}>
                        {r.notes || r.roadmap || r.missing_reason || "--"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* What's missing and why */}
          {missing.length > 0 && (
            <div style={{ marginTop: 12, background: "#1e1208", border: "1px solid #422006", borderRadius: 6, padding: "10px 12px" }}>
              <div style={{ color: "#fbbf24", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
                What's missing and why ({missing.length})
              </div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <tbody>
                  {missing.map((m, i) => (
                    <tr key={`miss-${i}`}>
                      <td style={{ padding: "3px 6px", color: "#fcd34d", fontWeight: 600, width: 50 }}>{m.state_code}</td>
                      <td style={{ padding: "3px 6px", color: "#fcd34d", fontSize: 10 }}>{m.coverage_status}</td>
                      <td style={{ padding: "3px 6px", color: "#fde68a" }}>
                        {m.missing_reason || m.notes || m.roadmap || "no detail"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SourcesTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } = useApi<SourcesResponse>("/api/sources");
  const [showMatrix, setShowMatrix] = useState(false);

  if (loading) return <Loader />;

  if (error) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} lastAttempt={lastFetchedAt} />
      </div>
    );
  }

  const sources = data?.sources ?? [];
  const agents = data?.agents ?? [];

  // The backend doesn't expose per-source confidence today; fall back to
  // total_records_stored for the summary tile.
  const totalRecords = sources.reduce(
    (s, r) => s + (r.total_records_stored ?? r.records ?? 0),
    0,
  );
  const sourcesWithRunData = sources.filter(r => (r.run_count ?? 0) > 0).length;

  // Map source-name -> total_records_stored so per-agent cards can show
  // a useful "records" count even though /api/sources/ doesn't put it on
  // the agent rows directly. Source rows can repeat the same name across
  // multiple versions (epa_echo v1.0/v1.1/v1.2), so SUM by name.
  const recordsByAgentName = sources.reduce<Map<string, number>>((acc, r) => {
    acc.set(r.name, (acc.get(r.name) ?? 0) + (r.total_records_stored ?? 0));
    return acc;
  }, new Map<string, number>());

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Summary KPIs */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {[
          { label: "Data Sources", value: String(sources.length) },
          { label: "Total Records Ingested", value: totalRecords.toLocaleString() },
          { label: "Active Agents", value: String(agents.filter((a) => a.status === "active").length) },
          { label: "Sources with Run Data", value: `${sourcesWithRunData}/${sources.length}` },
        ].map(({ label, value }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, minWidth: 140 }}>
            <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{label}</div>
            <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Coverage Matrix Section */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: showMatrix ? "16px" : 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Grid3X3 size={16} color="#3b82f6" />
            <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
              Data Coverage Matrix
            </h3>
          </div>
          <button
            onClick={() => setShowMatrix(v => !v)}
            style={{
              background: showMatrix ? "#1e293b" : "#0f172a",
              border: "1px solid #334155",
              borderRadius: "6px",
              color: "#94a3b8",
              padding: "6px 12px",
              cursor: "pointer",
              fontSize: "12px",
            }}
          >
            {showMatrix ? "Hide Matrix" : "Show Matrix"}
          </button>
        </div>
        {showMatrix && <CoverageMatrix />}
      </div>

      {/* Agent status */}
      {agents.length > 0 && (
        <div style={CARD_STYLE}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "14px" }}>
            <Activity size={16} color="#3b82f6" />
            <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
              Agent Pipeline Status
            </h3>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "10px" }}>
            {agents.map((a, i) => (
              <div key={i} style={{
                background: "#0f172a",
                borderRadius: "8px",
                padding: "12px 14px",
                border: `1px solid ${a.status === "active" ? "#22c55e44" : "#33415544"}`,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ color: "white", fontSize: "13px", fontWeight: 500 }}>{a.name ?? a.agent ?? "(unnamed)"}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    {a.status === "active"
                      ? <CheckCircle size={12} color="#22c55e" />
                      : <Clock size={12} color="#94a3b8" />
                    }
                    <span style={{ color: a.status === "active" ? "#22c55e" : "#94a3b8", fontSize: "11px" }}>
                      {a.status}
                    </span>
                  </div>
                </div>
                <div style={{ display: "flex", gap: "16px", marginTop: "8px" }}>
                  <div>
                    <div style={{ color: "#64748b", fontSize: "10px" }}>Records</div>
                    <div style={{ color: "#e2e8f0", fontSize: "12px" }}>
                      {(a.records_processed ?? recordsByAgentName.get(a.name ?? "") ?? 0).toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: "#64748b", fontSize: "10px" }}>Last Run</div>
                    <div style={{ color: "#e2e8f0", fontSize: "11px" }}>
                      {a.last_run ? a.last_run.split("T")[0] : "--"}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Source records */}
      {sources.length > 0 && (
        <div style={CARD_STYLE}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 16px" }}>
            Data Sources & Lineage
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {sources.map((s) => {
              const records = s.total_records_stored ?? s.records ?? 0;
              const lastRun = s.last_run_at ?? s.last_ingested ?? null;
              const lastRunStr = lastRun ? lastRun.split("T")[0] : "--";
              const runCount = s.run_count ?? null;
              return (
                <div key={`${s.name}@${s.version ?? "unversioned"}`} style={{
                  background: "#0f172a",
                  borderRadius: "8px",
                  padding: "14px 16px",
                  border: "1px solid #1e293b",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  flexWrap: "wrap",
                  gap: "12px",
                }}>
                  <div style={{ flex: 1, minWidth: 250 }}>
                    {s.version && (
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", fontSize: "10px" }}>v{s.version}</span>
                      </div>
                    )}
                    <div style={{ color: "white", fontSize: "14px", fontWeight: 600 }}>{s.name}</div>
                    {s.description && (
                      <div style={{ color: "#94a3b8", fontSize: "12px", marginTop: "2px" }}>{s.description}</div>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: "20px", alignItems: "flex-start", flexWrap: "wrap" }}>
                    <div>
                      <div style={{ color: "#64748b", fontSize: "10px" }}>Records</div>
                      <div style={{ color: "#e2e8f0", fontSize: "13px" }}>{records.toLocaleString()}</div>
                    </div>
                    <div>
                      <div style={{ color: "#64748b", fontSize: "10px" }}>Last Run</div>
                      <div style={{ color: "#e2e8f0", fontSize: "13px" }}>{lastRunStr}</div>
                    </div>
                    {runCount != null && (
                      <div>
                        <div style={{ color: "#64748b", fontSize: "10px" }}>Run Count</div>
                        <div style={{ color: "#e2e8f0", fontSize: "13px" }}>{runCount.toLocaleString()}</div>
                      </div>
                    )}
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noreferrer"
                        style={{ color: "#3b82f6", display: "flex", alignItems: "center", gap: "4px", textDecoration: "none", fontSize: "12px", marginTop: "12px" }}>
                        <ExternalLink size={12} />
                        View Source
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <CitationFooter
            sources={["Internal Data Pipeline"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={lineage?.source_url}
          />
        </div>
      )}

      {/* Explainability notice */}
      <div style={{
        ...CARD_STYLE,
        background: "#0f172a",
        borderLeft: "3px solid #3b82f6",
        padding: "14px 20px",
      }}>
        <div style={{ color: "#94a3b8", fontSize: "12px", lineHeight: "1.6" }}>
          <strong style={{ color: "white" }}>Data Traceability Policy:</strong> Every metric in this platform is traceable to a primary source via the Explainability Agent.
          All outputs include citation metadata, source confidence levels, and versioned data lineage.
          Assumptions used in derived metrics (e.g., revenue-to-unit inference, power-per-GPU estimates) are documented with transparent methodologies.
        </div>
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading...</div>;
}
