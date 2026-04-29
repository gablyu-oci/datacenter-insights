import { useMemo, useState, Fragment } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  Filter, X, ExternalLink, MapPin, Zap, Flame, ChevronDown, ChevronUp,
} from "lucide-react";

import { useApi } from "../../hooks/useApi";
import type { GeneratorPermitDto, GeneratorPermitsResponse } from "../../types";
import ErrorPanel from "../shared/ErrorPanel";
import NoDataPanel from "../shared/NoDataPanel";
import CitationFooter from "../shared/CitationFooter";
import CoverageBadge from "../shared/CoverageBadge";

// ── Phase 1.5 fuel-type focus (per PRD §5: data-center-relevant) ────────────
const DC_FUEL_TYPES = ["diesel", "natural_gas", "dual_fuel"] as const;
type FuelType = (typeof DC_FUEL_TYPES)[number];

const FUEL_LABEL: Record<string, string> = {
  diesel: "Diesel",
  natural_gas: "Natural Gas",
  dual_fuel: "Dual Fuel",
};

const FUEL_COLOR: Record<string, string> = {
  diesel: "#f97316",       // orange
  natural_gas: "#3b82f6",  // blue
  dual_fuel: "#a855f7",    // purple
};

const STATUS_COLORS: Record<string, string> = {
  issued: "#22c55e",
  effective: "#22c55e",
  active: "#22c55e",
  pending: "#f59e0b",
  application: "#f59e0b",
  under_review: "#3b82f6",
  draft: "#3b82f6",
  expired: "#94a3b8",
  withdrawn: "#94a3b8",
  denied: "#ef4444",
};

const SOURCE_LABEL: Record<string, string> = {
  epa_echo: "EPA ECHO",
  pjm: "PJM Queue",
  tceq: "TCEQ (TX)",
  va_open_data: "Virginia DEQ",
  ny_socrata: "NY DEC",
  socrata: "Socrata",
};

const CARD_STYLE: React.CSSProperties = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

// ── Helpers ─────────────────────────────────────────────────────────────────

// Real upstream fuel_type values are mixed-case + semicolon-joined
// (e.g. "Natural Gas; Other", "Solar; Storage"). Map heuristically.
function normalizeFuel(raw: string | null | undefined): "diesel" | "natural_gas" | "dual_fuel" | "other" | null {
  if (!raw) return null;
  const s = raw.toLowerCase();
  const hasDiesel = /\b(diesel|oil)\b/.test(s);
  const hasGas = /\b(natural gas|methane)\b/.test(s);
  if (hasDiesel && hasGas) return "dual_fuel";
  if (s.includes("dual fuel") || s.includes("dual-fuel")) return "dual_fuel";
  if (hasDiesel) return "diesel";
  if (hasGas) return "natural_gas";
  return "other";
}

function getFuelColor(fuel: string | null | undefined): string {
  const norm = normalizeFuel(fuel);
  if (!norm || norm === "other") return "#64748b";
  return FUEL_COLOR[norm] ?? "#64748b";
}

function fuelLabel(raw: string | null | undefined): string {
  if (!raw) return "--";
  const norm = normalizeFuel(raw);
  if (norm && norm !== "other") return FUEL_LABEL[norm];
  // Trim long PJM-style multi-fuel strings for readability
  return raw.length > 28 ? raw.slice(0, 26) + "..." : raw;
}

function statusColor(status: string | null | undefined): string {
  if (!status) return "#94a3b8";
  return STATUS_COLORS[status.toLowerCase()] ?? "#94a3b8";
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "--";
  return iso.split("T")[0];
}

function fmtMW(mw: number | null | undefined): string {
  if (mw == null) return "--";
  return mw >= 10 ? mw.toFixed(0) : mw.toFixed(1);
}

function permittee(p: GeneratorPermitDto): string {
  return p.resolved_company_name || p.permittee_raw_name || p.facility_name || "Unknown";
}

// ── Map ─────────────────────────────────────────────────────────────────────

