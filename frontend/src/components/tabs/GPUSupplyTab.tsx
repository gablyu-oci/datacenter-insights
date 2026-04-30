import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { GPUSupplyResponse, VendorTimeseriesPoint } from "../../types";
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

const VENDOR_COLOR: Record<string, string> = {
  NVIDIA: "#76b900",
  AMD: "#ed1c24",
  "Intel-DCAI": "#0071c5",
};

function formatBillions(usd: number | null | undefined) {
  if (usd == null) return "--";
  return `$${(usd / 1e9).toFixed(1)}B`;
}

function buildChartData(timeseries: Record<string, VendorTimeseriesPoint[]>) {
  const periodSet = new Set<string>();
  for (const series of Object.values(timeseries)) {
    for (const p of series) {
      const key = p.period_end || p.filing_date;
      if (key) periodSet.add(key);
    }
  }
  const periods = Array.from(periodSet).sort();
  return periods.map((period) => {
    const row: Record<string, number | string> = { period };
    for (const [vendor, series] of Object.entries(timeseries)) {
      const pt = series.find((p) => (p.period_end || p.filing_date) === period);
      if (pt && pt.revenue_usd != null) {
        row[vendor] = pt.revenue_usd / 1e9;  // billions
      }
    }
    return row;
  });
}

export default function GPUSupplyTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage, coverage } =
    useApi<GPUSupplyResponse>("/api/gpu/supply");

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
  const vendors = Object.keys(timeseries);
  const filingsAudited = data?.filings_audited ?? 0;
  const vendorsAudited = data?.vendors_audited ?? [];
  const excluded = coverage?.states_excluded_with_reason ?? {};

  if (vendors.length === 0) {
    return (
      <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "16px" }}>
        <NoDataPanel
          pillar="GPU Supply"
          reason={
            filingsAudited > 0
              ? `${filingsAudited} vendor filings audited but no extractable Data Center segment-revenue figures landed.`
              : "Vendor-supply ingestion has not produced any extracted rows yet. Backend command: python3 -m cli vendor-supply-extract --since 2024-01-01"
          }
        />
        {Object.keys(excluded).length > 0 && (
          <CoverageGapsPanel excluded={excluded} />
        )}
      </div>
    );
  }

  const chartData = buildChartData(timeseries);

  // KPIs: latest revenue per vendor
  const kpis = vendors.map((v) => {
    const series = timeseries[v];
    const latest = series.length > 0 ? series[series.length - 1] : null;
    return {
      vendor: v,
      latestRev: latest?.revenue_usd,
      latestPeriod: latest?.period_end || latest?.filing_date,
      pointCount: series.length,
    };
  });

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* KPIs */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {kpis.map(({ vendor, latestRev, latestPeriod, pointCount }) => (
          <div
            key={vendor}
            style={{
              ...CARD_STYLE,
              flex: 1,
              minWidth: 180,
              borderLeft: `4px solid ${VENDOR_COLOR[vendor] || "#3b82f6"}`,
            }}
          >
            <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
              {vendor} Data Center segment
            </div>
            <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>
              {formatBillions(latestRev)}
            </div>
            <div style={{ color: "#94a3b8", fontSize: "11px", marginTop: "2px" }}>
              {latestPeriod ?? "--"} -- {pointCount} quarter{pointCount !== 1 ? "s" : ""} on file
            </div>
          </div>
        ))}
      </div>

      {/* Per-vendor revenue timeseries */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
          Data Center Segment Revenue by Vendor
        </h3>
        <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
          Extracted from SEC EDGAR 10-K / 10-Q quarterly filings. Y axis: $-billions.
        </p>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
            <XAxis dataKey="period" tick={{ fill: "#94a3b8", fontSize: 11 }} />
            <YAxis
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickFormatter={(v) => `$${v}B`}
            />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: "8px",
              }}
              formatter={(v: number) => `$${v.toFixed(2)}B`}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
            {vendors.map((v) => (
              <Line
                key={v}
                type="monotone"
                dataKey={v}
                stroke={VENDOR_COLOR[v] || "#3b82f6"}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        <CitationFooter
          sources={["SEC EDGAR — vendor 10-K / 10-Q filings"]}
          retrievedAt={lineage?.retrieved_at}
          confidence={lineage?.confidence}
          sourceUrl={lineage?.source_url}
        />
      </div>

      {/* Coverage gaps */}
      {Object.keys(excluded).length > 0 && (
        <CoverageGapsPanel excluded={excluded} />
      )}

      {/* Audit footer */}
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
