import { useState } from "react";
import { useApi } from "../../hooks/useApi";
import type { PermitRecord } from "../../types";
import { Filter, ExternalLink, MapPin } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface PermitsResponse { data: PermitRecord[]; colors: Record<string, string>; }

const STATUS_COLORS: Record<string, string> = {
  Approved: "#22c55e",
  Pending: "#f59e0b",
  "Under Review": "#3b82f6",
  Completed: "#94a3b8",
};

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

export default function PermitsTab() {
  const { data, loading } = useApi<PermitsResponse>("/api/permits");
  const [filterCompany, setFilterCompany] = useState("All");
  const [filterStatus, setFilterStatus] = useState("All");

  if (loading) return <Loader />;

  const permits = data?.data ?? [];
  const colors = data?.colors ?? {};

  const companies = ["All", ...Array.from(new Set(permits.map((p) => p.company))).sort()];
  const statuses = ["All", "Approved", "Pending", "Under Review", "Completed"];

  const filtered = permits.filter(
    (p) => (filterCompany === "All" || p.company === filterCompany)
      && (filterStatus === "All" || p.status === filterStatus)
  );

  // Aggregate MW by county
  const countyMW: Record<string, number> = {};
  filtered.forEach((p) => { countyMW[p.county] = (countyMW[p.county] ?? 0) + p.estimated_mw; });
  const countyChart = Object.entries(countyMW)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([county, mw]) => ({ county: county.split(" County")[0], mw: +mw.toFixed(0) }));

  // Company permit counts
  const companyCount: Record<string, number> = {};
  filtered.forEach((p) => { companyCount[p.company] = (companyCount[p.company] ?? 0) + 1; });

  const totalMW = filtered.reduce((s, p) => s + p.estimated_mw, 0).toFixed(0);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* KPIs */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {[
          { label: "Total Permits (filtered)", value: String(filtered.length) },
          { label: "Total Estimated MW", value: `${totalMW} MW` },
          { label: "Counties Tracked", value: String(new Set(permits.map((p) => p.county)).size) },
          { label: "Active Filings", value: String(permits.filter((p) => p.status === "Pending" || p.status === "Under Review").length) },
        ].map(({ label, value }) => (
          <div key={label} style={{ ...CARD_STYLE, flex: 1, minWidth: 140 }}>
            <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{label}</div>
            <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ ...CARD_STYLE, padding: "14px 20px", display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Filter size={14} color="#64748b" />
          <span style={{ color: "#94a3b8", fontSize: "13px" }}>Filter:</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ color: "#64748b", fontSize: "12px" }}>Company:</span>
          <select value={filterCompany} onChange={(e) => setFilterCompany(e.target.value)}
            style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "6px", color: "white", padding: "4px 8px", fontSize: "12px" }}>
            {companies.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ color: "#64748b", fontSize: "12px" }}>Status:</span>
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
            style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "6px", color: "white", padding: "4px 8px", fontSize: "12px" }}>
            {statuses.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
      </div>

      {/* MW by county chart */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          Estimated MW by County (Top 8)
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          Construction ground truth — County Public Records APIs
        </p>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={countyChart} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} unit=" MW" />
            <YAxis type="category" dataKey="county" tick={{ fill: "#94a3b8", fontSize: 11 }} width={120} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
              formatter={(v: number) => `${v} MW`}
            />
            <Bar dataKey="mw" name="Estimated MW" fill="#3b82f6" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Permits table */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 16px" }}>
          Permit Records ({filtered.length})
        </h3>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                {["County", "State", "Company", "Type", "Filed", "Status", "Est. MW", "Source"].map((h) => (
                  <th key={h} style={{ color: "#64748b", textAlign: "left", padding: "8px 12px", fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 30).map((p, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                  <td style={{ padding: "8px 12px", color: "#e2e8f0" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                      <MapPin size={11} color="#64748b" />
                      {p.county}
                    </div>
                  </td>
                  <td style={{ padding: "8px 12px", color: "#94a3b8" }}>{p.state}</td>
                  <td style={{ padding: "8px 12px" }}>
                    <span style={{
                      padding: "2px 8px",
                      borderRadius: "4px",
                      background: `${colors[p.company] ?? "#666"}22`,
                      color: colors[p.company] ?? "#ccc",
                      fontSize: "11px",
                    }}>
                      {p.company}
                    </span>
                  </td>
                  <td style={{ padding: "8px 12px", color: "#94a3b8" }}>{p.permit_type}</td>
                  <td style={{ padding: "8px 12px", color: "#94a3b8" }}>{p.filed_date}</td>
                  <td style={{ padding: "8px 12px" }}>
                    <span style={{ color: STATUS_COLORS[p.status] ?? "#ccc", fontSize: "11px" }}>● {p.status}</span>
                  </td>
                  <td style={{ padding: "8px 12px", color: "#e2e8f0" }}>{p.estimated_mw} MW</td>
                  <td style={{ padding: "8px 12px" }}>
                    <a href={p.source_url} target="_blank" rel="noreferrer"
                      style={{ color: "#3b82f6", display: "flex", alignItems: "center", gap: "4px", textDecoration: "none" }}>
                      <ExternalLink size={11} />
                      {p.source}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length > 30 && (
            <div style={{ color: "#64748b", fontSize: "12px", padding: "8px 12px" }}>
              Showing 30 of {filtered.length} records
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading…</div>;
}
