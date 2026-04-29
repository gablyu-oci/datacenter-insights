import { useState, useMemo, Fragment } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, LabelList, PieChart, Pie, Legend,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import {
  MapPin, Server, Zap, Building2, Filter, X,
  ChevronDown, ChevronUp,
} from "lucide-react";
import ErrorPanel from "../shared/ErrorPanel";
import CitationFooter from "../shared/CitationFooter";
import SiteRoleBreakdown from "../shared/SiteRoleBreakdown";
import SiteDetail from "../SiteDetail";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
// react-leaflet-google-layer ships CJS; Vite's pre-bundle hands us the module
// wrapper rather than auto-unwrapping `.default`. Force the unwrap so React
// receives a component, not an object.
import RLGLImport from "react-leaflet-google-layer";
const ReactLeafletGoogleLayer =
  (RLGLImport as unknown as { default?: typeof RLGLImport }).default ?? RLGLImport;
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";

const GMAPS_KEY = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string) || "";

// ── Types (matching real API shapes) ──────────────────────────────────────

interface SiteRecord {
  aterio_dc_uid: string;
  site_name: string | null;
  city: string | null;
  state: string | null;
  latitude: number | null;
  longitude: number | null;
  total_mw: number | null;
  provider_name: string | null;
  stage: string | null;
  sqft: number | null;
  // Lifecycle dates — used to derive end-of-year snapshot of pipeline state.
  announced_date: string | null;
  construction_start_date: string | null;
  construction_finished_date: string | null;
  activation_date: string | null;
  cancelled_date: string | null;
  project_withdrawn_date: string | null;
}

interface SitesResponse {
  data: SiteRecord[];
  total: number;
  page: number;
  page_size: number;
}

// ── Constants ─────────────────────────────────────────────────────────────

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const PROVIDER_COLORS: Record<string, string> = {
  "Microsoft": "#0078D4",
  "Amazon": "#FF9900",
  "Google": "#4285F4",
  "Meta": "#1877F2",
  "Oracle": "#C74634",
  "Equinix": "#e31837",
  "Digital Realty": "#007dc6",
  "CyrusOne": "#f59e0b",
  "QTS": "#22c55e",
  "Switch": "#06b6d4",
  "Vantage": "#f97316",
  "NTT": "#3b82f6",
};

const STAGE_COLOR: Record<string, string> = {
  "Operational": "#22c55e",
  "Under Construction": "#f59e0b",
  "Expanding": "#3b82f6",
  "Planned": "#94a3b8",
  "Active": "#22c55e",
};

