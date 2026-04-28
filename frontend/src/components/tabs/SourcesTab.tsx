import { useApi } from "../../hooks/useApi";
import type { SourceRecord, AgentStatus } from "../../types";
import { ExternalLink, Activity, CheckCircle, Clock } from "lucide-react";

interface SourcesResponse { sources: SourceRecord[]; agents: AgentStatus[]; }

const PILLAR_COLORS: Record<string, string> = {
  Power: "#3b82f6",
  "GPU Supply": "#f59e0b",
  TSMC: "#8b5cf6",
  Permits: "#22c55e",
  Satellite: "#06b6d4",
  "NICs & Optics": "#ec4899",
  "Power / GPU": "#6366f1",
};

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

export default function SourcesTab() {
  const { data, loading } = useApi<SourcesResponse>("/api/sources");

  if (loading) return <Loader />;

  const sources = data?.sources ?? [];
  const agents = data?.agents ?? [];

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Summary KPIs */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {[
          { label: "Data Sources", value: String(sources.length) },
          { label: "Total Records Ingested", value: sources.reduce((s, r) => s + r.records, 0).toLocaleString() },
          { label: "Active Agents", value: String(agents.filter((a) => a.status === "active").length) },
          { label: "Avg Source Confidence", value: `${(sources.reduce((s, r) => s + r.confidence, 0) / sources.length * 100).toFixed(0)}%` },
        ].map(({ label, value }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, minWidth: 140 }}>
            <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{label}</div>
            <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Agent status */}
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
                <div style={{ color: "white", fontSize: "13px", fontWeight: 500 }}>{a.agent}</div>
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
                  <div style={{ color: "#e2e8f0", fontSize: "12px" }}>{a.records_processed.toLocaleString()}</div>
                </div>
                <div>
                  <div style={{ color: "#64748b", fontSize: "10px" }}>Last Run</div>
                  <div style={{ color: "#e2e8f0", fontSize: "11px" }}>{a.last_run.split("T")[0]}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Source records */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 16px" }}>
          Data Sources & Lineage
        </h3>
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          {sources.map((s) => (
            <div key={s.id} style={{
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
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                  <span style={{
                    background: `${PILLAR_COLORS[s.pillar] ?? "#64748b"}22`,
                    color: PILLAR_COLORS[s.pillar] ?? "#94a3b8",
                    fontSize: "10px",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    fontWeight: 600,
                  }}>
                    {s.pillar}
                  </span>
                  <span style={{ color: "#64748b", fontSize: "10px" }}>{s.type}</span>
                </div>
                <div style={{ color: "white", fontSize: "14px", fontWeight: 600 }}>{s.name}</div>
                <div style={{ color: "#94a3b8", fontSize: "12px", marginTop: "2px" }}>{s.description}</div>
              </div>
              <div style={{ display: "flex", gap: "20px", alignItems: "flex-start", flexWrap: "wrap" }}>
                <div>
                  <div style={{ color: "#64748b", fontSize: "10px" }}>Records</div>
                  <div style={{ color: "#e2e8f0", fontSize: "13px" }}>{s.records.toLocaleString()}</div>
                </div>
                <div>
                  <div style={{ color: "#64748b", fontSize: "10px" }}>Last Ingested</div>
                  <div style={{ color: "#e2e8f0", fontSize: "13px" }}>{s.last_ingested}</div>
                </div>
                <div>
                  <div style={{ color: "#64748b", fontSize: "10px" }}>Confidence</div>
                  <div style={{ color: "#e2e8f0", fontSize: "13px" }}>{(s.confidence * 100).toFixed(0)}%</div>
                  <div style={{ background: "#1e293b", borderRadius: "4px", height: "3px", width: "60px", marginTop: "2px" }}>
                    <div style={{ background: "#3b82f6", borderRadius: "4px", height: "3px", width: `${s.confidence * 100}%` }} />
                  </div>
                </div>
                <a href={s.url} target="_blank" rel="noreferrer"
                  style={{ color: "#3b82f6", display: "flex", alignItems: "center", gap: "4px", textDecoration: "none", fontSize: "12px", marginTop: "12px" }}>
                  <ExternalLink size={12} />
                  View Source
                </a>
              </div>
            </div>
          ))}
        </div>
      </div>

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
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading…</div>;
}
