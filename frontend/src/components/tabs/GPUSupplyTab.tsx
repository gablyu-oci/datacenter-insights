import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { GPUSupplyResponse } from "../../types";
import { ExternalLink, TrendingUp } from "lucide-react";

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

export default function GPUSupplyTab() {
  const { data, loading } = useApi<GPUSupplyResponse>("/api/gpu/supply");

  if (loading) return <Loader />;

  const shipped = data?.shipped ?? [];
  const deployed = data?.deployed ?? [];
  const inventory = data?.inventory ?? [];
  const revenue = data?.revenue_estimates ?? [];

  // Merge shipped/deployed/inventory for area chart
  const combined = shipped.map((s, i) => ({
    quarter: s.quarter,
    Shipped: s.units,
    Deployed: deployed[i]?.units ?? 0,
    Inventory: inventory[i]?.units ?? 0,
  }));

  const latestShipped = (shipped[shipped.length - 1]?.units ?? 0).toLocaleString();
  const latestDeployed = (deployed[deployed.length - 1]?.units ?? 0).toLocaleString();
  const latestGap = ((shipped[shipped.length - 1]?.units ?? 0) - (deployed[deployed.length - 1]?.units ?? 0)).toLocaleString();
  const latestRev = revenue[revenue.length - 1]?.revenue_b ?? 0;

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* KPIs */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {[
          { label: "GPUs Shipped (cumulative)", value: latestShipped, sub: "Q4 2024 estimate" },
          { label: "GPUs Deployed (active)", value: latestDeployed, sub: "Via NIC/optics proxy" },
          { label: "Inventory Gap", value: latestGap, sub: "Shipped − deployed" },
          { label: "NVIDIA AI Revenue", value: `$${latestRev}B`, sub: "Latest quarter" },
        ].map(({ label, value, sub }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, minWidth: 150 }}>
            <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{label}</div>
            <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>{value}</div>
            <div style={{ color: "#22c55e", fontSize: "11px", marginTop: "2px" }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* Shipped vs Deployed area chart */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          GPU Shipments vs Deployments
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          Cumulative units — inventory gap represents shipped but not yet active GPUs
        </p>
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={combined}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="quarter" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              formatter={(v: number) => v.toLocaleString()}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
            <Area type="monotone" dataKey="Shipped" stroke="#3b82f6" fill="#3b82f620" strokeWidth={2} />
            <Area type="monotone" dataKey="Deployed" stroke="#22c55e" fill="#22c55e20" strokeWidth={2} />
            <Area type="monotone" dataKey="Inventory" stroke="#f59e0b" fill="#f59e0b20" strokeWidth={2} strokeDasharray="5 5" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Revenue to unit inference */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
              Revenue → Unit Inference (NVIDIA AI Data Center)
            </h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
              Implied GPU units derived from revenue ÷ estimated ASP — Earnings Parsing Agent
            </p>
          </div>
          <TrendingUp size={18} color="#f59e0b" />
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={revenue}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="quarter" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis yAxisId="left" tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `$${v}B`} />
            <YAxis yAxisId="right" orientation="right" tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
            <Bar yAxisId="left" dataKey="revenue_b" name="Revenue ($B)" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            <Bar yAxisId="right" dataKey="units_implied" name="Implied Units" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div style={{ ...CARD_STYLE, padding: "12px 20px", display: "flex", alignItems: "center", gap: "8px" }}>
        <ExternalLink size={14} color="#64748b" />
        <span style={{ color: "#64748b", fontSize: "12px" }}>
          GPU shipment data inferred from NVIDIA earnings transcripts and financial filings. Unit estimates use avg ASP model. Confidence: 0.91.
        </span>
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading…</div>;
}