function getProviderColor(name: string | null): string {
  if (!name) return "#6366f1";
  for (const [key, val] of Object.entries(PROVIDER_COLORS)) {
    if (name.toLowerCase().includes(key.toLowerCase())) return val;
  }
  // Hash-based color for unknown providers
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 65%, 55%)`;
}

// ── Small UI helpers ──────────────────────────────────────────────────────

function ChartTypeToggle({ value, onChange }: { value: "bar" | "pie"; onChange: (v: "bar" | "pie") => void }) {
  return (
    <div style={{ display: "flex", gap: 0, border: "1px solid #334155", borderRadius: 4, overflow: "hidden", fontSize: 10 }}>
      {(["bar", "pie"] as const).map(v => (
        <button
          key={v}
          onClick={() => onChange(v)}
          style={{
            background: v === value ? "#1e293b" : "transparent",
            color: v === value ? "#60a5fa" : "#64748b",
            border: "none",
            padding: "3px 8px",
            cursor: "pointer",
            textTransform: "capitalize",
            fontWeight: v === value ? 600 : 400,
          }}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

const TOOLTIP_STYLES = {
  contentStyle: { background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "white" },
  itemStyle: { color: "#e2e8f0" },
} as const;

// ── Map component using Leaflet (no API key required) ─────────────────────

// ESRI World Imagery Wayback releases — historical satellite snapshots, free, no key.
// IDs from https://wayback.maptiles.arcgis.com config (also used in the legacy
// SatelliteTab before its consolidation into this view).
const WAYBACK_RELEASES: { year: string; releaseId: number }[] = [
  { year: "2019", releaseId: 10 },
  { year: "2020", releaseId: 20 },
  { year: "2021", releaseId: 30 },
  { year: "2022", releaseId: 40 },
  { year: "2023", releaseId: 54 },
  { year: "2024", releaseId: 62 },
];

function SiteMap({
  sites,
  selectedSite,
  onSelectSite,
  imageryOn,
  imageryReleaseId,
  imageryOpacity,
  googleSatOn,
}: {
  sites: SiteRecord[];
  selectedSite: SiteRecord | null;
  onSelectSite: (s: SiteRecord | null) => void;
  imageryOn: boolean;
  imageryReleaseId: number;
  imageryOpacity: number;
  googleSatOn: boolean;
}) {
  // Filter sites with valid coordinates
  const mappable = sites.filter(s => s.latitude != null && s.longitude != null);

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
      {googleSatOn && GMAPS_KEY && (
        <ReactLeafletGoogleLayer apiKey={GMAPS_KEY} type="satellite" />
      )}
      {imageryOn && (
        <TileLayer
          key={imageryReleaseId}
          attribution='Imagery &copy; <a href="https://livingatlas.arcgis.com/wayback/">ESRI Wayback</a>'
          url={`https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/${imageryReleaseId}/{z}/{y}/{x}`}
          opacity={imageryOpacity}
          zIndex={500}
        />
      )}
      <MarkerClusterGroup
        chunkedLoading
        maxClusterRadius={60}
        disableClusteringAtZoom={10}
        spiderfyOnMaxZoom={true}
        showCoverageOnHover={false}
      >
        {mappable.map((site) => {
          const color = getProviderColor(site.provider_name);
          const isSelected = selectedSite?.aterio_dc_uid === site.aterio_dc_uid;
          const mw = site.total_mw ?? 0;
          const radius = Math.max(4, Math.min(16, 4 + Math.sqrt(mw) * 0.5));

          return (
            <CircleMarker
              key={site.aterio_dc_uid}
              center={[site.latitude!, site.longitude!]}
              radius={radius}
              pathOptions={{
                fillColor: color,
                fillOpacity: isSelected ? 1 : 0.7,
                color: isSelected ? "#ffffff" : color,
                weight: isSelected ? 3 : 1,
              }}
              eventHandlers={{
                click: () => onSelectSite(isSelected ? null : site),
              }}
            >
              <Popup>
                <div style={{ fontFamily: "system-ui, sans-serif", minWidth: 180 }}>
                  <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 4 }}>
                    {site.site_name || site.aterio_dc_uid}
                  </div>
                  {site.provider_name && (
                    <div style={{ fontSize: 11, color: "#666", marginBottom: 6 }}>{site.provider_name}</div>
                  )}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 11 }}>
                    {site.city && <div><strong>City:</strong> {site.city}</div>}
                    {site.state && <div><strong>State:</strong> {site.state}</div>}
                    {mw > 0 && <div><strong>MW:</strong> {mw.toFixed(0)}</div>}
                    {site.stage && <div><strong>Stage:</strong> {site.stage}</div>}
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

// ── Helpers ─────────────────────────────────────────────────────────────────

function MetricCard({ label, value, unit, sub, accent, icon: Icon }: {
  label: string; value: string; unit?: string; sub?: string; accent?: string;
  icon: React.ElementType;
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Icon size={14} color={accent ?? "#3b82f6"} />
        <span style={{ color: "#94a3b8", fontSize: "12px" }}>{label}</span>
      </div>
      <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>
        {value}<span style={{ color: "#64748b", fontSize: "13px", marginLeft: "3px" }}>{unit}</span>
      </div>
      {sub && <div style={{ color: accent ?? "#3b82f6", fontSize: "11px", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function DataCentersTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } = useApi<SitesResponse>("/api/sites/?page_size=10000");
  const [filterProvider, setFilterProvider] = useState("All");
  const [filterState, setFilterState] = useState("All");
  const [filterStage, setFilterStage] = useState("All");
  const [sortField, setSortField] = useState<"total_mw" | "site_name">("total_mw");
  const [sortAsc, setSortAsc] = useState(false);
  const [selected, setSelected] = useState<SiteRecord | null>(null);
  const [expandedSiteUid, setExpandedSiteUid] = useState<string | null>(null);
  const [detailUid, setDetailUid] = useState<string | null>(null);
  const [imageryOn, setImageryOn] = useState(false);
  const [imageryYearIdx, setImageryYearIdx] = useState(WAYBACK_RELEASES.length - 1);
  const [imageryOpacity, setImageryOpacity] = useState(0.85);
  const [googleSatOn, setGoogleSatOn] = useState(false);
  const [providerChartType, setProviderChartType] = useState<"bar" | "pie">("bar");
  const [stateChartType, setStateChartType] = useState<"bar" | "pie">("bar");
  const [yearStageMetric, setYearStageMetric] = useState<"count" | "mw">("count");
  // Per-column filters for the Facility Directory table.
  // Text fields use datalist-backed combobox (typeahead suggestions from the
  // distinct values in the data). MW uses a structured comparator + number.
  type MwOp = ">=" | "<=" | ">" | "<" | "=" | "between";
  const [colFilters, setColFilters] = useState<{
    provider: string;
    site: string;
    city: string;
    state: string;
    stage: string;
    mw: { op: MwOp; value: string; value2: string };
  }>({
    provider: "",
    site: "",
    city: "",
    state: "",
    stage: "",
    mw: { op: ">=", value: "", value2: "" },
  });
  const _MW_OP_LABELS: Record<MwOp, string> = {
    ">=": "≥", "<=": "≤", ">": ">", "<": "<", "=": "=", "between": "between",
  };
  const clearColFilters = () =>
    setColFilters({
      provider: "", site: "", city: "", state: "", stage: "",
      mw: { op: ">=", value: "", value2: "" },
    });

  // API returns the raw Aterio-shaped Site row (building_name, state_code,
  // power_capacity_mw, etc.). Adapt to the component's SiteRecord shape and
  // fall back through the MW fields so we don't hide capacity that's only
  // available as an Aterio estimate.
  const sites: SiteRecord[] = useMemo(() => {
    const raw = (data?.data as unknown as Record<string, unknown>[]) ?? [];
    return raw.map((s) => ({
      aterio_dc_uid: (s.aterio_dc_uid as string) ?? "",
      site_name: (s.building_name as string | null) ?? null,
      city: (s.city_name as string | null) ?? null,
      state: (s.state_code as string | null) ?? null,
      latitude: (s.latitude as number | null) ?? null,
      longitude: (s.longitude as number | null) ?? null,
      total_mw:
        (s.power_capacity_mw as number | null) ??
        (s.aterio_est_mw as number | null) ??
        null,
      provider_name: (s.provider_name as string | null) ?? null,
      stage: (s.stage as string | null) ?? null,
      sqft:
        (s.tot_facility_space_sqft as number | null) ??
        (s.tot_datacenter_space_sqft as number | null) ??
        null,
      announced_date: (s.announced_date as string | null) ?? null,
      construction_start_date: (s.construction_start_date as string | null) ?? null,
      construction_finished_date: (s.construction_finished_date as string | null) ?? null,
      activation_date: (s.activation_date as string | null) ?? null,
      cancelled_date: (s.cancelled_date as string | null) ?? null,
      project_withdrawn_date: (s.project_withdrawn_date as string | null) ?? null,
    }));
  }, [data]);
  const totalInDb = data?.total ?? sites.length;

  const providers = useMemo(() => ["All", ...Array.from(new Set(sites.map(d => d.provider_name ?? "Unknown").filter(Boolean))).sort()], [sites]);
  const states = useMemo(() => ["All", ...Array.from(new Set(sites.map(d => d.state ?? "").filter(Boolean))).sort()], [sites]);
  const stagesList = useMemo(() => ["All", ...Array.from(new Set(sites.map(d => d.stage ?? "").filter(Boolean))).sort()], [sites]);

  const filtered = useMemo(() => sites.filter(d => {
    if (filterProvider !== "All" && (d.provider_name ?? "Unknown") !== filterProvider) return false;
    if (filterState !== "All" && d.state !== filterState) return false;
    if (filterStage !== "All" && d.stage !== filterStage) return false;
    return true;
  }), [sites, filterProvider, filterState, filterStage]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      if (sortField === "site_name") {
        const av = a.site_name ?? "";
        const bv = b.site_name ?? "";
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      const av = a.total_mw ?? 0;
      const bv = b.total_mw ?? 0;
      return sortAsc ? av - bv : bv - av;
    });
  }, [filtered, sortField, sortAsc]);

  // Distinct values per filterable column — populates the datalist
  // suggestions (combobox-with-search behavior).
  const distinctOptions = useMemo(() => {
    const prov = new Set<string>(), site = new Set<string>(),
      city = new Set<string>(), state = new Set<string>(), stage = new Set<string>();
    for (const s of sites) {
      if (s.provider_name) prov.add(s.provider_name);
      if (s.site_name) site.add(s.site_name);
      if (s.city) city.add(s.city);
      if (s.state) state.add(s.state);
      if (s.stage) stage.add(s.stage);
    }
    const sorted = (set: Set<string>) => [...set].sort((a, b) => a.localeCompare(b));
    return {
      provider: sorted(prov),
      site: sorted(site),
      city: sorted(city),
      state: sorted(state),
      stage: sorted(stage),
    };
  }, [sites]);

  // Apply per-column filters on top of the already-filtered/sorted set.
  const tableRows = useMemo(() => {
    const m = (s: string | null | undefined, q: string) =>
      q === "" || (s ?? "").toLowerCase().includes(q.toLowerCase());
    const mw = colFilters.mw;
    const mwV = mw.value === "" ? null : Number(mw.value);
    const mwV2 = mw.value2 === "" ? null : Number(mw.value2);
    const mwMatches = (v: number): boolean => {
      if (mwV === null || Number.isNaN(mwV)) return true;
      switch (mw.op) {
        case ">=": return v >= mwV;
        case "<=": return v <= mwV;
        case ">":  return v >  mwV;
        case "<":  return v <  mwV;
        case "=":  return v === mwV;
        case "between":
          return mwV2 !== null && !Number.isNaN(mwV2)
            ? v >= mwV && v <= mwV2
            : v >= mwV;
      }
    };
    return sorted.filter(d =>
      m(d.provider_name, colFilters.provider) &&
      m(d.site_name, colFilters.site) &&
      m(d.city, colFilters.city) &&
      m(d.state, colFilters.state) &&
      m(d.stage, colFilters.stage) &&
      mwMatches(d.total_mw ?? 0)
    );
  }, [sorted, colFilters]);

  // Aggregate stats over the filtered rows for the top-of-table summary line.
  const tableStats = useMemo(() => {
    const mws = tableRows.map(d => d.total_mw ?? 0).filter(v => v > 0);
    const sum = mws.reduce((s, v) => s + v, 0);
    return {
      count: tableRows.length,
      sumMW: Math.round(sum),
      avgMW: mws.length > 0 ? Math.round(sum / mws.length) : 0,
    };
  }, [tableRows]);

  const toggleSort = (field: typeof sortField) => {
    if (sortField === field) setSortAsc(v => !v);
    else { setSortField(field); setSortAsc(false); }
  };

  // Aggregate by provider (top 10)
  const byProvider = useMemo(() => {
    const map: Record<string, { mw: number; count: number }> = {};
    filtered.forEach(d => {
      const prov = d.provider_name ?? "Unknown";
      // Skip the Aterio "no provider known" sentinel — it's a data-quality
      // bucket, not a real competitor, and dominates the chart visually.
      if (prov === "Company Not Disclosed" || prov === "Unknown") return;
      if (!map[prov]) map[prov] = { mw: 0, count: 0 };
      map[prov].mw += d.total_mw ?? 0;
      map[prov].count += 1;
    });
    return Object.entries(map)
      .map(([provider, v]) => ({ provider, mw: Math.round(v.mw), count: v.count }))
      .sort((a, b) => b.mw - a.mw)
      .slice(0, 10);
  }, [filtered]);

  // End-of-year snapshot of pipeline state. For each recent year Y, classify
  // every filtered site by what state it was in at 12-31-Y, derived from the
  // lifecycle date columns. Mutually exclusive cohorts so the per-year totals
  // sum cleanly.
  //
  // Note for the current year (2026): "Active" includes projected activations
  // (Aterio's `activation_date` is the planned activation date), not just
  // already-realised ones. That's an honest quirk of the source data.
  const yearStage = useMemo(() => {
    const PIPELINE_STAGES = ["Announced", "Under Construction", "Active", "Withdrawn", "Cancelled"] as const;
    type PipelineStage = typeof PIPELINE_STAGES[number];

    const beforeOrEqual = (dateStr: string | null, yearEnd: number): boolean => {
      if (!dateStr) return false;
      const y = parseInt(dateStr.slice(0, 4), 10);
      return Number.isFinite(y) && y <= yearEnd;
    };

    const classify = (s: SiteRecord, yearEnd: number): PipelineStage | null => {
      if (beforeOrEqual(s.cancelled_date, yearEnd)) return "Cancelled";
      if (beforeOrEqual(s.project_withdrawn_date, yearEnd)) return "Withdrawn";
      if (beforeOrEqual(s.activation_date, yearEnd)) return "Active";
      if (beforeOrEqual(s.construction_start_date, yearEnd)) return "Under Construction";
      if (beforeOrEqual(s.announced_date, yearEnd)) return "Announced";
      return null; // not yet announced as of this year-end
    };

    const currentYear = new Date().getFullYear();
    const recentYears = [currentYear - 2, currentYear - 1, currentYear];

    // cube[year][stage] = { count, mw }
    const cube: Record<number, Record<PipelineStage, { count: number; mw: number }>> = {};
    recentYears.forEach(y => {
      cube[y] = {} as Record<PipelineStage, { count: number; mw: number }>;
      PIPELINE_STAGES.forEach(st => { cube[y][st] = { count: 0, mw: 0 }; });
    });

    filtered.forEach(s => {
      const mw = s.total_mw ?? 0;
      recentYears.forEach(y => {
        const stage = classify(s, y);
        if (stage) {
          cube[y][stage].count += 1;
          cube[y][stage].mw += mw;
        }
      });
    });

    // Transposed: one row per stage, one numeric column per year.
    const data = PIPELINE_STAGES.map(stage => {
      const row: Record<string, string | number> = { stage };
      recentYears.forEach(y => {
        row[String(y)] = Math.round(cube[y][stage][yearStageMetric]);
      });
      return row;
    });
    return { data, years: recentYears.map(String) };
  }, [filtered, yearStageMetric]);

  // Aggregate by state (top 8)
  const byState = useMemo(() => {
    const map: Record<string, { mw: number; count: number }> = {};
    filtered.forEach(d => {
      const st = d.state ?? "Unknown";
      if (!map[st]) map[st] = { mw: 0, count: 0 };
      map[st].mw += d.total_mw ?? 0;
      map[st].count += 1;
    });
    return Object.entries(map)
      .map(([state, v]) => ({ state, mw: Math.round(v.mw), count: v.count }))
      .sort((a, b) => b.mw - a.mw)
      .slice(0, 8);
  }, [filtered]);

  // Early returns must come AFTER all hooks (Rules of Hooks).
  if (loading) return <Loader />;
  if (error) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} lastAttempt={lastFetchedAt} />
      </div>
    );
  }

  const totalMW = filtered.reduce((s, d) => s + (d.total_mw ?? 0), 0);
  const totalFacilities = filtered.length;
  const uniqueStates = new Set(filtered.map(d => d.state).filter(Boolean)).size;
  const uniqueProviders = new Set(filtered.map(d => d.provider_name).filter(Boolean)).size;

  const filterSelectStyle: React.CSSProperties = {
    background: "#0f172a",
    border: "1px solid #334155",
    borderRadius: 6,
    color: "white",
    padding: "6px 10px",
    fontSize: "12px",
    cursor: "pointer",
  };

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>
      {detailUid && (
        <SiteDetail aterioDcUid={detailUid} onClose={() => setDetailUid(null)} />
      )}

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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Server size={16} color="#3b82f6" />
          <span style={{ color: "white", fontWeight: 600, fontSize: 14 }}>US Data Centers Power Map</span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#0f172a", border: "1px solid #1d4ed8", color: "#60a5fa", fontSize: "10px", fontWeight: 600 }}>
            {totalInDb.toLocaleString()} sites in database
          </span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#052e16", border: "1px solid #16a34a", color: "#4ade80", fontSize: "9px", fontWeight: 600 }}>
            LIVE
          </span>
        </div>
        <div style={{ color: "#64748b", fontSize: "11px" }}>
          Showing {filtered.length} of {totalInDb.toLocaleString()} sites (first 500 loaded)
        </div>
      </div>

      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <MetricCard label="Facilities Shown" value={String(totalFacilities)} sub={`${uniqueProviders} providers`} accent="#3b82f6" icon={Building2} />
        <MetricCard label="Total MW Capacity" value={Math.round(totalMW).toLocaleString()} unit="MW" sub="IT load capacity" accent="#f59e0b" icon={Zap} />
        <MetricCard label="US States" value={String(uniqueStates)} sub="geographic coverage" accent="#22c55e" icon={MapPin} />
        <MetricCard label="Total in Database" value={totalInDb.toLocaleString()} sub="full Aterio dataset" accent="#8b5cf6" icon={Server} />
      </div>

      {/* Filter bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Filter size={13} color="#64748b" />
        <span style={{ color: "#64748b", fontSize: "12px" }}>Filter:</span>
        <label style={{ color: "#94a3b8", fontSize: 11 }}>Provider</label>
        <select value={filterProvider} onChange={e => setFilterProvider(e.target.value)} style={filterSelectStyle}>
          {providers.map(o => <option key={o}>{o}</option>)}
        </select>
        <label style={{ color: "#94a3b8", fontSize: 11 }}>State</label>
        <select value={filterState} onChange={e => setFilterState(e.target.value)} style={filterSelectStyle}>
          {states.map(s => <option key={s}>{s}</option>)}
        </select>
        <label style={{ color: "#94a3b8", fontSize: 11 }}>Stage</label>
        <select value={filterStage} onChange={e => setFilterStage(e.target.value)} style={filterSelectStyle}>
          {stagesList.map(s => <option key={s}>{s}</option>)}
        </select>
        {(filterProvider !== "All" || filterState !== "All" || filterStage !== "All") && (
          <button
            onClick={() => { setFilterProvider("All"); setFilterState("All"); setFilterStage("All"); }}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 6, background: "#1e293b", border: "1px solid #334155", color: "#94a3b8", cursor: "pointer", fontSize: "12px" }}
          >
            <X size={11} /> Clear
          </button>
        )}
        <span style={{ marginLeft: "auto", color: "#64748b", fontSize: "11px" }}>{filtered.length} sites shown</span>
      </div>

      {/* Map */}
      <div style={{ ...CARD_STYLE, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #334155", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Site Locations</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "3px 0 0" }}>
              Bubble size proportional to MW capacity -- Click any marker to inspect -- Colored by provider
            </p>
          </div>
          {selected && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#0f172a", border: "1px solid #334155", borderRadius: 6, padding: "6px 12px" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: getProviderColor(selected.provider_name) }} />
              <span style={{ color: "white", fontSize: "12px", fontWeight: 600 }}>{selected.site_name || selected.aterio_dc_uid}</span>
              <button onClick={() => setSelected(null)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", padding: 0, display: "flex" }}><X size={12} /></button>
            </div>
          )}
        </div>
        {/* Satellite imagery controls (ESRI Wayback historical layer) */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "8px 12px", background: "#0f172a", border: "1px solid #334155", borderRadius: 6, marginBottom: 8 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, color: "#e2e8f0", fontSize: 12, cursor: "pointer" }}>
            <input type="checkbox" checked={imageryOn} onChange={e => setImageryOn(e.target.checked)} />
            ESRI Wayback (historical)
          </label>
          <label
            style={{
              display: "flex", alignItems: "center", gap: 6, fontSize: 12,
              color: GMAPS_KEY ? "#e2e8f0" : "#475569",
              cursor: GMAPS_KEY ? "pointer" : "not-allowed",
            }}
            title={GMAPS_KEY ? "" : "Set VITE_GOOGLE_MAPS_API_KEY in frontend/.env.local"}
          >
            <input
              type="checkbox"
              checked={googleSatOn}
              disabled={!GMAPS_KEY}
              onChange={e => setGoogleSatOn(e.target.checked)}
            />
            Google Satellite (current)
          </label>
          {imageryOn && (
            <>
              <span style={{ color: "#94a3b8", fontSize: 11 }}>Year:</span>
              {WAYBACK_RELEASES.map((r, i) => (
                <button
                  key={r.year}
                  onClick={() => setImageryYearIdx(i)}
                  style={{
                    background: i === imageryYearIdx ? "#3b82f6" : "transparent",
                    color: i === imageryYearIdx ? "white" : "#cbd5e1",
                    border: "1px solid #334155",
                    borderRadius: 4,
                    padding: "3px 8px",
                    fontSize: 11,
                    cursor: "pointer",
                  }}
                >
                  {r.year}
                </button>
              ))}
              <span style={{ color: "#94a3b8", fontSize: 11, marginLeft: 8 }}>
                Opacity: {Math.round(imageryOpacity * 100)}%
              </span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={imageryOpacity}
                onChange={e => setImageryOpacity(parseFloat(e.target.value))}
                style={{ width: 120 }}
              />
              <a
                href="https://livingatlas.arcgis.com/wayback/"
                target="_blank"
                rel="noreferrer"
                style={{ color: "#64748b", fontSize: 10, marginLeft: "auto" }}
              >
                Imagery via ESRI World Imagery Wayback
              </a>
            </>
          )}
        </div>
        <div style={{ height: 440 }}>
          <SiteMap
            sites={filtered}
            selectedSite={selected}
            onSelectSite={setSelected}
            imageryOn={imageryOn}
            imageryReleaseId={WAYBACK_RELEASES[imageryYearIdx].releaseId}
            imageryOpacity={imageryOpacity}
            googleSatOn={googleSatOn && !!GMAPS_KEY}
          />
        </div>
      </div>

      {/* Charts row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {/* By Provider */}
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 300 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
            <div>
              <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: 0 }}>MW Capacity by Provider (Top 10)</h3>
              <p style={{ color: "#64748b", fontSize: "11px", margin: "4px 0 10px" }}>Total power capacity across tracked facilities · "Company Not Disclosed" excluded</p>
            </div>
            <ChartTypeToggle value={providerChartType} onChange={setProviderChartType} />
          </div>
          {byProvider.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              {providerChartType === "bar" ? (
                <BarChart data={byProvider} layout="vertical" margin={{ left: 4, right: 56, top: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                  <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit=" MW" />
                  <YAxis type="category" dataKey="provider" tick={{ fill: "#94a3b8", fontSize: 10 }} width={120} />
                  <Tooltip
                    {...TOOLTIP_STYLES}
                    formatter={(v, _n, props) => [
                      `${Number(v).toLocaleString()} MW (${(props as { payload?: { count?: number } })?.payload?.count ?? 0} sites)`, "Capacity",
                    ]}
                  />
                  <Bar dataKey="mw" radius={[0, 4, 4, 0]}>
                    {byProvider.map((entry, i) => (
                      <Cell key={i} fill={getProviderColor(entry.provider)} />
                    ))}
                    <LabelList dataKey="mw" position="right" fill="#e2e8f0" fontSize={10} formatter={(v: number) => v.toLocaleString()} />
                  </Bar>
                </BarChart>
              ) : (
                <PieChart>
                  <Pie
                    data={byProvider}
                    dataKey="mw"
                    nameKey="provider"
                    cx="50%"
                    cy="50%"
                    outerRadius={95}
                    label={(p: { provider?: string; percent?: number }) =>
                      `${p.provider}: ${((p.percent ?? 0) * 100).toFixed(1)}%`
                    }
                    labelLine={false}
                  >
                    {byProvider.map((entry, i) => (
                      <Cell key={i} fill={getProviderColor(entry.provider)} />
                    ))}
                  </Pie>
                  <Tooltip
                    {...TOOLTIP_STYLES}
                    formatter={(v: number, name: string) => [
                      `${v.toLocaleString()} MW`, name,
                    ]}
                  />
                </PieChart>
              )}
            </ResponsiveContainer>
          ) : (
            <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>No data to display.</div>
          )}
          <CitationFooter
            sources={["Aterio Database"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={lineage?.source_url}
          />
        </div>

        {/* By State */}
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 280 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
            <div>
              <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: 0 }}>MW Capacity by State</h3>
              <p style={{ color: "#64748b", fontSize: "11px", margin: "4px 0 10px" }}>Top 8 states by total MW</p>
            </div>
            <ChartTypeToggle value={stateChartType} onChange={setStateChartType} />
          </div>
          {byState.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              {stateChartType === "bar" ? (
                <BarChart data={byState} layout="vertical" margin={{ left: 4, right: 56, top: 4, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                  <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit=" MW" />
                  <YAxis type="category" dataKey="state" tick={{ fill: "#94a3b8", fontSize: 11 }} width={30} />
                  <Tooltip
                    {...TOOLTIP_STYLES}
                    formatter={(v, _n, props) => [
                      `${Number(v).toLocaleString()} MW (${(props as { payload?: { count?: number } })?.payload?.count ?? 0} sites)`, "Capacity",
                    ]}
                  />
                  <Bar dataKey="mw" fill="#3b82f6" radius={[0, 4, 4, 0]}>
                    {byState.map((_, i) => (
                      <Cell key={i} fill={`hsl(${210 + i * 12}, 80%, ${60 - i * 3}%)`} />
                    ))}
                    <LabelList dataKey="mw" position="right" fill="#e2e8f0" fontSize={10} formatter={(v: number) => v.toLocaleString()} />
                  </Bar>
                </BarChart>
              ) : (
                <PieChart>
                  <Pie
                    data={byState}
                    dataKey="mw"
                    nameKey="state"
                    cx="50%"
                    cy="50%"
                    outerRadius={95}
                    label={(p: { state?: string; percent?: number }) =>
                      `${p.state}: ${((p.percent ?? 0) * 100).toFixed(1)}%`
                    }
                    labelLine={false}
                  >
                    {byState.map((_, i) => (
                      <Cell key={i} fill={`hsl(${210 + i * 12}, 80%, ${60 - i * 3}%)`} />
                    ))}
                  </Pie>
                  <Tooltip
                    {...TOOLTIP_STYLES}
                    formatter={(v: number, name: string) => [`${v.toLocaleString()} MW`, name]}
                  />
                </PieChart>
              )}
            </ResponsiveContainer>
          ) : (
            <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>No data to display.</div>
          )}
          <CitationFooter
            sources={["Aterio Database"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={lineage?.source_url}
          />
        </div>
      </div>

      {/* Year × Stage chart (recent 3 years, side-by-side grouped bars) */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: 0 }}>Pipeline State by Year</h3>
            <p style={{ color: "#64748b", fontSize: "11px", margin: "4px 0 10px" }}>
              End-of-year snapshot · how many sites were in each state at the close of {yearStage.years.join(" / ")} · current-year &quot;Active&quot; includes projected activations
            </p>
          </div>
          <div style={{ display: "flex", gap: 0, border: "1px solid #334155", borderRadius: 4, overflow: "hidden", fontSize: 10 }}>
            {(["count", "mw"] as const).map(v => (
              <button
                key={v}
                onClick={() => setYearStageMetric(v)}
                style={{
                  background: v === yearStageMetric ? "#1e293b" : "transparent",
                  color: v === yearStageMetric ? "#60a5fa" : "#64748b",
                  border: "none",
                  padding: "3px 10px",
                  cursor: "pointer",
                  fontWeight: v === yearStageMetric ? 600 : 400,
                }}
              >
                {v === "count" ? "Count" : "MW"}
              </button>
            ))}
          </div>
        </div>
        {yearStage.data.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={yearStage.data} margin={{ left: 4, right: 24, top: 16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="stage" tick={{ fill: "#94a3b8", fontSize: 11 }} interval={0} />
              <YAxis tick={{ fill: "#64748b", fontSize: 10 }} unit={yearStageMetric === "mw" ? " MW" : ""} />
              <Tooltip
                {...TOOLTIP_STYLES}
                formatter={(v: number) => [
                  yearStageMetric === "mw" ? `${v.toLocaleString()} MW` : `${v.toLocaleString()} sites`,
                ]}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: "#94a3b8" }} />
              {yearStage.years.map((year, i) => {
                // Older year → cooler/dimmer; latest year → bright accent.
                const palette = ["#475569", "#3b82f6", "#f59e0b"];
                const fill = palette[(palette.length - yearStage.years.length) + i] ?? palette[i];
                return (
                  <Bar
                    key={year}
                    dataKey={year}
                    fill={fill}
                    radius={[3, 3, 0, 0]}
                  >
                    <LabelList
                      dataKey={year}
                      position="top"
                      fill="#cbd5e1"
                      fontSize={9}
                      formatter={(v: number) => (v > 0 ? v.toLocaleString() : "")}
                    />
                  </Bar>
                );
              })}
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>
            No sites with an announcement date in the current filter.
          </div>
        )}
        <CitationFooter
          sources={["Aterio Database"]}
          retrievedAt={lineage?.retrieved_at}
          confidence={lineage?.confidence}
          sourceUrl={lineage?.source_url}
        />
      </div>

      {/* Data table */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Facility Directory</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
              {tableStats.count.toLocaleString()} matching · click column headers to sort · pick from the dropdowns or type to search · MW filter uses comparator + value
            </p>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                {[
                  { label: "Provider", field: null },
                  { label: "Site", field: "site_name" as const },
                  { label: "City", field: null },
                  { label: "State", field: null },
                  { label: "MW", field: "total_mw" as const },
                  { label: "Stage", field: null },
                  { label: "Details", field: null },
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
              {/* Per-column filter row — datalist-backed combobox per text
                  field, structured comparator + number for MW. */}
              <tr style={{ borderBottom: "1px solid #334155", background: "#0b1220" }}>
                {([
                  ["provider", "Provider", distinctOptions.provider],
                  ["site", "Site", distinctOptions.site],
                  ["city", "City", distinctOptions.city],
                  ["state", "State", distinctOptions.state],
                ] as const).map(([key, ph, opts]) => (
                  <th key={key} style={{ padding: "4px 8px" }}>
                    <input
                      type="text"
                      list={`dl-${key}`}
                      value={colFilters[key]}
                      onChange={e => setColFilters(f => ({ ...f, [key]: e.target.value }))}
                      placeholder={ph}
                      style={{
                        width: "100%", boxSizing: "border-box",
                        background: "#0f172a", border: "1px solid #1e293b",
                        borderRadius: 4, color: "#e2e8f0",
                        padding: "4px 6px", fontSize: 11,
                      }}
                    />
                    <datalist id={`dl-${key}`}>
                      {opts.map(o => <option key={o} value={o} />)}
                    </datalist>
                  </th>
                ))}
                <th style={{ padding: "4px 8px" }}>
                  <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <select
                      value={colFilters.mw.op}
                      onChange={e => setColFilters(f => ({ ...f, mw: { ...f.mw, op: e.target.value as MwOp } }))}
                      style={{
                        background: "#0f172a", border: "1px solid #1e293b",
                        borderRadius: 4, color: "#e2e8f0",
                        padding: "4px 4px", fontSize: 11, cursor: "pointer",
                      }}
                    >
                      {(Object.entries(_MW_OP_LABELS) as [MwOp, string][]).map(([op, lbl]) => (
                        <option key={op} value={op}>{lbl}</option>
                      ))}
                    </select>
                    <input
                      type="number"
                      value={colFilters.mw.value}
                      onChange={e => setColFilters(f => ({ ...f, mw: { ...f.mw, value: e.target.value } }))}
                      placeholder="MW"
                      style={{
                        flex: 1, minWidth: 50, boxSizing: "border-box",
                        background: "#0f172a", border: "1px solid #1e293b",
                        borderRadius: 4, color: "#e2e8f0",
                        padding: "4px 6px", fontSize: 11,
                      }}
                    />
                    {colFilters.mw.op === "between" && (
                      <input
                        type="number"
                        value={colFilters.mw.value2}
                        onChange={e => setColFilters(f => ({ ...f, mw: { ...f.mw, value2: e.target.value } }))}
                        placeholder="max"
                        style={{
                          flex: 1, minWidth: 50, boxSizing: "border-box",
                          background: "#0f172a", border: "1px solid #1e293b",
                          borderRadius: 4, color: "#e2e8f0",
                          padding: "4px 6px", fontSize: 11,
                        }}
                      />
                    )}
                  </div>
                </th>
                <th style={{ padding: "4px 8px" }}>
                  <input
                    type="text"
                    list="dl-stage"
                    value={colFilters.stage}
                    onChange={e => setColFilters(f => ({ ...f, stage: e.target.value }))}
                    placeholder="Stage"
                    style={{
                      width: "100%", boxSizing: "border-box",
                      background: "#0f172a", border: "1px solid #1e293b",
                      borderRadius: 4, color: "#e2e8f0",
                      padding: "4px 6px", fontSize: 11,
                    }}
                  />
                  <datalist id="dl-stage">
                    {distinctOptions.stage.map(o => <option key={o} value={o} />)}
                  </datalist>
                </th>
                <th style={{ padding: "4px 8px" }}>
                  {(colFilters.provider || colFilters.site || colFilters.city ||
                    colFilters.state || colFilters.stage ||
                    colFilters.mw.value !== "" || colFilters.mw.value2 !== "") && (
                    <button
                      onClick={clearColFilters}
                      style={{ background: "transparent", border: "1px solid #334155", color: "#94a3b8", borderRadius: 4, padding: "3px 8px", cursor: "pointer", fontSize: 10 }}
                    >
                      Clear
                    </button>
                  )}
                </th>
              </tr>
              {/* Aggregate stats row */}
              <tr style={{ borderBottom: "2px solid #334155", background: "#111c2e" }}>
                <td style={{ padding: "8px 12px", color: "#64748b", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Total</td>
                <td colSpan={3} style={{ padding: "8px 12px", color: "#cbd5e1", fontSize: 11 }}>
                  <span style={{ color: "#64748b" }}>count:</span>{" "}
                  <span style={{ color: "#60a5fa", fontWeight: 700 }}>{tableStats.count.toLocaleString()}</span>
                </td>
                <td style={{ padding: "8px 12px", color: "#cbd5e1", fontSize: 11 }}>
                  <span style={{ color: "#64748b" }}>sum:</span>{" "}
                  <span style={{ color: "#f59e0b", fontWeight: 700 }}>{tableStats.sumMW.toLocaleString()}</span>
                  <br />
                  <span style={{ color: "#64748b" }}>avg:</span>{" "}
                  <span style={{ color: "#22c55e", fontWeight: 700 }}>{tableStats.avgMW.toLocaleString()}</span>
                </td>
                <td colSpan={2} />
              </tr>
            </thead>
            <tbody>
              {tableRows.slice(0, 50).map(dc => {
                const color = getProviderColor(dc.provider_name);
                const stageColor = STAGE_COLOR[dc.stage ?? ""] ?? "#94a3b8";
                const isSelected = selected?.aterio_dc_uid === dc.aterio_dc_uid;
                const isExpanded = expandedSiteUid === dc.aterio_dc_uid;
                return (
                  <Fragment key={dc.aterio_dc_uid}>
                    <tr
                      onClick={() => {
                        setSelected(isSelected ? null : dc);
                        setExpandedSiteUid(isExpanded ? null : dc.aterio_dc_uid);
                      }}
                      style={{
                        borderBottom: isExpanded ? "none" : "1px solid #1e293b",
                        cursor: "pointer",
                        background: isSelected ? "#162032" : "transparent",
                        transition: "background 0.1s",
                      }}
                    >
                      <td style={{ padding: "9px 12px" }}>
                        <span style={{ padding: "2px 8px", borderRadius: 4, background: `${color}22`, color, fontSize: "11px", fontWeight: 600 }}>
                          {dc.provider_name ?? "Unknown"}
                        </span>
                      </td>
                      <td style={{ padding: "9px 12px", color: "#e2e8f0", fontWeight: 500 }}>{dc.site_name || dc.aterio_dc_uid}</td>
                      <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{dc.city ?? "--"}</td>
                      <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{dc.state ?? "--"}</td>
                      <td style={{ padding: "9px 12px", color: "white", fontWeight: 700 }}>{dc.total_mw != null ? dc.total_mw.toFixed(0) : "--"}</td>
                      <td style={{ padding: "9px 12px" }}>
                        <span style={{ color: stageColor, fontSize: "11px" }}>&#x25CF; {dc.stage ?? "Unknown"}</span>
                      </td>
                      <td style={{ padding: "9px 12px" }} onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => setDetailUid(dc.aterio_dc_uid)}
                          style={{
                            padding: "4px 10px",
                            borderRadius: 4,
                            background: "#0f172a",
                            border: "1px solid #1d4ed8",
                            color: "#60a5fa",
                            fontSize: "11px",
                            fontWeight: 600,
                            cursor: "pointer",
                          }}
                          aria-label={`View details for ${dc.site_name || dc.aterio_dc_uid}`}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr style={{ borderBottom: "1px solid #1e293b", background: "#162032" }}>
                        <td colSpan={7} style={{ padding: "12px 16px 16px 48px" }}>
                          <SiteRoleBreakdown siteUid={dc.aterio_dc_uid} />
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
              Showing 50 of {sorted.length} sites
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading site data...</div>;
}
