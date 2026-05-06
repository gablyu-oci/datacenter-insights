/**
 * TriangulationTab — Phase 2 (AC4) + AC2 (L2).
 *
 * L1 (Contracted Power, GW per company × state) is sourced honestly from
 * sites + curated_deals + EDGAR extractions.
 *
 * L2 (Compute Demand vs. Contracted Power) is modelled from NVIDIA Data
 * Center segment revenue / inventory using assumption dials surfaced in
 * the UI. L3 / L4 still require paid feeds.
 *
 * Endpoints: GET /api/triangulation/l1, GET /api/triangulation/l2
 */
import { useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import { Info } from "lucide-react";
import ErrorPanel from "../shared/ErrorPanel";
import NoDataPanel from "../shared/NoDataPanel";
import CitationFooter from "../shared/CitationFooter";
import WeeklyBriefCard from "../WeeklyBriefCard";

interface L1Source { type: "sites" | "deals" | "edgar"; count: number; mw: number; }
interface L1Record {
  company: string;
  state: string;
  gw_total: number;
  sources: L1Source[];
  confidence: number;
}
interface L1Response {
  data: L1Record[];
  note: string;
  layers_implemented?: string[];
  layers_pending?: string[];
}

interface L2HyperscalerShare {
  company: string;
  contracted_gw: number;
  implied_compute_gw: number;
  gap_gw: number;
  status: string;
  share_fraction: number;
}
interface L2Assumptions {
  avg_gpu_price_usd: number;
  avg_blended_power_w: number;
  utilization_pct: number;
  overhead_multiplier: number;
  h100_avg_power_w: number;
  b200_avg_power_w: number;
}
interface L2Data {
  period_end: string | null;
  nvidia_dc_revenue_usd: number | null;
  nvidia_inventory_usd: number | null;
  inferred_units_total: number | null;
  inferred_compute_gw: number | null;
  assumptions: L2Assumptions;
  per_hyperscaler_share: L2HyperscalerShare[];
}

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
} as const;

const LAYERS: Array<{
  layer: string; label: string; desc: string; status: "live" | "modelled" | "blocked"; anchor?: string;
}> = [
  { layer: "L1", label: "Contracted Power",     desc: "GW signed with utilities (sites + curated deals + EDGAR)",         status: "live",     anchor: "l1-section" },
  { layer: "L2", label: "GPU Compute Demand",   desc: "NVIDIA DC revenue × unit economics (modelled — see assumptions)",  status: "modelled", anchor: "l2-section" },
  { layer: "L3", label: "NIC/Optics Signals",   desc: "Coherent / Lumentum order books — paid data",                      status: "blocked" },
  { layer: "L4", label: "Permit Ground Truth",  desc: "County-level construction permits — paid data",                    status: "blocked" },
];

