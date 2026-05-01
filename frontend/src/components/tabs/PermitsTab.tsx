import { useMemo, useState, Fragment } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
// react-leaflet-google-layer ships CJS; force-unwrap the default export so
// React receives a component, not the wrapper module object.
import RLGLImport from "react-leaflet-google-layer";
const ReactLeafletGoogleLayer =
  (RLGLImport as unknown as { default?: typeof RLGLImport }).default ?? RLGLImport;
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  Filter, X, ExternalLink, MapPin, Zap, Flame, Building2, ChevronDown, ChevronUp,
} from "lucide-react";

import { useApi } from "../../hooks/useApi";
import type {
  GeneratorPermitDto,
  GeneratorPermitsResponse,
  BuildingPermitDto,
  BuildingPermitsResponse,
} from "../../types";
import ErrorPanel from "../shared/ErrorPanel";
import NoDataPanel from "../shared/NoDataPanel";
import CitationFooter from "../shared/CitationFooter";
import CoverageBadge from "../shared/CoverageBadge";

const GMAPS_KEY = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string) || "";

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
  loudoun_va: "Loudoun VA",
  mesa_az: "Mesa AZ",
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

function isIssued(status: string | null | undefined): boolean {
  return !!status && status.toLowerCase() === "issued";
}

function fmtUSD(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`;
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

// ── Generator Map ───────────────────────────────────────────────────────────

function GeneratorMap({
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
      {GMAPS_KEY ? (
        <ReactLeafletGoogleLayer apiKey={GMAPS_KEY} type="satellite" />
      ) : (
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />
      )}
      <MarkerClusterGroup
        chunkedLoading
        maxClusterRadius={60}
        disableClusteringAtZoom={10}
        spiderfyOnMaxZoom={true}
        showCoverageOnHover={false}
      >
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
                fillOpacity: isSelected ? 1 : 0.85,
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
                      <div><strong>Fuel:</strong> {fuelLabel(p.fuel_type)}</div>
                    )}
                    {p.rated_mw_total != null && (
                      <div><strong>MW:</strong> {fmtMW(p.rated_mw_total)}</div>
                    )}
                    {p.state_code && <div><strong>State:</strong> {p.state_code}</div>}
                    {p.county_fips && <div><strong>County FIPS:</strong> {p.county_fips}</div>}
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
      </MarkerClusterGroup>
    </MapContainer>
  );
}

// ── Building Map ────────────────────────────────────────────────────────────

function BuildingMap({
  permits,
  selectedId,
  onSelect,
}: {
  permits: BuildingPermitDto[];
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
      {GMAPS_KEY ? (
        <ReactLeafletGoogleLayer apiKey={GMAPS_KEY} type="satellite" />
      ) : (
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />
      )}
      <MarkerClusterGroup
        chunkedLoading
        maxClusterRadius={60}
        disableClusteringAtZoom={10}
        spiderfyOnMaxZoom={true}
        showCoverageOnHover={false}
      >
        {mappable.map((p) => {
          const color = isIssued(p.permit_status) ? "#22c55e" : "#f59e0b";
          const isSelected = selectedId === p.id;
          // Bubble radius scales with valuation; floor at 5px, ceiling at 16px.
          const v = p.valuation_usd ?? 0;
          const radius = Math.max(5, Math.min(16, 5 + Math.log10(Math.max(1, v / 1_000_000)) * 3));
          return (
            <CircleMarker
              key={p.id}
              center={[p.latitude!, p.longitude!]}
              radius={radius}
              pathOptions={{
                fillColor: color,
                fillOpacity: isSelected ? 1 : 0.85,
                color: isSelected ? "#ffffff" : color,
                weight: isSelected ? 3 : 1,
              }}
              eventHandlers={{
                click: () => onSelect(isSelected ? null : p.id),
              }}
            >
              <Popup>
                <div style={{ fontFamily: "system-ui, sans-serif", minWidth: 220 }}>
                  <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 2 }}>
                    {p.applicant_name || p.source_permit_id || `Permit #${p.id}`}
                  </div>
                  <div style={{ fontSize: 11, color: "#666", marginBottom: 6 }}>
                    {p.address ?? "--"}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 11 }}>
                    {p.permit_type && <div><strong>Type:</strong> {p.permit_type}</div>}
                    {p.permit_status && <div><strong>Status:</strong> {p.permit_status}</div>}
                    {p.county && <div><strong>County:</strong> {p.county}</div>}
                    {p.state && <div><strong>State:</strong> {p.state}</div>}
                    {p.issued_date && <div><strong>Issued:</strong> {fmtDate(p.issued_date)}</div>}
                    {p.valuation_usd != null && (
                      <div><strong>Value:</strong> {fmtUSD(p.valuation_usd)}</div>
                    )}
                  </div>
                  <div style={{ marginTop: 6, fontSize: 11, color: "#3b82f6" }}>
                    {SOURCE_LABEL[p.source ?? ""] ?? p.source ?? "--"}
                  </div>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MarkerClusterGroup>
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

