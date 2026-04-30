/**
 * TriangulationTab — Phase 2 (AC4).
 *
 * The original "multi-layer Power Gap" placeholder was vapor — L2 (GPU
 * compute), L3 (NIC/optics), and L4 (county permits) all require paid
 * data feeds we have not procured. This rewrite ships ONLY Layer 1
 * (Contracted Power, GW per company × state), which we can compute
 * honestly today by summing sites + curated_deals + edgar_extractions.
 *
 * Endpoint: GET /api/triangulation/l1
 */
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import { Info, AlertTriangle } from "lucide-react";
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

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
} as const;

const LAYERS = [
  { layer: "L1", label: "Contracted Power",     desc: "GW signed with utilities (sites + curated deals + EDGAR)", status: "live"    },
  { layer: "L2", label: "GPU Compute Demand",   desc: "Power draw × utilization (NVIDIA shipments — paid data)",   status: "blocked" },
  { layer: "L3", label: "NIC/Optics Signals",   desc: "Coherent / Lumentum order books — paid data",                status: "blocked" },
  { layer: "L4", label: "Permit Ground Truth",  desc: "County-level construction permits — paid data",              status: "blocked" },
];

export default function TriangulationTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } =
    useApi<L1Response>("/api/triangulation/l1");

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
          {LAYERS.map(({ layer, label, desc, status }) => {
            const isLive = status === "live";
            return (
              <div key={layer} style={{
                background: "#0f172a",
                border: `1px solid ${isLive ? "#22c55e" : "#334155"}`,
                borderRadius: "8px",
                padding: "12px 16px",
                flex: 1,
                minWidth: 180,
                opacity: isLive ? 1 : 0.55,
              }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: "6px", marginBottom: "4px",
                }}>
                  <span style={{
                    color: isLive ? "#22c55e" : "#64748b",
                    fontSize: "11px", fontWeight: 700,
                  }}>{layer}</span>
                  <span style={{
                    color: isLive ? "#22c55e" : "#94a3b8",
                    fontSize: "10px",
                    border: `1px solid ${isLive ? "#22c55e44" : "#33415588"}`,
                    borderRadius: "4px",
                    padding: "1px 6px",
                  }}>
                    {isLive ? "LIVE" : "Paid data required"}
                  </span>
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
        <>
          {/* L1 grouped bar chart: total GW per company, top 10 */}
          <L1Chart records={records} />

          {/* L1 detail table */}
          <L1Table records={records} />
        </>
      )}

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

function L1Table({ records }: { records: L1Record[] }) {
  return (
    <div style={CARD_STYLE}>
      <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: "0 0 12px" }}>
        L1 Detail — Company × State
      </h3>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155" }}>
              <Th>Company</Th>
              <Th>State</Th>
              <Th align="right">GW Total</Th>
              <Th>Sources</Th>
              <Th align="right">Confidence</Th>
            </tr>
          </thead>
          <tbody>
            {records.map((r, i) => (
              <tr key={`${r.company}-${r.state}-${i}`}
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
          </tbody>
        </table>
      </div>
      <p style={{ color: "#64748b", fontSize: "11px", marginTop: "12px" }}>
        Confidence rises with the number of corroborating sources (0.50 base
        +0.15 if ≥2 sources +0.10 if ≥3 sources, capped at 0.85).
      </p>
    </div>
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