function scrollToAnchor(id: string) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function TriangulationTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } =
    useApi<L1Response>("/api/triangulation/l1");

  const {
    data: l2Data,
    loading: l2Loading,
    error: l2Error,
    errorInfo: l2ErrorInfo,
    retry: l2Retry,
    lastFetchedAt: l2LastFetchedAt,
    lineage: l2Lineage,
    coverage: l2Coverage,
  } = useApi<L2Data>("/api/triangulation/l2");

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

  const records: L1Record[] = data?.data ?? [];

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      <WeeklyBriefCard />

      {/* Layer status / honest scope banner */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
          <Info size={16} color="#3b82f6" />
          <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
            Multi-Layer Triangulation Model — L1 only
          </h3>
        </div>
        <p style={{ color: "#94a3b8", fontSize: "12px", margin: "0 0 12px" }}>
          {data?.note ??
            "Layer 1 (Contracted Power) is computed from sites.power_capacity_mw + curated_deals.capacity_mw + edgar_extractions.capacity_mw, deduplicated by (company, state). Layers 2–4 require paid data sources not yet procured."}
        </p>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          {LAYERS.map(({ layer, label, desc, status, anchor }) => {
            const isLive = status === "live";
            const isModelled = status === "modelled";
            const accent = isLive ? "#22c55e" : isModelled ? "#eab308" : "#334155";
            const labelText =
              isLive
                ? "LIVE"
                : isModelled
                  ? "live (modelled — see assumptions)"
                  : "Paid data required";
            const clickable = !!anchor;
            return (
              <div
                key={layer}
                onClick={clickable ? () => scrollToAnchor(anchor!) : undefined}
                title={clickable ? `Scroll to ${label}` : undefined}
                role={clickable ? "button" : undefined}
                tabIndex={clickable ? 0 : undefined}
                onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") scrollToAnchor(anchor!); } : undefined}
                style={{
                  background: "#0f172a",
                  border: `1px solid ${accent}`,
                  borderRadius: "8px",
                  padding: "12px 16px",
                  flex: 1,
                  minWidth: 180,
                  opacity: isLive || isModelled ? 1 : 0.55,
                  cursor: clickable ? "pointer" : "default",
                  transition: "transform 0.1s, box-shadow 0.1s",
                }}
                onMouseEnter={clickable ? (e) => { (e.currentTarget as HTMLDivElement).style.transform = "translateY(-1px)"; (e.currentTarget as HTMLDivElement).style.boxShadow = `0 4px 12px ${accent}33`; } : undefined}
                onMouseLeave={clickable ? (e) => { (e.currentTarget as HTMLDivElement).style.transform = ""; (e.currentTarget as HTMLDivElement).style.boxShadow = ""; } : undefined}
              >
                <div style={{
                  display: "flex", alignItems: "center", gap: "6px", marginBottom: "4px",
                }}>
                  <span style={{
                    color: isLive || isModelled ? accent : "#64748b",
                    fontSize: "11px", fontWeight: 700,
                  }}>{layer}</span>
                  <span style={{
                    color: isLive || isModelled ? accent : "#94a3b8",
                    fontSize: "10px",
                    border: `1px solid ${isLive || isModelled ? `${accent}44` : "#33415588"}`,
                    borderRadius: "4px",
                    padding: "1px 6px",
                  }}>
                    {labelText}
                  </span>
                  {clickable && (
                    <span style={{ color: "#64748b", fontSize: "10px", marginLeft: "auto" }}>↓ click</span>
                  )}
                </div>
                <div style={{ color: "white", fontSize: "13px", fontWeight: 600 }}>{label}</div>
                <div style={{ color: "#64748b", fontSize: "11px", marginTop: "2px" }}>{desc}</div>
              </div>
            );
          })}
        </div>
      </div>

      {records.length === 0 ? (
        <NoDataPanel
          pillar="Triangulation L1"
          reason="No company × state contracted-power signals are populated yet. Run `python cli.py ingest --source edgar_quarterly` and `--source aterio` to land L1 inputs."
        />
      ) : (
        <div id="l1-section" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* L1 grouped bar chart: total GW per company, top 10 */}
          <L1Chart records={records} />

          {/* L1 detail table — paginated/sortable/filterable */}
          <L1Table records={records} />
        </div>
      )}

      {/* L2 — Compute Demand vs. Contracted Power */}
      <div id="l2-section" />
      <L2Section
        loading={l2Loading}
        error={l2Error}
        errorInfo={l2ErrorInfo}
        retry={l2Retry}
        lastFetchedAt={l2LastFetchedAt}
        data={l2Data}
        lineage={l2Lineage}
        coverageNote={
          l2Coverage?.states_excluded_with_reason?.ALL ?? null
        }
      />

      <CitationFooter
        sources={["sites.power_capacity_mw", "curated_deals.capacity_mw", "edgar_extractions.capacity_mw"]}
        retrievedAt={lineage?.retrieved_at}
        confidence={lineage?.confidence}
        sourceUrl={lineage?.source_url}
      />
    </div>
  );
}


// ---------------------------------------------------------------------------
// L1 grouped bar chart — sum GW per company, top 10
// ---------------------------------------------------------------------------

