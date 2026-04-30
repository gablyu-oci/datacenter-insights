import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type {
  NICsOpticsResponse,
  VendorSupplyRow,
  VendorTimeseriesPoint,
} from "../../types";
import { ExternalLink, AlertTriangle } from "lucide-react";
import ErrorPanel from "../shared/ErrorPanel";
import NoDataPanel from "../shared/NoDataPanel";
import CitationFooter from "../shared/CitationFooter";

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const NIC_COLOR: Record<string, string> = {
  Broadcom: "#cc092f",
  Marvell: "#34495e",
  "Astera Labs": "#7c3aed",
  Credo: "#f59e0b",
};
const OPTICS_COLOR: Record<string, string> = {
  Coherent: "#06b6d4",
  Lumentum: "#22c55e",
  Fabrinet: "#ec4899",
};

function formatBillions(usd: number | null | undefined) {
  if (usd == null) return "--";
  if (Math.abs(usd) >= 1e9) return `$${(usd / 1e9).toFixed(2)}B`;
  return `$${(usd / 1e6).toFixed(0)}M`;
}

function buildChartData(
  timeseries: Record<string, VendorTimeseriesPoint[]>,
  vendors: string[]
) {
  const periodSet = new Set<string>();
  for (const v of vendors) {
    const series = timeseries[v] || [];
    for (const p of series) {
      const key = p.period_end || p.filing_date;
      if (key) periodSet.add(key);
    }
  }
  const periods = Array.from(periodSet).sort();
  return periods.map((period) => {
    const row: Record<string, number | string> = { period };
    for (const v of vendors) {
      const series = timeseries[v] || [];
      const pt = series.find((p) => (p.period_end || p.filing_date) === period);
      if (pt && pt.revenue_usd != null) row[v] = pt.revenue_usd / 1e9;
    }
    return row;
  });
}

function latestRow(rows: VendorSupplyRow[] | undefined, vendor: string) {
  if (!rows) return null;
  const sub = rows
    .filter((r) => r.company === vendor && r.revenue_usd != null)
    .sort((a, b) => (a.period_end || a.filing_date || "").localeCompare(b.period_end || b.filing_date || ""));
  return sub[sub.length - 1] ?? null;
}

