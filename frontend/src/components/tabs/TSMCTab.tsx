import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type {
  TSMCResponse,
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

const FOUNDRY_COLOR: Record<string, string> = {
  TSMC: "#bf3030",
  "Intel-Foundry": "#0071c5",
  GlobalFoundries: "#0098db",
};
const PACKAGING_COLOR: Record<string, string> = {
  Amkor: "#f59e0b",
  "ASE Technology": "#22c55e",
};
const EQUIPMENT_COLOR: Record<string, string> = {
  ASML: "#ec4899",
  "Applied Materials": "#8b5cf6",
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

interface SubPanelProps {
  title: string;
  description: string;
  rows: VendorSupplyRow[];
  timeseries: Record<string, VendorTimeseriesPoint[]>;
  colorMap: Record<string, string>;
  citationSource: string;
}

function SubPanel({ title, description, rows, timeseries, colorMap, citationSource }: SubPanelProps & { lineage?: { retrieved_at?: string; confidence?: number; source_url?: string } | null }) {
  const vendors = Array.from(new Set(rows.map((r) => r.company))).filter(
    (v) => (timeseries[v] || []).length > 0
  );
  if (vendors.length === 0) return null;
  const chart = buildChartData(timeseries, vendors);
  return (
    <div style={CARD_STYLE}>
      <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
        {title}
      </h3>
      <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>{description}</p>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={chart}>
          <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
          <XAxis dataKey="period" tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => `$${v}B`} />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
            formatter={(v: number) => `$${v.toFixed(2)}B`}
          />
          <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
          {vendors.map((v) => (
            <Line
              key={v}
              type="monotone"
              dataKey={v}
              stroke={colorMap[v] || "#3b82f6"}
              strokeWidth={2}
              dot={{ r: 3 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <CitationFooter sources={[citationSource]} />
    </div>
  );
}

export default function TSMCTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage, coverage } =
    useApi<TSMCResponse>("/api/tsmc");

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
  const foundryRows = (data?.capacity ?? []) as VendorSupplyRow[];
  const packagingRows = (data?.packaging ?? []) as VendorSupplyRow[];
  const equipmentRows = (data?.equipment ?? []) as VendorSupplyRow[];
  const filingsAudited = data?.filings_audited ?? 0;
  const vendorsAudited = data?.vendors_audited ?? [];
  const excluded = coverage?.states_excluded_with_reason ?? {};

  const allRows = [...foundryRows, ...packagingRows, ...equipmentRows];
  const allVendorsWithSeries = Array.from(new Set(allRows.map((r) => r.company))).filter(
    (v) => (timeseries[v] || []).length > 0
  );

  if (allVendorsWithSeries.length === 0) {
    return (
      <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "16px" }}>
        <NoDataPanel
          pillar="Wafer Production & Supply"
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

  // KPIs: latest revenue per vendor — pick top 4 by latest revenue
  const kpiVendors = allVendorsWithSeries
    .map((v) => ({ vendor: v, latest: latestRow(allRows, v) }))
    .filter((x) => x.latest)
    .sort((a, b) => (b.latest!.revenue_usd ?? 0) - (a.latest!.revenue_usd ?? 0))
    .slice(0, 4);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
        {kpiVendors.map(({ vendor, latest }) => {
          const color =
            FOUNDRY_COLOR[vendor] ||
            PACKAGING_COLOR[vendor] ||
            EQUIPMENT_COLOR[vendor] ||
            "#3b82f6";
          return (
            <div
              key={vendor}
              style={{
                ...CARD_STYLE,
                flex: 1,
                minWidth: 180,
                borderLeft: `4px solid ${color}`,
              }}
            >
              <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{vendor}</div>
              <div style={{ color: "white", fontSize: "24px", fontWeight: 700 }}>
                {formatBillions(latest?.revenue_usd)}
              </div>
              <div style={{ color: "#94a3b8", fontSize: "11px", marginTop: "2px" }}>
                {latest?.period_end || latest?.filing_date || "--"}
                {latest?.segment_name && (
                  <span style={{ marginLeft: 6 }}>-- {latest.segment_name}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <SubPanel
        title="Foundry vendors -- Quarterly revenue"
        description="TSMC HPC platform + Intel Foundry + GlobalFoundries. Leading-edge wafer capacity gates AI accelerator shipments."
        rows={foundryRows}
        timeseries={timeseries}
        colorMap={FOUNDRY_COLOR}
        citationSource="SEC EDGAR -- foundry 20-F / 10-K"
        lineage={lineage}
      />

      <SubPanel
        title="OSAT / Advanced Packaging -- Quarterly revenue"
        description="Amkor Advanced Products + ASE LEAP. CoWoS / 2.5D / HDFO supply tracks Nvidia / AMD shipment cadence."
        rows={packagingRows}
        timeseries={timeseries}
        colorMap={PACKAGING_COLOR}
        citationSource="SEC EDGAR -- OSAT 10-K / 20-F"
        lineage={lineage}
      />

      <SubPanel
        title="Semiconductor equipment -- Quarterly revenue (leading indicator)"
        description="ASML lithography + Applied Materials. Equipment orders precede foundry capacity by 6-12 months."
        rows={equipmentRows}
        timeseries={timeseries}
        colorMap={EQUIPMENT_COLOR}
        citationSource="SEC EDGAR -- equipment 10-K / 20-F"
        lineage={lineage}
      />

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