function L1Chart({ records }: { records: L1Record[] }) {
  // Aggregate per company across all states for the top-line view.
  const byCompany = new Map<string, number>();
  for (const r of records) {
    byCompany.set(r.company, (byCompany.get(r.company) ?? 0) + r.gw_total);
  }
  const chartData = Array.from(byCompany.entries())
    .map(([company, gw]) => ({ company, "Contracted GW (L1)": Number(gw.toFixed(2)) }))
    .sort((a, b) => b["Contracted GW (L1)"] - a["Contracted GW (L1)"])
    .slice(0, 10);

  return (
    <div style={CARD_STYLE}>
      <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 4px" }}>
        Contracted Power by Company (L1) — Top 10
      </h3>
      <p style={{ color: "#64748b", fontSize: "12px", margin: "0 0 16px" }}>
        Sum of disclosed contracted MW across sites, curated deals, and EDGAR extractions, converted to GW.
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
          <XAxis dataKey="company" tick={{ fill: "#94a3b8", fontSize: 11 }} interval={0} angle={-25} textAnchor="end" height={70} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} unit=" GW" />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
            formatter={(v) => `${v} GW`}
          />
          <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
          <Bar dataKey="Contracted GW (L1)" fill="#3b82f6" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}


// ---------------------------------------------------------------------------
// L1 detail table
// ---------------------------------------------------------------------------

type L1SortField = "company" | "state" | "gw_total" | "confidence";

function L1Table({ records }: { records: L1Record[] }) {
  const [filter, setFilter] = useState("");
  const [sortField, setSortField] = useState<L1SortField>("gw_total");
  const [sortAsc, setSortAsc] = useState(false);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 25;

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return records;
    return records.filter(
      r => r.company.toLowerCase().includes(q) || r.state.toLowerCase().includes(q),
    );
  }, [records, filter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      let cmp = 0;
      if (sortField === "gw_total") cmp = a.gw_total - b.gw_total;
      else if (sortField === "confidence") cmp = a.confidence - b.confidence;
      else if (sortField === "company") cmp = a.company.localeCompare(b.company);
      else cmp = a.state.localeCompare(b.state);
      return sortAsc ? cmp : -cmp;
    });
    return arr;
  }, [filtered, sortField, sortAsc]);

  const total = sorted.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const startIdx = (safePage - 1) * PAGE_SIZE;
  const pageRows = sorted.slice(startIdx, startIdx + PAGE_SIZE);

  const toggleSort = (f: L1SortField) => {
    if (sortField === f) setSortAsc(v => !v);
    else { setSortField(f); setSortAsc(false); }
    setPage(1);
  };

  return (
    <div style={CARD_STYLE}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
          L1 Detail — Company × State
        </h3>
        <input
          type="text"
          placeholder="Filter by company or state..."
          value={filter}
          onChange={e => { setFilter(e.target.value); setPage(1); }}
          style={{
            background: "#0f172a", border: "1px solid #334155", borderRadius: 6,
            color: "white", padding: "6px 10px", fontSize: 12, minWidth: 220,
          }}
        />
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155" }}>
              <SortableTh active={sortField === "company"} asc={sortAsc} onClick={() => toggleSort("company")}>Company</SortableTh>
              <SortableTh active={sortField === "state"} asc={sortAsc} onClick={() => toggleSort("state")}>State</SortableTh>
              <SortableTh active={sortField === "gw_total"} asc={sortAsc} onClick={() => toggleSort("gw_total")} align="right">GW Total</SortableTh>
              <Th>Sources</Th>
              <SortableTh active={sortField === "confidence"} asc={sortAsc} onClick={() => toggleSort("confidence")} align="right">Confidence</SortableTh>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r, i) => (
              <tr key={`${r.company}-${r.state}-${startIdx + i}`}
                  style={{ borderBottom: "1px solid #1f2937" }}>
                <Td><span style={{ color: "white", fontWeight: 600 }}>{r.company}</span></Td>
                <Td><span style={{ color: "#94a3b8" }}>{r.state}</span></Td>
                <Td align="right">
                  <span style={{ color: "#22c55e", fontWeight: 600 }}>{r.gw_total.toFixed(2)}</span>
                </Td>
                <Td>
                  <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                    {r.sources.map((s) => (
                      <span key={s.type} style={{
                        background: "#0f172a",
                        border: "1px solid #334155",
                        borderRadius: "4px",
                        padding: "2px 6px",
                        color: "#cbd5e1",
                        fontSize: "11px",
                      }}>
                        {s.type}: {s.count} · {s.mw.toFixed(0)} MW
                      </span>
                    ))}
                  </div>
                </Td>
                <Td align="right">
                  <ConfidencePill value={r.confidence} />
                </Td>
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: 16, textAlign: "center", color: "#64748b" }}>
                  No rows match this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, color: "#94a3b8", fontSize: 11 }}>
        <span>
          Showing {total === 0 ? 0 : startIdx + 1}–{Math.min(startIdx + PAGE_SIZE, total)} of {total}
          {filter && ` (filtered from ${records.length})`}
        </span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <PagerButton disabled={safePage === 1} onClick={() => setPage(1)}>«</PagerButton>
          <PagerButton disabled={safePage === 1} onClick={() => setPage(p => Math.max(1, p - 1))}>‹</PagerButton>
          <span style={{ padding: "0 6px" }}>Page {safePage} / {pageCount}</span>
          <PagerButton disabled={safePage >= pageCount} onClick={() => setPage(p => Math.min(pageCount, p + 1))}>›</PagerButton>
          <PagerButton disabled={safePage >= pageCount} onClick={() => setPage(pageCount)}>»</PagerButton>
        </div>
      </div>
      <p style={{ color: "#64748b", fontSize: "11px", marginTop: "12px" }}>
        Confidence rises with the number of corroborating sources (0.50 base
        +0.15 if ≥2 sources +0.10 if ≥3 sources, capped at 0.85).
      </p>
    </div>
  );
}

