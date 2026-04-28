import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { TriangulationRecord } from "../../types";
import { AlertTriangle, CheckCircle, TrendingDown, Info } from "lucide-react";

interface TriangResponse { data: TriangulationRecord[]; }

const STATUS_CONFIG = {
  Overbuild: { color: "#f59e0b", icon: <AlertTriangle size={14} color="#f59e0b" />, bg: "#f59e0b22" },
  Constrained: { color: "#ef4444", icon: <TrendingDown size={14} color="#ef4444" />, bg: "#ef444422" },
  Balanced: { color: "#22c55e", icon: <CheckCircle size={14} color="#22c55e" />, bg: "#22c55e22" },
};

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const LAYERS = [
  { layer: "L1", label: "Contracted Power", desc: "GW signed with utilities" },
  { layer: "L2", label: "GPU Compute Demand", desc: "Power draw × utilization" },
  { layer: "L3", label: "NIC/Optics Signals", desc: "Deployment validation" },
  { layer: "L4", label: "Permit Ground Truth", desc: "County construction data" },
];

export default function TriangulationTab() {
  const { data, loading } = useApi<TriangResponse>("/api/triangulation");

  if (loading) return <Loader />;

  const records = data?.data ?? [];

  const powerGapData = records.map((r) => ({
    region: r.region,
    "Contracted GW": r.contracted_power_gw,
    "GPU Demand GW": r.gpu_power_demand_gw,
    "Gap GW": r.power_gap_gw,
  }));

  const radarData = records.map((r) => ({
    region: r.region,
    "Power": +(r.contracted_power_gw * 10).toFixed(0),
    "GPU Density": r.deployed_gpus_k,
    "NIC Signal": +(r.nic_validation_score * 100).toFixed(0),
    "Permits": r.permit_signal_count * 5,
    "Confidence": +(r.confidence * 100).toFixed(0),
  }));

  const overbuildCount = records.filter((r) => r.status === "Overbuild").length;
  const constrainedCount = records.filter((r) => r.status === "Constrained").length;
  const balancedCount = records.filter((r) => r.status === "Balanced").length;

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Model layers explanation */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
          <Info size={16} color="#3b82f6" />
          <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
            Multi-Layer Triangulation Model
          </h3>
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          {LAYERS.map(({ layer, label, desc }) => (
            <div key={layer} style={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: "8px",
              padding: "12px 16px",
              flex: 1,
              minWidth: 160,
            }}>
              <div style={{ color: "#3b82f6", fontSize: "11px", fontWeight: 700, marginBottom: "4px" }}>{layer}</div>
              <div style={{ color: "white", fontSize: "13px", fontWeight: 600 }}>{label}</div>
              <div style={{ color: "#64748b", fontSize: "11px", marginTop: "2px" }}>{desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Status summary */}
      <div style={{ display: "flex", gap: "16px" }}>
        {[
          { label: "Overbuild Regions", value: overbuildCount, ...STATUS_CONFIG.Overbuild },
          { label: "Constrained Regions", value: constrainedCount, ...STATUS_CONFIG.Constrained },
          { label: "Balanced Regions", value: balancedCount, ...STATUS_CONFIG.Balanced },
        ].map(({ label, value, color, icon, bg }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, background: bg, border: `1px solid ${color}44` }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
              {icon}
              <span style={{ color: "#94a3b8", fontSize: "12px" }}>{label}</span>
            </div>
            <div style={{ color, fontSize: "36px", fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Power gap bar chart */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          Power Gap Analysis — Contracted vs GPU Demand (GW)
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          Positive gap = excess capacity · Negative gap = compute constrained
        </p>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={powerGapData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="region" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} unit=" GW" />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              formatter={(v: number) => `${v} GW`}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
            <Bar dataKey="Contracted GW" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            <Bar dataKey="GPU Demand GW" fill="#ef4444" radius={[4, 4, 0, 0]} />
            <Bar dataKey="Gap GW" fill="#22c55e" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Detail cards per region */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "12px" }}>
        {records.map((r, i) => {
          const cfg = STATUS_CONFIG[r.status] ?? STATUS_CONFIG.Balanced;
          return (
            <div key={i} style={{
              ...CARD_STYLE,
              borderLeft: `3px solid ${cfg.color}`,
              padding: "14px 16px",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                <div style={{ color: "white", fontWeight: 600, fontSize: "14px" }}>{r.region}</div>
                <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                  {cfg.icon}
                  <span style={{ color: cfg.color, fontSize: "11px" }}>{r.status}</span>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "10px" }}>
                {[
                  ["Contracted", `${r.contracted_power_gw} GW`],
                  ["GPU Demand", `${r.gpu_power_demand_gw} GW`],
                  ["Deployed GPUs", `${r.deployed_gpus_k}k`],
                  ["Power Gap", `${r.power_gap_gw} GW`],
                  ["NIC Score", `${(r.nic_validation_score * 100).toFixed(0)}%`],
                  ["Permit Signals", String(r.permit_signal_count)],
                ].map(([k, v]) => (
                  <div key={k}>
                    <div style={{ color: "#64748b", fontSize: "10px" }}>{k}</div>
                    <div style={{ color: "#e2e8f0", fontSize: "13px", fontWeight: 500 }}>{v}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b", fontSize: "11px" }}>Confidence</span>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <div style={{ background: "#0f172a", borderRadius: "4px", height: "4px", width: "80px" }}>
                    <div style={{ background: cfg.color, borderRadius: "4px", height: "4px", width: `${r.confidence * 100}%` }} />
                  </div>
                  <span style={{ color: "#94a3b8", fontSize: "11px" }}>{(r.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading…</div>;
}