export default function NICsOpticsTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage, coverage } =
    useApi<NICsOpticsResponse>("/api/nics");

  if (loading) return <Loader />;
  if (error) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel
          title={errorInfo?.title}
          message={errorInfo?.message}
          onRetry={retry}
          lastAttempt={lastFetchedAt}
        />
      </div>
    );
  }

  const timeseries = data?.timeseries ?? {};
  const nicRows = data?.nic_shipments ?? [];
  const opticsRows = data?.optics_shipments ?? [];
  const filingsAudited = data?.filings_audited ?? 0;
  const vendorsAudited = data?.vendors_audited ?? [];
  const excluded = coverage?.states_excluded_with_reason ?? {};

  const nicVendors = Array.from(new Set(nicRows.map((r) => r.company))).filter(
    (v) => (timeseries[v] || []).length > 0
  );
  const opticsVendors = Array.from(new Set(opticsRows.map((r) => r.company))).filter(
    (v) => (timeseries[v] || []).length > 0
  );

  if (nicVendors.length === 0 && opticsVendors.length === 0) {
    return (
      <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "16px" }}>
        <NoDataPanel
          pillar="NICs & Optics"
          reason={
            filingsAudited > 0
              ? `${filingsAudited} vendor filings audited but no extractable revenue figures landed.`
              : "Vendor-supply ingestion has not produced any extracted rows yet. Backend command: python3 -m cli vendor-supply-extract --since 2024-01-01"
          }
        />
        {Object.keys(excluded).length > 0 && (
          <CoverageGapsPanel excluded={excluded} />
        )}
      </div>
    );
  }

  const nicChart = buildChartData(timeseries, nicVendors);
  const opticsChart = buildChartData(timeseries, opticsVendors);

  // KPIs: latest revenue per vendor (max 4 cards)
  const kpiVendors = [...nicVendors, ...opticsVendors].slice(0, 4);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {kpiVendors.map((vendor) => {
          const latest = latestRow([...nicRows, ...opticsRows], vendor);
          const isNic = nicVendors.includes(vendor);
          const color = isNic ? NIC_COLOR[vendor] : OPTICS_COLOR[vendor];
          return (
            <div
              key={vendor}
              style={{
                ...CARD_STYLE,
                flex: 1,
                minWidth: 180,
                borderLeft: `4px solid ${color || "#3b82f6"}`,
              }}
            >
              <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                {vendor} {isNic ? "(NIC)" : "(Optics)"}
              </div>
              <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>
                {formatBillions(latest?.revenue_usd)}
              </div>
              <div style={{ color: "#94a3b8", fontSize: "11px", marginTop: "2px" }}>
                {latest?.period_end || latest?.filing_date || "--"}
                {latest?.customer_concentration_pct != null && (
                  <span style={{ color: "#f59e0b", marginLeft: 6 }}>
                    -- top customers: {latest.customer_concentration_pct}%
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {nicVendors.length > 0 && (
        <div style={CARD_STYLE}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
            NIC Silicon Vendors -- Quarterly Revenue
          </h3>
          <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
            Broadcom AI networking + Marvell Data Center + Astera Labs + Credo. SEC EDGAR-extracted.
          </p>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={nicChart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
              <XAxis dataKey="period" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `$${v}B`} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
                formatter={(v: number) => `$${v.toFixed(2)}B`}
              />
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
              {nicVendors.map((v) => (
                <Line
                  key={v}
                  type="monotone"
                  dataKey={v}
                  stroke={NIC_COLOR[v] || "#3b82f6"}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <CitationFooter
            sources={["SEC EDGAR — NIC vendor 10-K / 10-Q"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={lineage?.source_url}
          />
        </div>
      )}

      {opticsVendors.length > 0 && (
        <div style={CARD_STYLE}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
            Optical Transceiver Vendors -- Quarterly Revenue
          </h3>
          <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
            Coherent + Lumentum + Fabrinet. Datacom revenue tracks 800G/1.6T optics ramp.
          </p>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={opticsChart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
              <XAxis dataKey="period" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `$${v}B`} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
                formatter={(v: number) => `$${v.toFixed(2)}B`}
              />
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
              {opticsVendors.map((v) => (
                <Line
                  key={v}
                  type="monotone"
                  dataKey={v}
                  stroke={OPTICS_COLOR[v] || "#3b82f6"}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <CitationFooter
            sources={["SEC EDGAR — optics vendor 10-K / 10-Q"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={lineage?.source_url}
          />
        </div>
      )}

      {Object.keys(excluded).length > 0 && (
        <CoverageGapsPanel excluded={excluded} />
      )}

      <div
        style={{
          ...CARD_STYLE,
          padding: "12px 20px",
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
      >
        <ExternalLink size={14} color="#64748b" />
        <span style={{ color: "#64748b", fontSize: "12px" }}>
          {filingsAudited} vendor filings audited via SEC EDGAR. Vendors:{" "}
          {vendorsAudited.join(", ") || "--"}.
        </span>
      </div>
    </div>
  );
}

function CoverageGapsPanel({ excluded }: { excluded: Record<string, string> }) {
  return (
    <div style={CARD_STYLE}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
        <AlertTriangle size={16} color="#f59e0b" />
        <h4 style={{ color: "white", fontWeight: 600, fontSize: "14px", margin: 0 }}>
          Coverage gaps
        </h4>
      </div>
      <ul style={{ margin: 0, paddingLeft: "20px", color: "#cbd5e1", fontSize: "12px", lineHeight: 1.6 }}>
        {Object.entries(excluded).map(([vendor, reason]) => (
          <li key={vendor}>
            <strong style={{ color: "#e2e8f0" }}>{vendor}:</strong> {reason}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Loader() {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        height: "400px",
        color: "#3b82f6",
      }}
    >
      Loading...
    </div>
  );
}