function SortableTh({ children, active, asc, onClick, align }: { children: React.ReactNode; active: boolean; asc: boolean; onClick: () => void; align?: "right" | "left" }) {
  return (
    <th
      onClick={onClick}
      style={{
        textAlign: align ?? "left",
        padding: "8px 12px",
        color: active ? "#60a5fa" : "#94a3b8",
        fontWeight: 600,
        fontSize: "11px",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      {children}
      {active && <span style={{ marginLeft: 4, fontSize: 10 }}>{asc ? "▲" : "▼"}</span>}
    </th>
  );
}

function PagerButton({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: disabled ? "transparent" : "#0f172a",
        border: "1px solid #334155",
        borderRadius: 4,
        color: disabled ? "#475569" : "#cbd5e1",
        padding: "2px 8px",
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: 12,
      }}
    >
      {children}
    </button>
  );
}


function Th({ children, align }: { children: React.ReactNode; align?: "right" | "left" }) {
  return (
    <th style={{
      textAlign: align ?? "left",
      padding: "10px 12px",
      color: "#94a3b8",
      fontWeight: 600,
      fontSize: "11px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
    }}>{children}</th>
  );
}

function Td({ children, align }: { children: React.ReactNode; align?: "right" | "left" }) {
  return (
    <td style={{ textAlign: align ?? "left", padding: "8px 12px", color: "#cbd5e1" }}>
      {children}
    </td>
  );
}

function ConfidencePill({ value }: { value: number }) {
  const pct = Math.round((value ?? 0) * 100);
  let color = "#f59e0b";
  if (pct >= 75) color = "#22c55e";
  else if (pct >= 60) color = "#3b82f6";
  return (
    <span style={{
      color, fontWeight: 600,
      background: `${color}22`,
      padding: "2px 8px",
      borderRadius: "999px",
      fontSize: "11px",
    }}>{pct}%</span>
  );
}

function Loader() {
  return (
    <div style={{
      display: "flex", justifyContent: "center", alignItems: "center",
      height: "400px", color: "#3b82f6",
    }}>
      Loading L1 triangulation…
    </div>
  );
}


// ---------------------------------------------------------------------------
// L2 — Compute Demand vs. Contracted Power
// ---------------------------------------------------------------------------

interface L2SectionProps {
  loading: boolean;
  error: string | null;
  errorInfo: { title: string; message: string } | null;
  retry: () => void;
  lastFetchedAt: Date | null;
  data: L2Data | null;
  lineage: { source_url?: string; retrieved_at?: string; confidence?: number } | null;
  coverageNote: string | null;
}