function PermitsMap({
  permits,
  selectedId,
  onSelect,
}: {
  permits: GeneratorPermitDto[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
}) {
  const mappable = permits.filter(p => p.latitude != null && p.longitude != null);

  return (
    <MapContainer
      center={[38.5, -96]}
      zoom={4}
      style={{ width: "100%", height: "100%", borderRadius: 8 }}
      scrollWheelZoom={true}
    >
      <TileLayer
        attribution='&copy; <a href="https://carto.com/">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      />
      {mappable.map((p) => {
        const color = getFuelColor(p.fuel_type);
        const isSelected = selectedId === p.id;
        const mw = p.rated_mw_total ?? 0;
        const radius = Math.max(4, Math.min(16, 4 + Math.sqrt(mw) * 0.5));
        return (
          <CircleMarker
            key={p.id}
            center={[p.latitude!, p.longitude!]}
            radius={radius}
            pathOptions={{
              fillColor: color,
              fillOpacity: isSelected ? 1 : 0.7,
              color: isSelected ? "#ffffff" : color,
              weight: isSelected ? 3 : 1,
            }}
            eventHandlers={{
              click: () => onSelect(isSelected ? null : p.id),
            }}
          >
            <Popup>
              <div style={{ fontFamily: "system-ui, sans-serif", minWidth: 200 }}>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 2 }}>
                  {p.facility_name || p.permittee_raw_name || `Permit #${p.id}`}
                </div>
                <div style={{ fontSize: 11, color: "#666", marginBottom: 6 }}>
                  {permittee(p)}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 11 }}>
                  {p.fuel_type && (
                    <div><strong>Fuel:</strong> {FUEL_LABEL[p.fuel_type.toLowerCase()] ?? p.fuel_type}</div>
                  )}
                  {p.rated_mw_total != null && (
                    <div><strong>MW:</strong> {fmtMW(p.rated_mw_total)}</div>
                  )}
                  {p.state_code && <div><strong>State:</strong> {p.state_code}</div>}
                  {p.county && <div><strong>County:</strong> {p.county}</div>}
                  {p.permit_status && <div><strong>Status:</strong> {p.permit_status}</div>}
                  {p.issued_date && <div><strong>Issued:</strong> {fmtDate(p.issued_date)}</div>}
                </div>
                {p.source_url && (
                  <div style={{ marginTop: 6 }}>
                    <a href={p.source_url} target="_blank" rel="noreferrer"
                      style={{ color: "#3b82f6", fontSize: 11, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 3 }}>
                      <ExternalLink size={10} /> {SOURCE_LABEL[p.source ?? ""] ?? p.source ?? "Source"}
                    </a>
                  </div>
                )}
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}

// ── KPI ─────────────────────────────────────────────────────────────────────

function MetricCard({ label, value, unit, sub, accent, icon: Icon }: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  accent?: string;
  icon: React.ElementType;
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Icon size={14} color={accent ?? "#3b82f6"} />
        <span style={{ color: "#94a3b8", fontSize: "12px" }}>{label}</span>
      </div>
      <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>
        {value}
        {unit && <span style={{ color: "#64748b", fontSize: "13px", marginLeft: "3px" }}>{unit}</span>}
      </div>
      {sub && <div style={{ color: accent ?? "#3b82f6", fontSize: "11px", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ── Main ────────────────────────────────────────────────────────────────────

export default function PermitsTab() {
  // Default to data-center-relevant fuel types per PRD §5.
  const [activeFuels, setActiveFuels] = useState<Set<FuelType>>(
    new Set<FuelType>(DC_FUEL_TYPES),
  );
  const [filterState, setFilterState] = useState<string>("All");
  const [filterSource, setFilterSource] = useState<string>("All");
  const [sortField, setSortField] = useState<"rated_mw_total" | "issued_date" | "permittee">("rated_mw_total");
  const [sortAsc, setSortAsc] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Build query string from active fuel chips.
  const fuelQs = activeFuels.size > 0
    ? Array.from(activeFuels).join(",")
    : "";
  const apiPath = fuelQs
    ? `/api/permits/?fuel_type=${encodeURIComponent(fuelQs)}&page=1&page_size=500`
    : `/api/permits/?page=1&page_size=500`;

  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } =
    useApi<GeneratorPermitsResponse>(apiPath);

  const permits: GeneratorPermitDto[] = data?.data ?? [];
  const total = data?.total ?? permits.length;
  const sourcesIncluded = data?.sources_included ?? [];

  // Hooks must run before any early returns.
  const states = useMemo(
    () => ["All", ...Array.from(new Set(permits.map(p => p.state_code).filter(Boolean) as string[])).sort()],
    [permits],
  );
  const sources = useMemo(
    () => ["All", ...Array.from(new Set(permits.map(p => p.source).filter(Boolean) as string[])).sort()],
    [permits],
  );

  const filtered = useMemo(() => permits.filter(p => {
    if (filterState !== "All" && p.state_code !== filterState) return false;
    if (filterSource !== "All" && p.source !== filterSource) return false;
    return true;
  }), [permits, filterState, filterSource]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      if (sortField === "permittee") {
        const av = permittee(a);
        const bv = permittee(b);
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      if (sortField === "issued_date") {
        const av = a.issued_date ?? "";
        const bv = b.issued_date ?? "";
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const av = a.rated_mw_total ?? 0;
      const bv = b.rated_mw_total ?? 0;
      return sortAsc ? av - bv : bv - av;
    });
  }, [filtered, sortField, sortAsc]);

  // Aggregate MW by state (top 8)
  const byState = useMemo(() => {
    const map: Record<string, { mw: number; count: number }> = {};
    filtered.forEach(p => {
      const st = p.state_code ?? "Unknown";
      if (!map[st]) map[st] = { mw: 0, count: 0 };
      map[st].mw += p.rated_mw_total ?? 0;
      map[st].count += 1;
    });
    return Object.entries(map)
      .map(([state, v]) => ({ state, mw: Math.round(v.mw), count: v.count }))
      .sort((a, b) => b.mw - a.mw)
      .slice(0, 8);
  }, [filtered]);

  // Aggregate by fuel type
  const byFuel = useMemo(() => {
    const map: Record<string, { mw: number; count: number }> = {};
    filtered.forEach(p => {
      const f = (p.fuel_type ?? "unknown").toLowerCase();
      if (!map[f]) map[f] = { mw: 0, count: 0 };
      map[f].mw += p.rated_mw_total ?? 0;
      map[f].count += 1;
    });
    return Object.entries(map)
      .map(([fuel, v]) => ({ fuel, mw: Math.round(v.mw), count: v.count }))
      .sort((a, b) => b.mw - a.mw);
  }, [filtered]);

  // KPIs
  const totalMW = filtered.reduce((s, p) => s + (p.rated_mw_total ?? 0), 0);
  const uniqueStates = new Set(filtered.map(p => p.state_code).filter(Boolean)).size;
  const resolvedParents = filtered.filter(p => p.resolved_company_id != null).length;

  const toggleSort = (field: typeof sortField) => {
    if (sortField === field) setSortAsc(v => !v);
    else { setSortField(field); setSortAsc(false); }
  };

  const toggleFuel = (f: FuelType) => {
    setActiveFuels(prev => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  };

  // Now safe to short-circuit.
  if (loading) return <Loader />;
  if (error) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} lastAttempt={lastFetchedAt} />
      </div>
    );
  }
  if (permits.length === 0) {
    return (
      <div style={{ padding: "24px" }}>
        <NoDataPanel
          pillar="Generator Permits"
          reason="No permits matched the active filters. Try enabling additional fuel types or check ingestion status."
        />
      </div>
    );
  }

  const filterSelectStyle: React.CSSProperties = {
    background: "#0f172a",
    border: "1px solid #334155",
    borderRadius: 6,
    color: "white",
    padding: "6px 10px",
    fontSize: "12px",
    cursor: "pointer",
  };

  const sourceLabels = sourcesIncluded.map(s => SOURCE_LABEL[s] ?? s);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Header banner */}
      <div style={{
        background: "linear-gradient(135deg, #0a1628 0%, #0f2240 100%)",
        border: "1px solid #1d4ed8",
        borderRadius: 10,
        padding: "12px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Flame size={16} color="#f97316" />
          <span style={{ color: "white", fontWeight: 600, fontSize: 14 }}>
            Backup-Generator Permits (Construction Ground Truth)
          </span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#0f172a", border: "1px solid #1d4ed8", color: "#60a5fa", fontSize: "10px", fontWeight: 600 }}>
            {total.toLocaleString()} permits in DB
          </span>
          <CoverageBadge pillar="permits" />
        </div>
        <div style={{ color: "#64748b", fontSize: "11px" }}>
          Showing {filtered.length} of {permits.length} loaded {permits.length < total ? `(of ${total.toLocaleString()} total)` : ""}
        </div>
      </div>

      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <MetricCard label="Permits Shown" value={String(filtered.length)} sub={`${sourcesIncluded.length} sources`} accent="#3b82f6" icon={Filter} />
        <MetricCard label="Total Generator MW" value={Math.round(totalMW).toLocaleString()} unit="MW" sub="aggregated nameplate" accent="#f97316" icon={Zap} />
        <MetricCard label="States Covered" value={String(uniqueStates)} sub="geographic coverage" accent="#22c55e" icon={MapPin} />
        <MetricCard label="Parent Resolved" value={String(resolvedParents)} sub={`${filtered.length > 0 ? ((resolvedParents / filtered.length) * 100).toFixed(0) : 0}% of shown`} accent="#a855f7" icon={Zap} />
      </div>

      {/* Filter bar */}
      <div style={{ ...CARD_STYLE, padding: "14px 18px", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Filter size={13} color="#64748b" />
        <span style={{ color: "#64748b", fontSize: "12px", marginRight: 4 }}>Fuel:</span>
        {DC_FUEL_TYPES.map(f => {
          const active = activeFuels.has(f);
          return (
            <button
              key={f}
              onClick={() => toggleFuel(f)}
              style={{
                padding: "5px 12px",
                borderRadius: 999,
                border: `1px solid ${active ? FUEL_COLOR[f] : "#334155"}`,
                background: active ? `${FUEL_COLOR[f]}22` : "#0f172a",
                color: active ? FUEL_COLOR[f] : "#94a3b8",
                fontSize: "11px",
                fontWeight: 600,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <span style={{
                display: "inline-block",
                width: 7, height: 7, borderRadius: "50%",
                background: FUEL_COLOR[f],
                opacity: active ? 1 : 0.4,
              }} />
              {FUEL_LABEL[f]}
            </button>
          );
        })}
        <span style={{ width: 1, height: 18, background: "#334155", margin: "0 6px" }} />
        <span style={{ color: "#64748b", fontSize: "12px" }}>State:</span>
        <select value={filterState} onChange={e => setFilterState(e.target.value)} style={filterSelectStyle}>
          {states.map(s => <option key={s}>{s}</option>)}
        </select>
        <span style={{ color: "#64748b", fontSize: "12px" }}>Source:</span>
        <select value={filterSource} onChange={e => setFilterSource(e.target.value)} style={filterSelectStyle}>
          {sources.map(s => <option key={s}>{s === "All" ? "All" : (SOURCE_LABEL[s] ?? s)}</option>)}
        </select>
        {(filterState !== "All" || filterSource !== "All" || activeFuels.size !== DC_FUEL_TYPES.length) && (
          <button
            onClick={() => {
              setFilterState("All");
              setFilterSource("All");
              setActiveFuels(new Set<FuelType>(DC_FUEL_TYPES));
            }}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 6, background: "#1e293b", border: "1px solid #334155", color: "#94a3b8", cursor: "pointer", fontSize: "12px" }}
          >
            <X size={11} /> Reset
          </button>
        )}
        <span style={{ marginLeft: "auto", color: "#64748b", fontSize: "11px" }}>{filtered.length} permits</span>
      </div>

      {/* Map */}
      <div style={{ ...CARD_STYLE, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #334155", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Permit Locations</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "3px 0 0" }}>
              Bubble size proportional to nameplate MW -- Colored by fuel type -- Click marker to inspect
            </p>
          </div>
          {/* Fuel-color legend */}
          <div style={{ display: "flex", gap: 12, alignItems: "center", fontSize: "11px", color: "#94a3b8" }}>
            {DC_FUEL_TYPES.map(f => (
              <span key={f} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: FUEL_COLOR[f] }} />
                {FUEL_LABEL[f]}
              </span>
            ))}
          </div>
        </div>
        <div style={{ height: 440 }}>
          <PermitsMap permits={filtered} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
      </div>

      {/* Charts row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {/* By State */}
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 320 }}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: "0 0 4px" }}>Generator MW by State (Top 8)</h3>
          <p style={{ color: "#64748b", fontSize: "11px", margin: "0 0 14px" }}>
            Aggregated nameplate capacity from real generator-permit filings
          </p>
          {byState.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={byState} layout="vertical" margin={{ left: 4, right: 24, top: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit=" MW" />
                <YAxis type="category" dataKey="state" tick={{ fill: "#94a3b8", fontSize: 11 }} width={36} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "white" }}
                  formatter={(v, _n, props) => [
                    `${Number(v).toLocaleString()} MW (${(props as { payload?: { count?: number } })?.payload?.count ?? 0} permits)`, "Capacity",
                  ]}
                />
                <Bar dataKey="mw" radius={[0, 4, 4, 0]}>
                  {byState.map((_, i) => (
                    <Cell key={i} fill={`hsl(${20 + i * 14}, 80%, ${60 - i * 3}%)`} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>No data to display.</div>
          )}
          <CitationFooter
            sources={sourceLabels.length > 0 ? sourceLabels : ["EPA ECHO + State APIs"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={undefined}
          />
        </div>

        {/* By Fuel */}
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 280 }}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: "0 0 4px" }}>MW by Fuel Type</h3>
          <p style={{ color: "#64748b", fontSize: "11px", margin: "0 0 14px" }}>
            Diesel = backup; natural-gas / dual-fuel = primary or hybrid
          </p>
          {byFuel.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={byFuel} layout="vertical" margin={{ left: 4, right: 24, top: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit=" MW" />
                <YAxis type="category" dataKey="fuel" tick={{ fill: "#94a3b8", fontSize: 11 }} width={100}
                  tickFormatter={(v: string) => FUEL_LABEL[v] ?? v} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "white" }}
                  formatter={(v, _n, props) => [
                    `${Number(v).toLocaleString()} MW (${(props as { payload?: { count?: number } })?.payload?.count ?? 0} permits)`, "Capacity",
                  ]}
                  labelFormatter={(v: string) => FUEL_LABEL[v] ?? v}
                />
                <Bar dataKey="mw" radius={[0, 4, 4, 0]}>
                  {byFuel.map((entry, i) => (
                    <Cell key={i} fill={getFuelColor(entry.fuel)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>No data to display.</div>
          )}
          <CitationFooter
            sources={sourceLabels.length > 0 ? sourceLabels : ["EPA ECHO + State APIs"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
          />
        </div>
      </div>

      {/* Permits table */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Permit Records</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
              {sorted.length} permits -- click column headers to sort -- click row to expand raw filing
            </p>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                {[
                  { label: "Permittee (resolved parent)", field: "permittee" as const },
                  { label: "Facility", field: null },
                  { label: "State", field: null },
                  { label: "County FIPS", field: null },
                  { label: "Fuel", field: null },
                  { label: "MW", field: "rated_mw_total" as const },
                  { label: "Status", field: null },
                  { label: "Issued", field: "issued_date" as const },
                  { label: "Source", field: null },
                ].map(({ label, field }) => (
                  <th key={label}
                    onClick={field ? () => toggleSort(field) : undefined}
                    style={{
                      color: "#64748b", textAlign: "left", padding: "8px 12px",
                      fontWeight: 500, whiteSpace: "nowrap",
                      cursor: field ? "pointer" : "default",
                      userSelect: "none",
                    }}
                  >
                    {label}
                    {field && sortField === field && (
                      sortAsc ? <ChevronUp size={10} style={{ display: "inline", marginLeft: 3 }} /> : <ChevronDown size={10} style={{ display: "inline", marginLeft: 3 }} />
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, 50).map(p => {
                const fc = getFuelColor(p.fuel_type);
                const isExpanded = expandedId === p.id;
                const isSelected = selectedId === p.id;
                return (
                  <Fragment key={p.id}>
                    <tr
                      onClick={() => {
                        setSelectedId(isSelected ? null : p.id);
                        setExpandedId(isExpanded ? null : p.id);
                      }}
                      style={{
                        borderBottom: isExpanded ? "none" : "1px solid #1e293b",
                        cursor: "pointer",
                        background: isSelected ? "#162032" : "transparent",
                        transition: "background 0.1s",
                      }}
                    >
                      <td style={{ padding: "9px 12px", color: "#e2e8f0", fontWeight: 500 }}>
                        {p.resolved_company_name ? (
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                            <span style={{
                              padding: "2px 7px", borderRadius: 3, background: "#1e3a8a22",
                              color: "#60a5fa", fontSize: "10px", fontWeight: 700,
                            }}>{p.resolved_company_name}</span>
                            {p.permittee_raw_name && p.permittee_raw_name !== p.resolved_company_name && (
                              <span style={{ color: "#64748b", fontSize: "10px" }}>
                                -- via {p.permittee_raw_name}
                              </span>
                            )}
                          </span>
                        ) : (
                          <span style={{ color: "#94a3b8" }}>{p.permittee_raw_name ?? "Unknown"}</span>
                        )}
                      </td>
                      <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{p.facility_name ?? "--"}</td>
                      <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{p.state_code ?? "--"}</td>
                      <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{p.county ?? "--"}</td>
                      <td style={{ padding: "9px 12px" }}>
                        {p.fuel_type ? (
                          <span style={{
                            padding: "2px 8px", borderRadius: 4,
                            background: `${fc}22`, color: fc,
                            fontSize: "11px", fontWeight: 600,
                          }}>
                            {FUEL_LABEL[p.fuel_type.toLowerCase()] ?? p.fuel_type}
                          </span>
                        ) : <span style={{ color: "#64748b" }}>--</span>}
                      </td>
                      <td style={{ padding: "9px 12px", color: "white", fontWeight: 700 }}>
                        {fmtMW(p.rated_mw_total)}
                        {p.num_units != null && p.num_units > 1 && (
                          <span style={{ color: "#64748b", fontSize: "10px", marginLeft: 4 }}>
                            ({p.num_units} units)
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "9px 12px" }}>
                        <span style={{ color: statusColor(p.permit_status), fontSize: "11px" }}>
                          &#x25CF; {p.permit_status ?? "--"}
                        </span>
                      </td>
                      <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>
                        {fmtDate(p.issued_date)}
                      </td>
                      <td style={{ padding: "9px 12px" }} onClick={(e) => e.stopPropagation()}>
                        {p.source_url ? (
                          <a href={p.source_url} target="_blank" rel="noreferrer"
                            style={{ color: "#3b82f6", display: "inline-flex", alignItems: "center", gap: 4, textDecoration: "none", fontSize: "11px" }}>
                            <ExternalLink size={11} />
                            {SOURCE_LABEL[p.source ?? ""] ?? p.source ?? "Source"}
                          </a>
                        ) : (
                          <span style={{ color: "#64748b", fontSize: "11px" }}>
                            {SOURCE_LABEL[p.source ?? ""] ?? p.source ?? "--"}
                          </span>
                        )}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr style={{ borderBottom: "1px solid #1e293b", background: "#162032" }}>
                        <td colSpan={9} style={{ padding: "12px 16px 16px 24px" }}>
                          <ExpandedPermit p={p} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          {sorted.length > 50 && (
            <div style={{ color: "#64748b", fontSize: "12px", padding: "8px 12px" }}>
              Showing 50 of {sorted.length} permits
            </div>
          )}
        </div>
        <CitationFooter
          sources={sourceLabels.length > 0 ? sourceLabels : ["EPA ECHO + State APIs"]}
          retrievedAt={lineage?.retrieved_at}
          confidence={lineage?.confidence}
        />
      </div>
    </div>
  );
}

// ── Expanded row ────────────────────────────────────────────────────────────

function ExpandedPermit({ p }: { p: GeneratorPermitDto }) {
  const fields: Array<[string, string | number | null | undefined]> = [
    ["Source permit ID", p.source_permit_id],
    ["FRS ID", p.frs_id],
    ["NAICS code", p.naics_code],
    ["Issued", fmtDate(p.issued_date)],
    ["Expires", fmtDate(p.expiry_date)],
    ["Latitude", p.latitude],
    ["Longitude", p.longitude],
    ["Rated MW (total)", p.rated_mw_total],
    ["# Units", p.num_units],
    ["County FIPS", p.county_fips],
    ["Confidence", p.confidence != null ? `${(p.confidence * 100).toFixed(0)}%` : null],
    ["Created", fmtDate(p.created_at)],
  ];
  return (
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap", color: "#cbd5e1", fontSize: 12 }}>
      <div style={{ flex: 1, minWidth: 280 }}>
        <div style={{ color: "#94a3b8", fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.6 }}>
          Filing details
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "150px 1fr", rowGap: 4, columnGap: 12 }}>
          {fields.map(([k, v]) => (
            <Fragment key={k}>
              <span style={{ color: "#64748b" }}>{k}</span>
              <span style={{ color: "#e2e8f0" }}>{v == null || v === "--" ? "--" : String(v)}</span>
            </Fragment>
          ))}
        </div>
      </div>
      {p.raw_payload && (
        <div style={{ flex: 1, minWidth: 320 }}>
          <div style={{ color: "#94a3b8", fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.6 }}>
            Raw payload (parser output)
          </div>
          <pre style={{
            background: "#0f172a",
            border: "1px solid #1e293b",
            borderRadius: 6,
            padding: 10,
            fontSize: 10,
            color: "#94a3b8",
            maxHeight: 220,
            overflow: "auto",
            margin: 0,
          }}>
            {JSON.stringify(p.raw_payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function Loader() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>
      Loading permit data...
    </div>
  );
}
