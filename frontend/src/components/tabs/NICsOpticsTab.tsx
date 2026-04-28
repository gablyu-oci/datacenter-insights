import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  LineChart, Line, ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { NICsOpticsResponse } from "../../types";

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

export default function NICsOpticsTab() {
  const { data, loading } = useApi<NICsOpticsResponse>("/api/nics");

  if (loading) return <Loader />;

  const nics = data?.nic_shipments ?? [];
  const optics = data?.optics_shipments ?? [];
  const corrScore = data?.correlation_score ?? 0;

  const latestNIC = nics[nics.length - 1];
  const latestOptics = optics[optics.length - 1];

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* KPIs */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {[
          { label: "GPU-to-NIC Correlation", value: `${(corrScore * 100).toFixed(0)}%`, sub: "Deployment validation score", color: "#22c55e" },
          { label: "InfiniBand (Q4 2024)", value: (latestNIC?.infiniband ?? 0).toLocaleString(), sub: "Units shipped", color: "#3b82f6" },
          { label: "High-Speed Ethernet (Q4 2024)", value: (latestNIC?.ethernet ?? 0).toLocaleString(), sub: "Units shipped", color: "#06b6d4" },
          { label: "800G Optics (Q4 2024)", value: (latestOptics?.["800g"] ?? 0).toLocaleString(), sub: "Units shipped", color: "#8b5cf6" },
        ].map(({ label, value, sub, color }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, minWidth: 150 }}>
            <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{label}</div>
            <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>{value}</div>
            <div style={{ color, fontSize: "11px", marginTop: "2px" }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* NIC Shipments */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          NIC Shipments — InfiniBand vs High-Speed Ethernet
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          AI cluster networking proxy for GPU deployment activity — Industry Analysis sources
        </p>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={nics}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="quarter" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              formatter={(v: number) => v.toLocaleString()}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
            <Bar dataKey="infiniband" name="InfiniBand" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            <Bar dataKey="ethernet" name="High-Speed Ethernet" fill="#06b6d4" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Optics Shipments */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          Optical Transceiver Shipments — 400G vs 800G
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          800G ramp signals scale-up AI cluster deployments — triangulated against GPU active estimates
        </p>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={optics}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="quarter" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              formatter={(v: number) => v.toLocaleString()}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
            <Line type="monotone" dataKey="400g" name="400G" stroke="#8b5cf6" strokeWidth={2} dot={{ r: 3 }} />
            <Line type="monotone" dataKey="800g" name="800G" stroke="#ec4899" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading…</div>;
}