function L2Section({
  loading, error, errorInfo, retry, lastFetchedAt,
  data, lineage, coverageNote,
}: L2SectionProps) {
  return (
    <div style={CARD_STYLE}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
        <Info size={16} color="#eab308" />
        <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
          L2 — Compute Demand vs. Contracted Power
        </h3>
        <span style={{
          color: "#eab308",
          fontSize: "10px",
          border: "1px solid #eab30844",
          borderRadius: "4px",
          padding: "1px 6px",
          marginLeft: "4px",
        }}>
          modelled
        </span>
      </div>
      <p style={{ color: "#94a3b8", fontSize: "12px", margin: "0 0 16px" }}>
        Translates NVIDIA Data Center segment revenue into implied compute GW
        using GPU unit economics, then compares against L1 contracted power
        per hyperscaler. The dials are open — see Assumptions below.
      </p>

      {loading && <L2Skeleton />}

      {!loading && error && (
        <ErrorPanel
          title={errorInfo?.title}
          message={errorInfo?.message}
          onRetry={retry}
          lastAttempt={lastFetchedAt}
        />
      )}

      {!loading && !error && data && (
        data.nvidia_dc_revenue_usd == null ? (
          <div style={{
            color: "#94a3b8",
            fontSize: "13px",
            padding: "24px",
            textAlign: "center",
            background: "#0f172a",
            border: "1px dashed #334155",
            borderRadius: "8px",
          }}>
            No NVIDIA Data Center revenue extracted yet.
          </div>
        ) : (
          <L2Body data={data} coverageNote={coverageNote} lineage={lineage} />
        )
      )}
    </div>
  );
}

function L2Body({
  data, coverageNote,
}: {
  data: L2Data;
  coverageNote: string | null;
  lineage: { source_url?: string; retrieved_at?: string; confidence?: number } | null;
}) {
  const periodEnd = data.period_end ?? "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* KPI tiles */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px" }}>
        <KpiTile
          label="NVIDIA DC Revenue"
          value={formatUsdBillions(data.nvidia_dc_revenue_usd)}
          subtitle={`as of ${periodEnd}`}
          accent="#3b82f6"
        />
        <KpiTile
          label="Inferred Units"
          value={formatUnitsMillions(data.inferred_units_total)}
          subtitle={`as of ${periodEnd}`}
          accent="#a855f7"
        />
        <KpiTile
          label="Inferred Compute GW"
          value={formatGw(data.inferred_compute_gw)}
          subtitle={`as of ${periodEnd}`}
          accent="#f97316"
        />
      </div>

      {/* Side-by-side bar chart per hyperscaler */}
      <L2HyperscalerChart rows={data.per_hyperscaler_share} />

      {/* Inventory overhang callout */}
      {data.nvidia_inventory_usd != null && data.nvidia_inventory_usd > 0 && (
        <div
          title="NVIDIA inventory line item — chips on the balance sheet that have not yet shipped to customers."
          style={{
            background: "#0f172a",
            border: "1px solid #f59e0b55",
            borderRadius: "8px",
            padding: "10px 14px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
          <span style={{ color: "#f59e0b", fontWeight: 700, fontSize: "12px" }}>
            Inventory overhang
          </span>
          <span style={{ color: "#cbd5e1", fontSize: "13px" }}>
            {formatUsdBillions(data.nvidia_inventory_usd)} warehoused but not yet deployed
          </span>
        </div>
      )}

      {/* Assumptions panel */}
      <details style={{
        background: "#0f172a",
        border: "1px solid #334155",
        borderRadius: "8px",
        padding: "10px 14px",
      }}>
        <summary style={{
          cursor: "pointer",
          color: "#cbd5e1",
          fontSize: "13px",
          fontWeight: 600,
          listStyle: "revert",
        }}>
          Assumptions (the dials of the model)
        </summary>
        <p style={{ color: "#64748b", fontSize: "11px", margin: "8px 0 12px" }}>
          These are the dials of the model. the user will push back on each — that's the point.
        </p>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
          <tbody>
            <AssumptionRow k="AVG_GPU_PRICE_USD"   v={formatUsd(data.assumptions.avg_gpu_price_usd)} />
            <AssumptionRow k="AVG_BLENDED_POWER_W" v={`${data.assumptions.avg_blended_power_w} W`} />
            <AssumptionRow k="UTILIZATION_PCT"     v={`${Math.round(data.assumptions.utilization_pct * 100)}%`} />
            <AssumptionRow k="OVERHEAD_MULTIPLIER" v={`${data.assumptions.overhead_multiplier}\u00d7`} />
            <AssumptionRow k="H100_AVG_POWER_W"    v={`${data.assumptions.h100_avg_power_w} W`} />
            <AssumptionRow k="B200_AVG_POWER_W"    v={`${data.assumptions.b200_avg_power_w} W`} />
          </tbody>
        </table>
      </details>

      {/* Coverage note */}
      {coverageNote && (
        <p style={{ color: "#64748b", fontSize: "11px", margin: 0, lineHeight: 1.5 }}>
          {coverageNote}
        </p>
      )}
    </div>
  );
}

