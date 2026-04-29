import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  LineChart, Line, ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { TSMCResponse } from "../../types";
import { AlertTriangle, CheckCircle } from "lucide-react";
import ErrorPanel from "../shared/ErrorPanel";
import NoDataPanel from "../shared/NoDataPanel";
import CitationFooter from "../shared/CitationFooter";

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

export default function TSMCTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } = useApi<TSMCResponse>("/api/tsmc");

  if (loading) return <Loader />;

  if (error) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} lastAttempt={lastFetchedAt} />
      </div>
    );
  }

  const capacity = data?.capacity ?? [];
  const packaging = data?.packaging ?? [];

  const hasData = capacity.length > 0 || packaging.length > 0;

  if (!hasData) {
    return (
      <div style={{ padding: "24px" }}>
        <NoDataPanel pillar="TSMC" reason="TSMC wafer production and CoWoS packaging data will be integrated in Phase 2. This will track upstream supply constraints for AI accelerators." />
      </div>
    );
  }

  const latest = capacity[capacity.length - 1];
  const constrainedQuarters = packaging.filter((p) => p.constraint_flag).length;

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* KPIs */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {[
          { label: "3nm Wafer Starts (Q4 2024)", value: (latest?.node_3nm_wafers ?? 0).toLocaleString(), unit: "wafers/qtr", color: "#3b82f6" },
          { label: "5nm Wafer Starts (Q4 2024)", value: (latest?.node_5nm_wafers ?? 0).toLocaleString(), unit: "wafers/qtr", color: "#06b6d4" },
          { label: "Fab Utilization", value: `${latest?.utilization_pct ?? 0}%`, unit: "", color: (latest?.utilization_pct ?? 0) > 90 ? "#f59e0b" : "#22c55e" },
          { label: "CoWoS Constraint Quarters", value: String(constrainedQuarters), unit: "/ 8 quarters", color: constrainedQuarters > 3 ? "#ef4444" : "#22c55e" },
        ].map(({ label, value, unit, color }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, minWidth: 150 }}>
            <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{label}</div>
            <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>
              {value}<span style={{ color: "#64748b", fontSize: "11px", marginLeft: "4px" }}>{unit}</span>
            </div>
            <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: color, marginTop: "6px" }} />
          </div>
        ))}
      </div>

      {/* Wafer capacity by node */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          TSMC Wafer Capacity by Node (3nm vs 5nm)
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          AI accelerator supply constraint upstream -- TSMC Financial Reports
        </p>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={capacity}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="quarter" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              formatter={(v) => Number(v).toLocaleString()}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
            <Bar dataKey="node_3nm_wafers" name="3nm Wafers" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            <Bar dataKey="node_5nm_wafers" name="5nm Wafers" fill="#06b6d4" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <CitationFooter
          sources={["TSMC Financial Reports"]}
          retrievedAt={lineage?.retrieved_at}
          confidence={lineage?.confidence}
          sourceUrl={lineage?.source_url}
        />
      </div>

      {/* Utilization line */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          Fab Utilization Rate
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          High utilization (&gt; 90%) signals supply tightness and potential GPU shipment delays
        </p>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={capacity}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="quarter" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis domain={[50, 100]} tick={{ fill: "#94a3b8", fontSize: 11 }} unit="%" />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              formatter={(v) => `${v}%`}
            />
            <Line type="monotone" dataKey="utilization_pct" name="Utilization" stroke="#f59e0b" strokeWidth={2} dot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
        <CitationFooter
          sources={["TSMC Financial Reports"]}
          retrievedAt={lineage?.retrieved_at}
          confidence={lineage?.confidence}
          sourceUrl={lineage?.source_url}
        />
      </div>

      {/* CoWoS packaging constraints */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 12px" }}>
          CoWoS Advanced Packaging -- Constraint Signals
        </h3>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          {packaging.map((p, i) => (
            <div key={i} style={{
              background: "#0f172a",
              border: `1px solid ${p.constraint_flag ? "#ef4444" : "#22c55e"}`,
              borderRadius: "8px",
              padding: "10px 14px",
              minWidth: "130px",
            }}>
              <div style={{ color: "#94a3b8", fontSize: "11px" }}>{p.quarter}</div>
              <div style={{ color: "white", fontSize: "14px", fontWeight: 600, margin: "4px 0" }}>
                {(p.cowos_capacity).toLocaleString()} <span style={{ color: "#64748b", fontSize: "10px" }}>units</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                {p.constraint_flag
                  ? <><AlertTriangle size={12} color="#ef4444" /><span style={{ color: "#ef4444", fontSize: "11px" }}>Constrained</span></>
                  : <><CheckCircle size={12} color="#22c55e" /><span style={{ color: "#22c55e", fontSize: "11px" }}>Normal</span></>
                }
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading...</div>;
}