type PermitMode = "generator" | "building";

export default function PermitsTab() {
  // AC3: Toggle between generator (existing) and building-permit views.
  const [mode, setMode] = useState<PermitMode>("generator");

  // Building-permit fetch window. Default 365d; the empty-state CTA bumps to 730.
  const [buildingDays, setBuildingDays] = useState<number>(365);

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
  // Free-text search across permittee / facility / state / county / source / fuel / status
  const [searchGenerator, setSearchGenerator] = useState<string>("");

  // Building-permit table sort
  const [buildingSortField, setBuildingSortField] = useState<
    "issued_date" | "valuation_usd" | "applicant_name" | "permit_status"
  >("issued_date");
  const [buildingSortAsc, setBuildingSortAsc] = useState(false);
  const [selectedBuildingId, setSelectedBuildingId] = useState<number | null>(null);
  // Free-text search across source / county / state / permit_type / status / applicant / address
  const [searchBuilding, setSearchBuilding] = useState<string>("");

  // Generator fetch (kept identical to prior behavior).
  const generatorPath = `/api/permits/?page=1&page_size=10000`;
  const {
    data: genData,
    loading: genLoading,
    error: genError,
    errorInfo: genErrorInfo,
    retry: genRetry,
    lastFetchedAt: genLastFetchedAt,
    lineage: genLineage,
  } = useApi<GeneratorPermitsResponse>(generatorPath);

  // Building fetch (parallel; runs unconditionally so toggling is instant).
  const buildingPath = `/api/permits/building?days=${buildingDays}`;
  const {
    data: bldData,
    loading: bldLoading,
    error: bldError,
    errorInfo: bldErrorInfo,
    retry: bldRetry,
    lastFetchedAt: bldLastFetchedAt,
    lineage: bldLineage,
    coverage: bldCoverage,
  } = useApi<BuildingPermitsResponse>(buildingPath);

  const permits: GeneratorPermitDto[] = genData?.data ?? [];
  const total = genData?.total ?? permits.length;
  const sourcesIncluded = genData?.sources_included ?? [];

  const buildingPermits: BuildingPermitDto[] = bldData?.data ?? [];
  const buildingTotal = bldData?.total ?? buildingPermits.length;

  // Hooks must run before any early returns.
  const states = useMemo(
    () => ["All", ...Array.from(new Set(permits.map(p => p.state_code).filter(Boolean) as string[])).sort()],
    [permits],
  );
  const sources = useMemo(
    () => ["All", ...Array.from(new Set(permits.map(p => p.source).filter(Boolean) as string[])).sort()],
    [permits],
  );

  // Hoisted to satisfy Rules of Hooks — must run on every render whether
  // we early-return for loading/error/empty in generator mode or not.
  const buildingSources = useMemo(
    () => Array.from(new Set(buildingPermits.map(p => p.source).filter(Boolean) as string[])),
    [buildingPermits],
  );

  // Charts/list filter for generator mode.
  const filtered = useMemo(() => permits.filter(p => {
    if (filterState !== "All" && p.state_code !== filterState) return false;
    if (filterSource !== "All" && p.source !== filterSource) return false;
    if (activeFuels.size > 0) {
      const norm = normalizeFuel(p.fuel_type);
      if (!norm || !activeFuels.has(norm as FuelType)) return false;
    }
    return true;
  }), [permits, filterState, filterSource, activeFuels]);

  // Map filter for generator mode (no fuel filter).
  const mapFiltered = useMemo(() => permits.filter(p => {
    if (filterState !== "All" && p.state_code !== filterState) return false;
    if (filterSource !== "All" && p.source !== filterSource) return false;
    return true;
  }), [permits, filterState, filterSource]);

  const sorted = useMemo(() => {
    const q = searchGenerator.trim().toLowerCase();
    const matches = (p: GeneratorPermitDto) => {
      if (!q) return true;
      const fields = [
        p.resolved_company_name, p.permittee_raw_name, p.facility_name,
        p.state_code, p.county_fips, p.source, p.fuel_type, p.permit_status,
      ];
      return fields.some(v => v && v.toLowerCase().includes(q));
    };
    return [...filtered]
      .filter(matches)
      .sort((a, b) => {
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
  }, [filtered, sortField, sortAsc, searchGenerator]);

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

  // Building aggregations
  const byCounty = useMemo(() => {
    const map: Record<string, number> = {};
    buildingPermits.forEach(p => {
      const c = p.county ?? p.jurisdiction ?? "Unknown";
      map[c] = (map[c] ?? 0) + 1;
    });
    return Object.entries(map)
      .map(([county, count]) => ({ county, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [buildingPermits]);

  const sortedBuildings = useMemo(() => {
    const q = searchBuilding.trim().toLowerCase();
    const matches = (p: BuildingPermitDto) => {
      if (!q) return true;
      const fields = [
        p.source, p.county, p.state, p.permit_type, p.permit_status,
        p.applicant_name, p.address, p.jurisdiction, p.source_permit_id,
      ];
      return fields.some(v => v && v.toLowerCase().includes(q));
    };
    return [...buildingPermits]
      .filter(matches)
      .sort((a, b) => {
        const dir = buildingSortAsc ? 1 : -1;
        switch (buildingSortField) {
          case "issued_date": {
            const av = a.issued_date ?? "";
            const bv = b.issued_date ?? "";
            return av.localeCompare(bv) * dir;
          }
          case "valuation_usd": {
            const av = a.valuation_usd ?? 0;
            const bv = b.valuation_usd ?? 0;
            return (av - bv) * dir;
          }
          case "applicant_name": {
            const av = a.applicant_name ?? "";
            const bv = b.applicant_name ?? "";
            return av.localeCompare(bv) * dir;
          }
          case "permit_status": {
            const av = a.permit_status ?? "";
            const bv = b.permit_status ?? "";
            return av.localeCompare(bv) * dir;
          }
        }
      });
  }, [buildingPermits, buildingSortField, buildingSortAsc, searchBuilding]);

  // Generator KPIs
  const totalMW = filtered.reduce((s, p) => s + (p.rated_mw_total ?? 0), 0);
  const uniqueStates = new Set(filtered.map(p => p.state_code).filter(Boolean)).size;
  const resolvedParents = filtered.filter(p => p.resolved_company_id != null).length;

  // Building KPIs
  const buildingIssued = buildingPermits.filter(p => isIssued(p.permit_status)).length;
  const buildingPending = buildingPermits.length - buildingIssued;
  const buildingValuation = buildingPermits.reduce(
    (s, p) => s + (p.valuation_usd ?? 0), 0,
  );

  const toggleSort = (field: typeof sortField) => {
    if (sortField === field) setSortAsc(v => !v);
    else { setSortField(field); setSortAsc(false); }
  };

  const toggleBuildingSort = (field: typeof buildingSortField) => {
    if (buildingSortField === field) setBuildingSortAsc(v => !v);
    else { setBuildingSortField(field); setBuildingSortAsc(false); }
  };

  const toggleFuel = (f: FuelType) => {
    setActiveFuels(prev => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  };

  // ── Toggle UI ──────────────────────────────────────────────────────────────
  const toggleBar = (
    <div
      role="tablist"
      aria-label="Permit dataset"
      style={{
        display: "inline-flex",
        background: "#0f172a",
        border: "1px solid #334155",
        borderRadius: 999,
        padding: 3,
        gap: 2,
        alignSelf: "flex-start",
      }}
    >
      {[
        { id: "generator" as const, label: "Generator Permits", icon: Flame, accent: "#f97316" },
        { id: "building" as const, label: "Building Permits", icon: Building2, accent: "#22c55e" },
      ].map(opt => {
        const active = mode === opt.id;
        const Icon = opt.icon;
        return (
          <button
            key={opt.id}
            role="tab"
            aria-selected={active}
            onClick={() => setMode(opt.id)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              borderRadius: 999,
              border: "none",
              background: active ? opt.accent : "transparent",
              color: active ? "white" : "#94a3b8",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
              transition: "background 0.15s",
            }}
          >
            <Icon size={13} />
            {opt.label}
          </button>
        );
      })}
    </div>
  );

  // ── Loading / error gating per active mode ────────────────────────────────
  // Generator path errors only block generator mode; building path errors only
  // block building mode. Unconditional fetches mean toggling is instant once
  // both have resolved.
  if (mode === "generator") {
    if (genLoading) return <Loader />;
    if (genError) {
      return (
        <div style={{ padding: "24px" }}>
          <div style={{ marginBottom: 16 }}>{toggleBar}</div>
          <ErrorPanel title={genErrorInfo?.title} message={genErrorInfo?.message} onRetry={genRetry} lastAttempt={genLastFetchedAt} />
        </div>
      );
    }
    if (permits.length === 0) {
      return (
        <div style={{ padding: "24px" }}>
          <div style={{ marginBottom: 16 }}>{toggleBar}</div>
          <NoDataPanel
            pillar="Generator Permits"
            reason="No permits matched the active filters. Try enabling additional fuel types or check ingestion status."
          />
        </div>
      );
    }
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

  // ── Building-mode coverage strings ────────────────────────────────────────
  // (buildingSources useMemo is hoisted to the top of the component above
  // any early returns -- Rules of Hooks. The plain-JS derivations below
  // are safe to compute here.)
  const buildingStatesIncluded = bldCoverage?.states_included ?? [];
  const buildingCoverageNote =
    (bldCoverage as unknown as { note?: string } | null)?.note ??
    (buildingStatesIncluded.length === 0
      ? "Building permits from Loudoun VA + Mesa AZ -- Grant WA pending free-API"
      : null);
  const buildingSourceLabels =
    buildingSources.length > 0
      ? buildingSources.map(s => SOURCE_LABEL[s] ?? s)
      : ["Loudoun VA + Mesa AZ"];

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Toggle */}
      {toggleBar}

      {mode === "generator" ? (
        <GeneratorView
          toggleBar={null}
          permits={permits}
          filtered={filtered}
          sorted={sorted}
          mapFiltered={mapFiltered}
          byState={byState}
          byFuel={byFuel}
          totalMW={totalMW}
          uniqueStates={uniqueStates}
          resolvedParents={resolvedParents}
          total={total}
          sourcesIncluded={sourcesIncluded}
          sourceLabels={sourceLabels}
          lineage={genLineage}
          states={states}
          sources={sources}
          filterState={filterState}
          setFilterState={setFilterState}
          filterSource={filterSource}
          setFilterSource={setFilterSource}
          activeFuels={activeFuels}
          setActiveFuels={setActiveFuels}
          toggleFuel={toggleFuel}
          sortField={sortField}
          sortAsc={sortAsc}
          toggleSort={toggleSort}
          selectedId={selectedId}
          setSelectedId={setSelectedId}
          expandedId={expandedId}
          setExpandedId={setExpandedId}
          filterSelectStyle={filterSelectStyle}
          search={searchGenerator}
          setSearch={setSearchGenerator}
          unfilteredCount={filtered.length}
        />
      ) : (
        <BuildingView
          loading={bldLoading}
          error={bldError}
          errorInfo={bldErrorInfo}
          retry={bldRetry}
          lastFetchedAt={bldLastFetchedAt}
          buildingPermits={buildingPermits}
          sortedBuildings={sortedBuildings}
          buildingTotal={buildingTotal}
          buildingIssued={buildingIssued}
          buildingPending={buildingPending}
          buildingValuation={buildingValuation}
          byCounty={byCounty}
          buildingDays={buildingDays}
          setBuildingDays={setBuildingDays}
          buildingSortField={buildingSortField}
          buildingSortAsc={buildingSortAsc}
          toggleBuildingSort={toggleBuildingSort}
          selectedBuildingId={selectedBuildingId}
          setSelectedBuildingId={setSelectedBuildingId}
          buildingStatesIncluded={buildingStatesIncluded}
          buildingCoverageNote={buildingCoverageNote}
          buildingSourceLabels={buildingSourceLabels}
          lineage={bldLineage}
          search={searchBuilding}
          setSearch={setSearchBuilding}
          unfilteredCount={buildingPermits.length}
        />
      )}
    </div>
  );
}

// ── Generator-mode view (existing UI extracted into a sub-component) ────────

function GeneratorView(props: {
  toggleBar: React.ReactNode;
  permits: GeneratorPermitDto[];
  filtered: GeneratorPermitDto[];
  sorted: GeneratorPermitDto[];
  mapFiltered: GeneratorPermitDto[];
  byState: { state: string; mw: number; count: number }[];
  byFuel: { fuel: string; mw: number; count: number }[];
  totalMW: number;
  uniqueStates: number;
  resolvedParents: number;
  total: number;
  sourcesIncluded: string[];
  sourceLabels: string[];
  lineage: { source_url?: string; retrieved_at?: string; confidence?: number } | null;
  states: string[];
  sources: string[];
  filterState: string;
  setFilterState: (s: string) => void;
  filterSource: string;
  setFilterSource: (s: string) => void;
  activeFuels: Set<FuelType>;
  setActiveFuels: (s: Set<FuelType>) => void;
  toggleFuel: (f: FuelType) => void;
  sortField: "rated_mw_total" | "issued_date" | "permittee";
  sortAsc: boolean;
  toggleSort: (f: "rated_mw_total" | "issued_date" | "permittee") => void;
  selectedId: number | null;
  setSelectedId: (id: number | null) => void;
  expandedId: number | null;
  setExpandedId: (id: number | null) => void;
  filterSelectStyle: React.CSSProperties;
  search: string;
  setSearch: (s: string) => void;
  unfilteredCount: number;
}) {
  const {
    permits, filtered, sorted, mapFiltered, byState, byFuel,
    totalMW, uniqueStates, resolvedParents, total, sourcesIncluded, sourceLabels, lineage,
    states, sources, filterState, setFilterState, filterSource, setFilterSource,
    activeFuels, setActiveFuels, toggleFuel, sortField, sortAsc, toggleSort,
    selectedId, setSelectedId, expandedId, setExpandedId, filterSelectStyle,
    search, setSearch, unfilteredCount,
  } = props;

  return (
    <>
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
          <GeneratorMap permits={mapFiltered} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
      </div>

      {/* Charts row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
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
              {sorted.length} permit{sorted.length === 1 ? "" : "s"}
              {search.trim() && unfilteredCount !== sorted.length && ` (filtered from ${unfilteredCount})`}
              {" "}-- click column headers to sort -- click row to expand raw filing
            </p>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="text"
              placeholder="Search permittee, facility, state, source..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 6,
                color: "white",
                padding: "6px 10px",
                fontSize: 12,
                minWidth: 260,
              }}
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                style={{
                  background: "transparent",
                  border: "1px solid #334155",
                  borderRadius: 6,
                  color: "#94a3b8",
                  padding: "5px 8px",
                  cursor: "pointer",
                  fontSize: 11,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <X size={11} /> Clear
              </button>
            )}
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
                      <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{p.county_fips ?? "--"}</td>
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
    </>
  );
}

// ── Building-mode view ──────────────────────────────────────────────────────

function BuildingView(props: {
  loading: boolean;
  error: string | null;
  errorInfo: { title: string; message: string } | null;
  retry: () => void;
  lastFetchedAt: Date | null;
  buildingPermits: BuildingPermitDto[];
  sortedBuildings: BuildingPermitDto[];
  buildingTotal: number;
  buildingIssued: number;
  buildingPending: number;
  buildingValuation: number;
  byCounty: { county: string; count: number }[];
  buildingDays: number;
  setBuildingDays: (n: number) => void;
  buildingSortField: "issued_date" | "valuation_usd" | "applicant_name" | "permit_status";
  buildingSortAsc: boolean;
  toggleBuildingSort: (
    f: "issued_date" | "valuation_usd" | "applicant_name" | "permit_status",
  ) => void;
  selectedBuildingId: number | null;
  setSelectedBuildingId: (id: number | null) => void;
  buildingStatesIncluded: string[];
  buildingCoverageNote: string | null;
  buildingSourceLabels: string[];
  lineage: { source_url?: string; retrieved_at?: string; confidence?: number } | null;
  search: string;
  setSearch: (s: string) => void;
  unfilteredCount: number;
}) {
  const {
    loading, error, errorInfo, retry, lastFetchedAt,
    buildingPermits, sortedBuildings, buildingTotal,
    buildingIssued, buildingPending, buildingValuation, byCounty,
    buildingDays, setBuildingDays,
    buildingSortField, buildingSortAsc, toggleBuildingSort,
    selectedBuildingId, setSelectedBuildingId,
    buildingStatesIncluded, buildingCoverageNote, buildingSourceLabels, lineage,
    search, setSearch, unfilteredCount,
  } = props;

  if (loading) return <Loader />;
  if (error) {
    return <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} lastAttempt={lastFetchedAt} />;
  }

  // Empty state with widen-window CTA
  if (buildingPermits.length === 0) {
    return (
      <div style={{ ...CARD_STYLE, textAlign: "center", padding: 40 }}>
        <Building2 size={32} color="#64748b" style={{ marginBottom: 12 }} />
        <div style={{ color: "#e2e8f0", fontWeight: 600, fontSize: 14, marginBottom: 6 }}>
          No building permits in window
        </div>
        <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 16 }}>
          No building permits in window -- try widening days param (currently {buildingDays}d).
        </div>
        <button
          onClick={() => setBuildingDays(730)}
          style={{
            padding: "8px 16px",
            borderRadius: 6,
            background: "#22c55e",
            border: "none",
            color: "white",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Refetch with days=730
        </button>
      </div>
    );
  }

  return (
    <>
      {/* Coverage banner */}
      <div style={{
        background: "linear-gradient(135deg, #022c22 0%, #064e3b 100%)",
        border: "1px solid #15803d",
        borderRadius: 10,
        padding: "12px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Building2 size={16} color="#22c55e" />
          <span style={{ color: "white", fontWeight: 600, fontSize: 14 }}>
            Datacenter Building Permits (Construction Filings)
          </span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#0f172a", border: "1px solid #15803d", color: "#86efac", fontSize: "10px", fontWeight: 600 }}>
            {buildingTotal.toLocaleString()} permits in window
          </span>
        </div>
        <div style={{ color: "#94a3b8", fontSize: "11px", maxWidth: 540, textAlign: "right" }}>
          {buildingStatesIncluded.length > 0
            ? <>States: <span style={{ color: "#86efac" }}>{buildingStatesIncluded.join(", ")}</span></>
            : null}
          {buildingCoverageNote && (
            <div style={{ marginTop: 2, color: "#64748b" }}>{buildingCoverageNote}</div>
          )}
        </div>
      </div>

      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <MetricCard label="Total Permits" value={String(buildingPermits.length)} sub="in active window" accent="#3b82f6" icon={Filter} />
        <MetricCard label="Issued" value={String(buildingIssued)} sub={`${buildingPermits.length > 0 ? ((buildingIssued / buildingPermits.length) * 100).toFixed(0) : 0}% of total`} accent="#22c55e" icon={Building2} />
        <MetricCard label="Pending" value={String(buildingPending)} sub="applied / under review" accent="#f59e0b" icon={Building2} />
        <MetricCard label="Total Valuation" value={fmtUSD(buildingValuation)} sub="declared construction $" accent="#a855f7" icon={Zap} />
      </div>

      {/* Days-window control */}
      <div style={{ ...CARD_STYLE, padding: "12px 18px", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Filter size={13} color="#64748b" />
        <span style={{ color: "#64748b", fontSize: "12px" }}>Window:</span>
        {[180, 365, 730].map(d => {
          const active = buildingDays === d;
          return (
            <button
              key={d}
              onClick={() => setBuildingDays(d)}
              style={{
                padding: "5px 12px",
                borderRadius: 999,
                border: `1px solid ${active ? "#22c55e" : "#334155"}`,
                background: active ? "#22c55e22" : "#0f172a",
                color: active ? "#22c55e" : "#94a3b8",
                fontSize: 11,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Last {d}d
            </button>
          );
        })}
        <span style={{ marginLeft: "auto", color: "#64748b", fontSize: "11px" }}>
          {buildingPermits.length} permits loaded
        </span>
      </div>

      {/* Map */}
      <div style={{ ...CARD_STYLE, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #334155", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Building Permit Locations</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "3px 0 0" }}>
              Bubble size proportional to declared valuation -- Colored by status -- Click marker to inspect
            </p>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center", fontSize: "11px", color: "#94a3b8" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#22c55e" }} /> Issued
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#f59e0b" }} /> Pending
            </span>
          </div>
        </div>
        <div style={{ height: 440 }}>
          <BuildingMap
            permits={buildingPermits}
            selectedId={selectedBuildingId}
            onSelect={setSelectedBuildingId}
          />
        </div>
      </div>

      {/* Single bar chart: Permits by County */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 320 }}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: "0 0 4px" }}>Permits by County (Top 10)</h3>
          <p style={{ color: "#64748b", fontSize: "11px", margin: "0 0 14px" }}>
            Construction-permit volume by jurisdiction -- watch the leaders for new datacenter shells
          </p>
          {byCounty.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={byCounty} layout="vertical" margin={{ left: 4, right: 24, top: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} />
                <YAxis type="category" dataKey="county" tick={{ fill: "#94a3b8", fontSize: 11 }} width={120} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "white" }}
                  formatter={(v) => [`${Number(v)} permits`, "Count"]}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {byCounty.map((_, i) => (
                    <Cell key={i} fill={`hsl(${145 + i * 12}, 60%, ${55 - i * 2}%)`} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>No data to display.</div>
          )}
          <CitationFooter
            sources={buildingSourceLabels}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
          />
        </div>
      </div>

      {/* Building-permit table */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Building Permit Records</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
              {sortedBuildings.length} permit{sortedBuildings.length === 1 ? "" : "s"}
              {search.trim() && unfilteredCount !== sortedBuildings.length && ` (filtered from ${unfilteredCount})`}
              {" "}-- click column headers to sort
            </p>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="text"
              placeholder="Search county, applicant, address..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 6,
                color: "white",
                padding: "6px 10px",
                fontSize: 12,
                minWidth: 260,
              }}
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                style={{
                  background: "transparent",
                  border: "1px solid #334155",
                  borderRadius: 6,
                  color: "#94a3b8",
                  padding: "5px 8px",
                  cursor: "pointer",
                  fontSize: 11,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <X size={11} /> Clear
              </button>
            )}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                {[
                  { label: "Source", field: null },
                  { label: "County", field: null },
                  { label: "State", field: null },
                  { label: "Permit Type", field: null },
                  { label: "Status", field: "permit_status" as const },
                  { label: "Issued", field: "issued_date" as const },
                  { label: "Valuation $", field: "valuation_usd" as const },
                  { label: "Applicant", field: "applicant_name" as const },
                ].map(({ label, field }) => (
                  <th key={label}
                    onClick={field ? () => toggleBuildingSort(field) : undefined}
                    style={{
                      color: "#64748b", textAlign: "left", padding: "8px 12px",
                      fontWeight: 500, whiteSpace: "nowrap",
                      cursor: field ? "pointer" : "default",
                      userSelect: "none",
                    }}
                  >
                    {label}
                    {field && buildingSortField === field && (
                      buildingSortAsc
                        ? <ChevronUp size={10} style={{ display: "inline", marginLeft: 3 }} />
                        : <ChevronDown size={10} style={{ display: "inline", marginLeft: 3 }} />
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedBuildings.slice(0, 100).map(p => {
                const isSelected = selectedBuildingId === p.id;
                const issued = isIssued(p.permit_status);
                const statusBg = issued ? "#22c55e22" : "#f59e0b22";
                const statusColorVal = issued ? "#22c55e" : "#f59e0b";
                return (
                  <tr
                    key={p.id}
                    onClick={() => setSelectedBuildingId(isSelected ? null : p.id)}
                    style={{
                      borderBottom: "1px solid #1e293b",
                      cursor: "pointer",
                      background: isSelected ? "#162032" : "transparent",
                      transition: "background 0.1s",
                    }}
                  >
                    <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: 11 }}>
                      {SOURCE_LABEL[p.source ?? ""] ?? p.source ?? "--"}
                    </td>
                    <td style={{ padding: "9px 12px", color: "#e2e8f0", fontSize: 11 }}>{p.county ?? "--"}</td>
                    <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: 11 }}>{p.state ?? "--"}</td>
                    <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: 11 }}>{p.permit_type ?? "--"}</td>
                    <td style={{ padding: "9px 12px" }}>
                      <span style={{
                        padding: "2px 8px", borderRadius: 4,
                        background: statusBg, color: statusColorVal,
                        fontSize: 11, fontWeight: 600,
                      }}>
                        {p.permit_status ?? "--"}
                      </span>
                    </td>
                    <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: 11 }}>{fmtDate(p.issued_date)}</td>
                    <td style={{ padding: "9px 12px", color: "white", fontWeight: 700, fontSize: 12 }}>
                      {fmtUSD(p.valuation_usd)}
                    </td>
                    <td style={{ padding: "9px 12px", color: "#e2e8f0", fontSize: 11 }}>
                      {p.applicant_name ?? "--"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {sortedBuildings.length > 100 && (
            <div style={{ color: "#64748b", fontSize: "12px", padding: "8px 12px" }}>
              Showing 100 of {sortedBuildings.length} permits
            </div>
          )}
        </div>
        <CitationFooter
          sources={buildingSourceLabels}
          retrievedAt={lineage?.retrieved_at}
          confidence={lineage?.confidence}
        />
      </div>
    </>
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