function L2HyperscalerChart({ rows }: { rows: L2HyperscalerShare[] }) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{
        color: "#94a3b8", fontSize: "13px", padding: "16px", textAlign: "center",
      }}>
        No hyperscaler split available.
      </div>
    );
  }

  const chartData = rows.map((r) => ({
    company: r.company,
    "Contracted GW (L1)": Number(r.contracted_gw.toFixed(2)),
    "Implied Compute GW (L2)": Number(r.implied_compute_gw.toFixed(2)),
    gap_gw: r.gap_gw,
    status: r.status,
  }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 12, right: 140 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
          <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} unit=" GW" />
          <YAxis
            type="category"
            dataKey="company"
            tick={{ fill: "#cbd5e1", fontSize: 12 }}
            width={90}
          />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "8px" }}
            formatter={(v) => `${v} GW`}
          />
          <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
          <Bar dataKey="Contracted GW (L1)" fill="#3b82f6" radius={[0, 4, 4, 0]} />
          <Bar dataKey="Implied Compute GW (L2)" fill="#f97316" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>

      {/* Gap labels per row */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr",
        gap: "4px",
        marginTop: "4px",
      }}>
        {rows.map((r) => (
          <div key={r.company} style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: "11px",
            padding: "2px 8px",
          }}>
            <span style={{ color: "#94a3b8" }}>{r.company}</span>
            <span style={{
              color: r.status === "overcontracted" ? "#22c55e" : "#ef4444",
              fontWeight: 600,
            }}>
              {formatGap(r.gap_gw, r.status)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AssumptionRow({ k, v }: { k: string; v: string }) {
  return (
    <tr style={{ borderBottom: "1px solid #1f2937" }}>
      <td style={{ padding: "6px 8px", color: "#94a3b8", fontFamily: "ui-monospace, monospace", fontSize: "11px" }}>
        {k}
      </td>
      <td style={{ padding: "6px 8px", color: "white", fontWeight: 600, textAlign: "right" }}>
        {v}
      </td>
    </tr>
  );
}

function KpiTile({
  label, value, subtitle, accent,
}: { label: string; value: string; subtitle: string; accent: string }) {
  return (
    <div style={{
      background: "#0f172a",
      border: `1px solid ${accent}55`,
      borderRadius: "8px",
      padding: "12px 14px",
    }}>
      <div style={{ color: "#94a3b8", fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
        {label}
      </div>
      <div style={{ color: accent, fontSize: "22px", fontWeight: 700, marginTop: "4px" }}>
        {value}
      </div>
      <div style={{ color: "#64748b", fontSize: "11px", marginTop: "2px" }}>
        {subtitle}
      </div>
    </div>
  );
}

function L2Skeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px" }}>
        {[0, 1, 2].map((i) => (
          <div key={i} style={{
            height: "78px",
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: "8px",
          }} />
        ))}
      </div>
      <div style={{
        height: "320px",
        background: "#0f172a",
        border: "1px solid #334155",
        borderRadius: "8px",
      }} />
      <div style={{ color: "#3b82f6", fontSize: "12px", textAlign: "center" }}>
        Loading L2 triangulation…
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// formatters
// ---------------------------------------------------------------------------

function formatUsdBillions(v: number | null | undefined): string {
  if (v == null) return "—";
  const b = v / 1_000_000_000;
  return `$${b.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
}

function formatUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatUnitsMillions(v: number | null | undefined): string {
  if (v == null) return "—";
  const m = v / 1_000_000;
  return `${m.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M`;
}

function formatGw(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} GW`;
}

function formatGap(gapGw: number, status: string): string {
  const abs = Math.abs(gapGw).toFixed(1);
  if (status === "overcontracted") return `+${abs} GW overcontracted`;
  if (status === "undercontracted") return `\u2212${abs} GW undercontracted`;
  return `${gapGw >= 0 ? "+" : "\u2212"}${abs} GW`;
}
