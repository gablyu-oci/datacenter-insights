import { useEffect, useRef, useState, useMemo } from "react";
import { setOptions, importLibrary } from "@googlemaps/js-api-loader";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from "recharts";
import {
  MapPin, Server, Zap, Building2, Filter, X, ExternalLink,
  ChevronDown, ChevronUp, AlertTriangle,
} from "lucide-react";

// ── Static mock data ────────────────────────────────────────────────────────

interface DataCenter {
  id: string;
  name: string;
  operator: string;
  market: string;
  state: string;
  city: string;
  lat: number;
  lon: number;
  mw: number;
  sqft_k: number;
  tier: "Tier III" | "Tier IV";
  status: "Operational" | "Under Construction" | "Planned" | "Expanding";
  year_opened: number | null;
  source_url: string;
}

const DATA_CENTERS: DataCenter[] = [
  // Equinix — Northern Virginia
  { id: "eq-dc1",   name: "DC1 – Ashburn",          operator: "Equinix",        market: "Northern Virginia", state: "VA", city: "Ashburn",       lat: 39.0438, lon: -77.4874, mw: 100, sqft_k: 750,  tier: "Tier III", status: "Operational",        year_opened: 2000, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/ashburn-data-centers" },
  { id: "eq-dc2",   name: "DC2 – Ashburn",          operator: "Equinix",        market: "Northern Virginia", state: "VA", city: "Ashburn",       lat: 39.0440, lon: -77.4862, mw: 85,  sqft_k: 610,  tier: "Tier III", status: "Operational",        year_opened: 2002, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/ashburn-data-centers" },
  { id: "eq-dc3",   name: "DC3 – Ashburn",          operator: "Equinix",        market: "Northern Virginia", state: "VA", city: "Ashburn",       lat: 39.0442, lon: -77.4850, mw: 110, sqft_k: 800,  tier: "Tier III", status: "Operational",        year_opened: 2005, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/ashburn-data-centers" },
  { id: "eq-da1",   name: "DA1 – Dallas",           operator: "Equinix",        market: "Dallas",            state: "TX", city: "Dallas",        lat: 32.8208, lon: -96.8712, mw: 72,  sqft_k: 520,  tier: "Tier III", status: "Operational",        year_opened: 2001, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/dallas-data-centers" },
  { id: "eq-da2",   name: "DA2 – Dallas",           operator: "Equinix",        market: "Dallas",            state: "TX", city: "Dallas",        lat: 32.8210, lon: -96.8705, mw: 68,  sqft_k: 480,  tier: "Tier III", status: "Operational",        year_opened: 2004, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/dallas-data-centers" },
  { id: "eq-ch1",   name: "CH1 – Chicago",          operator: "Equinix",        market: "Chicago",           state: "IL", city: "Chicago",       lat: 41.8827, lon: -87.6233, mw: 90,  sqft_k: 660,  tier: "Tier III", status: "Operational",        year_opened: 2000, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/chicago-data-centers" },
  { id: "eq-sv1",   name: "SV1 – Silicon Valley",   operator: "Equinix",        market: "Silicon Valley",    state: "CA", city: "San Jose",      lat: 37.3382, lon: -121.8863, mw: 60, sqft_k: 430,  tier: "Tier III", status: "Operational",        year_opened: 1999, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/silicon-valley-data-centers" },
  { id: "eq-ny2",   name: "NY2 – New York",         operator: "Equinix",        market: "New York",          state: "NY", city: "Secaucus",      lat: 40.7795, lon: -74.0565, mw: 55,  sqft_k: 390,  tier: "Tier III", status: "Operational",        year_opened: 2003, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/new-york-data-centers" },
  { id: "eq-se2",   name: "SE2 – Seattle",          operator: "Equinix",        market: "Seattle",           state: "WA", city: "Seattle",       lat: 47.6062, lon: -122.3321, mw: 50, sqft_k: 360,  tier: "Tier III", status: "Operational",        year_opened: 2007, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/seattle-data-centers" },
  { id: "eq-at1",   name: "AT1 – Atlanta",          operator: "Equinix",        market: "Atlanta",           state: "GA", city: "Atlanta",       lat: 33.7490, lon: -84.3880, mw: 65,  sqft_k: 470,  tier: "Tier III", status: "Operational",        year_opened: 2000, source_url: "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/atlanta-data-centers" },

  // Digital Realty
  { id: "dr-iad1",  name: "IAD-01 – Ashburn",       operator: "Digital Realty", market: "Northern Virginia", state: "VA", city: "Ashburn",       lat: 39.0432, lon: -77.4910, mw: 130, sqft_k: 980,  tier: "Tier III", status: "Operational",        year_opened: 2007, source_url: "https://www.digitalrealty.com/data-centers/americas/northern-virginia" },
  { id: "dr-iad2",  name: "IAD-02 – Ashburn",       operator: "Digital Realty", market: "Northern Virginia", state: "VA", city: "Ashburn",       lat: 39.0434, lon: -77.4918, mw: 115, sqft_k: 840,  tier: "Tier III", status: "Operational",        year_opened: 2010, source_url: "https://www.digitalrealty.com/data-centers/americas/northern-virginia" },
  { id: "dr-dfw1",  name: "DFW-01 – Dallas",        operator: "Digital Realty", market: "Dallas",            state: "TX", city: "Richardson",    lat: 32.9483, lon: -96.7299, mw: 96,  sqft_k: 700,  tier: "Tier III", status: "Operational",        year_opened: 2005, source_url: "https://www.digitalrealty.com/data-centers/americas/dallas" },
  { id: "dr-chi1",  name: "CHI-01 – Chicago",       operator: "Digital Realty", market: "Chicago",           state: "IL", city: "Elk Grove",     lat: 41.9967, lon: -87.9973, mw: 88,  sqft_k: 640,  tier: "Tier III", status: "Operational",        year_opened: 2008, source_url: "https://www.digitalrealty.com/data-centers/americas/chicago" },
  { id: "dr-phx1",  name: "PHX-01 – Phoenix",       operator: "Digital Realty", market: "Phoenix",           state: "AZ", city: "Phoenix",        lat: 33.4484, lon: -112.0740, mw: 120, sqft_k: 880, tier: "Tier III", status: "Operational",        year_opened: 2012, source_url: "https://www.digitalrealty.com/data-centers/americas/phoenix" },
  { id: "dr-phx2",  name: "PHX-02 – Phoenix",       operator: "Digital Realty", market: "Phoenix",           state: "AZ", city: "Chandler",       lat: 33.3062, lon: -111.8413, mw: 105, sqft_k: 760, tier: "Tier III", status: "Under Construction", year_opened: null, source_url: "https://www.digitalrealty.com/data-centers/americas/phoenix" },
  { id: "dr-den1",  name: "DEN-01 – Denver",        operator: "Digital Realty", market: "Denver",            state: "CO", city: "Denver",         lat: 39.7392, lon: -104.9903, mw: 55, sqft_k: 400,  tier: "Tier III", status: "Operational",        year_opened: 2011, source_url: "https://www.digitalrealty.com/data-centers/americas/denver" },

  // CyrusOne
  { id: "cy-iad1",  name: "Northern Virginia I",    operator: "CyrusOne",       market: "Northern Virginia", state: "VA", city: "Manassas",      lat: 38.7509, lon: -77.4753, mw: 150, sqft_k: 1100, tier: "Tier III", status: "Operational",        year_opened: 2013, source_url: "https://cyrusone.com/locations/virginia/northern-virginia-manassas/" },
  { id: "cy-iad2",  name: "Northern Virginia II",   operator: "CyrusOne",       market: "Northern Virginia", state: "VA", city: "Sterling",       lat: 39.0062, lon: -77.3995, mw: 90,  sqft_k: 660,  tier: "Tier III", status: "Expanding",          year_opened: 2016, source_url: "https://cyrusone.com/locations/virginia/northern-virginia-sterling/" },
  { id: "cy-dfw1",  name: "Dallas I – Carrollton",  operator: "CyrusOne",       market: "Dallas",            state: "TX", city: "Carrollton",    lat: 32.9537, lon: -96.8903, mw: 100, sqft_k: 730,  tier: "Tier III", status: "Operational",        year_opened: 2009, source_url: "https://cyrusone.com/locations/texas/dallas-carrollton/" },
  { id: "cy-phx1",  name: "Phoenix I",              operator: "CyrusOne",       market: "Phoenix",           state: "AZ", city: "Chandler",       lat: 33.2946, lon: -111.8413, mw: 80,  sqft_k: 580, tier: "Tier III", status: "Operational",        year_opened: 2018, source_url: "https://cyrusone.com/locations/arizona/phoenix-chandler/" },
  { id: "cy-ch1",   name: "Chicago I",              operator: "CyrusOne",       market: "Chicago",           state: "IL", city: "Aurora",         lat: 41.7606, lon: -88.3201, mw: 72,  sqft_k: 520,  tier: "Tier III", status: "Operational",        year_opened: 2017, source_url: "https://cyrusone.com/locations/illinois/chicago-aurora/" },

  // QTS Data Centers
  { id: "qts-iad1", name: "Manassas Campus",        operator: "QTS",            market: "Northern Virginia", state: "VA", city: "Manassas",      lat: 38.7404, lon: -77.4748, mw: 200, sqft_k: 1500, tier: "Tier III", status: "Operational",        year_opened: 2010, source_url: "https://www.qtsdatacenters.com/data-centers/manassas-va" },
  { id: "qts-atl1", name: "Atlanta Metro",          operator: "QTS",            market: "Atlanta",           state: "GA", city: "Atlanta",        lat: 33.7490, lon: -84.3900, mw: 75,  sqft_k: 550,  tier: "Tier III", status: "Operational",        year_opened: 2007, source_url: "https://www.qtsdatacenters.com/data-centers/atlanta-ga" },
  { id: "qts-dfw1", name: "Irving Campus",          operator: "QTS",            market: "Dallas",            state: "TX", city: "Irving",         lat: 32.8140, lon: -96.9489, mw: 65,  sqft_k: 470,  tier: "Tier III", status: "Operational",        year_opened: 2012, source_url: "https://www.qtsdatacenters.com/data-centers/irving-tx" },

  // Iron Mountain Data Centers
  { id: "im-bos1",  name: "Boston I",               operator: "Iron Mountain",  market: "Boston",            state: "MA", city: "Boston",         lat: 42.3601, lon: -71.0589, mw: 40,  sqft_k: 290,  tier: "Tier III", status: "Operational",        year_opened: 2008, source_url: "https://www.ironmountain.com/resources/data-centers/boston" },
  { id: "im-phx1",  name: "Phoenix I",              operator: "Iron Mountain",  market: "Phoenix",           state: "AZ", city: "Scottsdale",     lat: 33.4942, lon: -111.9261, mw: 50,  sqft_k: 360, tier: "Tier III", status: "Operational",        year_opened: 2015, source_url: "https://www.ironmountain.com/resources/data-centers/phoenix" },

  // Switch
  { id: "sw-lv1",   name: "SUPERNAP 7 – Las Vegas", operator: "Switch",         market: "Las Vegas",         state: "NV", city: "Las Vegas",     lat: 36.1699, lon: -115.1398, mw: 177, sqft_k: 1300, tier: "Tier IV", status: "Operational",         year_opened: 2012, source_url: "https://www.switch.com/las-vegas/" },
  { id: "sw-lv2",   name: "SUPERNAP 8 – Las Vegas", operator: "Switch",         market: "Las Vegas",         state: "NV", city: "Las Vegas",     lat: 36.1701, lon: -115.1402, mw: 130, sqft_k: 950,  tier: "Tier IV", status: "Operational",        year_opened: 2016, source_url: "https://www.switch.com/las-vegas/" },
  { id: "sw-rno1",  name: "TAHOE RENO 1",           operator: "Switch",         market: "Reno",              state: "NV", city: "Reno",           lat: 39.5296, lon: -119.8138, mw: 250, sqft_k: 1800, tier: "Tier IV", status: "Operational",        year_opened: 2017, source_url: "https://www.switch.com/reno/" },
  { id: "sw-atl1",  name: "PYRAMID – Atlanta",      operator: "Switch",         market: "Atlanta",           state: "GA", city: "Atlanta",        lat: 33.7495, lon: -84.3900, mw: 55,  sqft_k: 400,  tier: "Tier IV", status: "Under Construction", year_opened: null, source_url: "https://www.switch.com/atlanta/" },

  // Vantage Data Centers
  { id: "vn-phx1",  name: "PHX01 – Phoenix",        operator: "Vantage",        market: "Phoenix",           state: "AZ", city: "Mesa",           lat: 33.4152, lon: -111.8315, mw: 108, sqft_k: 790,  tier: "Tier III", status: "Operational",       year_opened: 2019, source_url: "https://vantage-dc.com/data-centers/phoenix/" },
  { id: "vn-svk1",  name: "SVK01 – Silicon Valley", operator: "Vantage",        market: "Silicon Valley",    state: "CA", city: "San Jose",       lat: 37.3387, lon: -121.8870, mw: 70, sqft_k: 510,   tier: "Tier III", status: "Operational",       year_opened: 2021, source_url: "https://vantage-dc.com/data-centers/silicon-valley/" },
  { id: "vn-den1",  name: "DEN01 – Denver",         operator: "Vantage",        market: "Denver",            state: "CO", city: "Englewood",      lat: 39.6478, lon: -104.9877, mw: 60, sqft_k: 435,   tier: "Tier III", status: "Expanding",         year_opened: 2022, source_url: "https://vantage-dc.com/data-centers/denver/" },

  // NTT Global Data Centers
  { id: "nt-dc1",   name: "DCA-01 – Ashburn",       operator: "NTT",            market: "Northern Virginia", state: "VA", city: "Ashburn",        lat: 39.0445, lon: -77.4855, mw: 62,  sqft_k: 450,  tier: "Tier III", status: "Operational",        year_opened: 2014, source_url: "https://services.global.ntt/en-us/offerings/data-center-services" },
  { id: "nt-ch1",   name: "CHI-01 – Chicago",       operator: "NTT",            market: "Chicago",           state: "IL", city: "Lisle",          lat: 41.7959, lon: -88.0834, mw: 55,  sqft_k: 400,  tier: "Tier III", status: "Operational",        year_opened: 2011, source_url: "https://services.global.ntt/en-us/offerings/data-center-services" },

  // Flexential
  { id: "fx-sea1",  name: "Seattle – Tukwila",      operator: "Flexential",     market: "Seattle",           state: "WA", city: "Tukwila",        lat: 47.4740, lon: -122.2605, mw: 32, sqft_k: 235,   tier: "Tier III", status: "Operational",        year_opened: 2008, source_url: "https://www.flexential.com/data-centers/seattle-tukwila" },
  { id: "fx-den1",  name: "Denver – Englewood",     operator: "Flexential",     market: "Denver",            state: "CO", city: "Englewood",      lat: 39.6482, lon: -104.9880, mw: 28, sqft_k: 205,   tier: "Tier III", status: "Operational",        year_opened: 2010, source_url: "https://www.flexential.com/data-centers/denver-englewood" },

  // DataBank
  { id: "db-dal1",  name: "DAL-01 – Dallas",        operator: "DataBank",       market: "Dallas",            state: "TX", city: "Dallas",          lat: 32.8212, lon: -96.8720, mw: 45, sqft_k: 330,   tier: "Tier III", status: "Operational",        year_opened: 2009, source_url: "https://www.databank.com/data-centers/dallas/" },
  { id: "db-slc1",  name: "SLC-01 – Salt Lake City", operator: "DataBank",      market: "Salt Lake City",    state: "UT", city: "Salt Lake City",  lat: 40.7608, lon: -111.8910, mw: 30, sqft_k: 220,  tier: "Tier III", status: "Operational",        year_opened: 2018, source_url: "https://www.databank.com/data-centers/salt-lake-city/" },
  { id: "db-iad1",  name: "IAD-01 – Culpeper",      operator: "DataBank",       market: "Northern Virginia", state: "VA", city: "Culpeper",        lat: 38.4732, lon: -77.9966, mw: 60, sqft_k: 440,   tier: "Tier III", status: "Planned",            year_opened: null, source_url: "https://www.databank.com/data-centers/virginia/" },
];

// ── Color map ───────────────────────────────────────────────────────────────

const OPERATOR_COLORS: Record<string, string> = {
  "Equinix":        "#e31837",
  "Digital Realty": "#007dc6",
  "CyrusOne":       "#f59e0b",
  "QTS":            "#22c55e",
  "Iron Mountain":  "#a855f7",
  "Switch":         "#06b6d4",
  "Vantage":        "#f97316",
  "NTT":            "#3b82f6",
  "Flexential":     "#84cc16",
  "DataBank":       "#ec4899",
};

const STATUS_COLOR: Record<string, string> = {
  "Operational":        "#22c55e",
  "Under Construction": "#f59e0b",
  "Expanding":          "#3b82f6",
  "Planned":            "#94a3b8",
};

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const GMAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string;
setOptions({ key: GMAPS_KEY, v: "weekly" });

// ── Google Map component ────────────────────────────────────────────────────

function DCMap({
  centers, selected, onSelect,
}: {
  centers: DataCenter[];
  selected: DataCenter | null;
  onSelect: (dc: DataCenter | null) => void;
}) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<google.maps.Marker[]>([]);
  const infoWindowRef = useRef<google.maps.InfoWindow | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    if (!mapRef.current || centers.length === 0) return;
    async function init() {
      const { Map, InfoWindow } = await importLibrary("maps") as google.maps.MapsLibrary;
      const { Marker } = await importLibrary("marker") as google.maps.MarkerLibrary;
      if (!mapRef.current) return;

      const map = new Map(mapRef.current, {
        center: { lat: 38.5, lng: -98 },
        zoom: 4,
        mapTypeId: "satellite",
        tilt: 0,
        mapTypeControl: true,
        mapTypeControlOptions: {
          style: google.maps.MapTypeControlStyle.HORIZONTAL_BAR,
          position: google.maps.ControlPosition.TOP_RIGHT,
          mapTypeIds: ["satellite", "hybrid", "roadmap"],
        },
        streetViewControl: false,
        fullscreenControl: true,
        zoomControl: true,
      });
      mapInstanceRef.current = map;

      const infoWindow = new InfoWindow();
      infoWindowRef.current = infoWindow;

      markersRef.current.forEach(m => m.setMap(null));
      markersRef.current = [];

      centers.forEach(dc => {
        const color = OPERATOR_COLORS[dc.operator] ?? "#6366f1";
        const statusColor = STATUS_COLOR[dc.status] ?? "#64748b";
        const scale = Math.max(8, Math.min(22, dc.mw / 10));
        const marker = new Marker({
          position: { lat: dc.lat, lng: dc.lon },
          map,
          title: dc.name,
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            fillColor: color,
            fillOpacity: dc.status === "Operational" ? 0.85 : 0.45,
            strokeColor: statusColor,
            strokeWeight: 2,
            scale,
          },
        });

        const infoContent = `
          <div style="background:#1e293b;color:#e2e8f0;padding:14px 16px;border-radius:8px;min-width:240px;font-family:system-ui,sans-serif;border-top:3px solid ${color}">
            <div style="font-weight:700;font-size:13px;margin-bottom:2px;color:#fff">${dc.name}</div>
            <div style="font-size:11px;color:${color};font-weight:600;margin-bottom:8px">${dc.operator}</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
              <div><div style="color:#64748b;font-size:10px">Market</div><div style="color:#e2e8f0;font-size:12px">${dc.market}</div></div>
              <div><div style="color:#64748b;font-size:10px">State</div><div style="color:#e2e8f0;font-size:12px">${dc.state}</div></div>
              <div><div style="color:#64748b;font-size:10px">MW Capacity</div><div style="color:#fff;font-size:14px;font-weight:700">${dc.mw} MW</div></div>
              <div><div style="color:#64748b;font-size:10px">Sq Ft</div><div style="color:#e2e8f0;font-size:12px">${dc.sqft_k}K sqft</div></div>
              <div><div style="color:#64748b;font-size:10px">Tier</div><div style="color:#e2e8f0;font-size:12px">${dc.tier}</div></div>
              <div><div style="color:#64748b;font-size:10px">Status</div><div style="color:${statusColor};font-size:12px;font-weight:600">${dc.status}</div></div>
            </div>
            ${dc.year_opened ? `<div style="color:#475569;font-size:10px">Opened ${dc.year_opened}</div>` : ""}
          </div>`;

        marker.addListener("click", () => {
          infoWindow.setContent(infoContent);
          infoWindow.open(map, marker);
          map.panTo({ lat: dc.lat, lng: dc.lon });
          map.setZoom(10);
          onSelect(dc);
        });
        markersRef.current.push(marker);
      });
    }
    init().catch((err: unknown) => setMapError(String(err)));
    return () => { markersRef.current.forEach(m => m.setMap(null)); };
  }, [centers]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !selected) return;
    map.panTo({ lat: selected.lat, lng: selected.lon });
    map.setZoom(10);
  }, [selected]);

  if (mapError) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#ef4444", fontSize: 13, flexDirection: "column", gap: 8 }}>
      <AlertTriangle size={24} /><span>Map failed to load: {mapError}</span>
    </div>
  );

  return <div ref={mapRef} style={{ width: "100%", height: "100%", borderRadius: 8 }} />;
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
  const [filterOperator, setFilterOperator] = useState("All");
  const [filterState, setFilterState] = useState("All");
  const [filterStatus, setFilterStatus] = useState("All");
  const [sortField, setSortField] = useState<"mw" | "sqft_k" | "name">("mw");
  const [sortAsc, setSortAsc] = useState(false);
  const [selected, setSelected] = useState<DataCenter | null>(null);

  const operators = useMemo(() => ["All", ...Array.from(new Set(DATA_CENTERS.map(d => d.operator))).sort()], []);
  const states = useMemo(() => ["All", ...Array.from(new Set(DATA_CENTERS.map(d => d.state))).sort()], []);
  const statuses = useMemo(() => ["All", "Operational", "Under Construction", "Expanding", "Planned"], []);

  const filtered = useMemo(() => DATA_CENTERS.filter(d => {
    if (filterOperator !== "All" && d.operator !== filterOperator) return false;
    if (filterState !== "All" && d.state !== filterState) return false;
    if (filterStatus !== "All" && d.status !== filterStatus) return false;
    return true;
  }), [filterOperator, filterState, filterStatus]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = sortField === "name" ? a.name : a[sortField];
      const bv = sortField === "name" ? b.name : b[sortField];
      if (typeof av === "string") return sortAsc ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [filtered, sortField, sortAsc]);

  const toggleSort = (field: typeof sortField) => {
    if (sortField === field) setSortAsc(v => !v);
    else { setSortField(field); setSortAsc(false); }
  };

  // Aggregate by operator
  const byOperator = useMemo(() => {
    const map: Record<string, { mw: number; count: number }> = {};
    filtered.forEach(d => {
      if (!map[d.operator]) map[d.operator] = { mw: 0, count: 0 };
      map[d.operator].mw += d.mw;
      map[d.operator].count += 1;
    });
    return Object.entries(map)
      .map(([op, v]) => ({ operator: op, mw: v.mw, count: v.count }))
      .sort((a, b) => b.mw - a.mw);
  }, [filtered]);

  // Aggregate by state
  const byState = useMemo(() => {
    const map: Record<string, { mw: number; count: number }> = {};
    filtered.forEach(d => {
      if (!map[d.state]) map[d.state] = { mw: 0, count: 0 };
      map[d.state].mw += d.mw;
      map[d.state].count += 1;
    });
    return Object.entries(map)
      .map(([state, v]) => ({ state, mw: v.mw, count: v.count }))
      .sort((a, b) => b.mw - a.mw)
      .slice(0, 8);
  }, [filtered]);

  const totalMW = filtered.reduce((s, d) => s + d.mw, 0);
  const totalFacilities = filtered.length;
  const uniqueStates = new Set(filtered.map(d => d.state)).size;
  const uniqueOperators = new Set(filtered.map(d => d.operator)).size;

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
          <span style={{ color: "white", fontWeight: 600, fontSize: 14 }}>US Data Centers Overview</span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#0f172a", border: "1px solid #1d4ed8", color: "#60a5fa", fontSize: "10px", fontWeight: 600 }}>
            {DATA_CENTERS.length} facilities tracked
          </span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#1c1917", border: "1px solid #44403c", color: "#78716c", fontSize: "9px", fontWeight: 600 }}>
            MOCK
          </span>
        </div>
        <div style={{ color: "#64748b", fontSize: "11px" }}>
          Inspired by Aterio US Data Centers Dashboard · Major colocation providers
        </div>
      </div>

      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <MetricCard label="Total Facilities"   value={String(totalFacilities)} sub={`${uniqueOperators} operators`}             accent="#3b82f6"  icon={Building2} />
        <MetricCard label="Total MW Capacity"  value={totalMW.toLocaleString()} unit="MW"  sub="IT load capacity"               accent="#f59e0b"  icon={Zap} />
        <MetricCard label="US States / Markets" value={String(uniqueStates)}     sub="geographic markets"                       accent="#22c55e"  icon={MapPin} />
        <MetricCard label="Operational"
          value={String(filtered.filter(d => d.status === "Operational").length)}
          sub={`${filtered.filter(d => d.status !== "Operational").length} under construction / planned`}
          accent="#22c55e" icon={Server}
        />
      </div>

      {/* Filter bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Filter size={13} color="#64748b" />
        <span style={{ color: "#64748b", fontSize: "12px" }}>Filter:</span>
        <select value={filterOperator} onChange={e => setFilterOperator(e.target.value)} style={filterSelectStyle}>
          {operators.map(o => <option key={o}>{o}</option>)}
        </select>
        <select value={filterState} onChange={e => setFilterState(e.target.value)} style={filterSelectStyle}>
          {states.map(s => <option key={s}>{s}</option>)}
        </select>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} style={filterSelectStyle}>
          {statuses.map(s => <option key={s}>{s}</option>)}
        </select>
        {(filterOperator !== "All" || filterState !== "All" || filterStatus !== "All") && (
          <button
            onClick={() => { setFilterOperator("All"); setFilterState("All"); setFilterStatus("All"); }}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 6, background: "#1e293b", border: "1px solid #334155", color: "#94a3b8", cursor: "pointer", fontSize: "12px" }}
          >
            <X size={11} /> Clear
          </button>
        )}
        <span style={{ marginLeft: "auto", color: "#64748b", fontSize: "11px" }}>{filtered.length} facilities shown</span>
      </div>

      {/* Map */}
      <div style={{ ...CARD_STYLE, padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #334155", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Data Center Locations</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "3px 0 0" }}>
              Bubble size proportional to MW capacity · Click any marker to inspect · Colored by operator
            </p>
          </div>
          {selected && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, background: "#0f172a", border: "1px solid #334155", borderRadius: 6, padding: "6px 12px" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: OPERATOR_COLORS[selected.operator] ?? "#6366f1" }} />
              <span style={{ color: "white", fontSize: "12px", fontWeight: 600 }}>{selected.name}</span>
              <button onClick={() => setSelected(null)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", padding: 0, display: "flex" }}><X size={12} /></button>
            </div>
          )}
        </div>
        <div style={{ height: 440 }}>
          <DCMap centers={filtered} selected={selected} onSelect={setSelected} />
        </div>
        {/* Legend */}
        <div style={{ padding: "10px 18px", borderTop: "1px solid #1e293b", display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ color: "#475569", fontSize: "10px", fontWeight: 600 }}>OPERATORS</span>
          {Object.entries(OPERATOR_COLORS).map(([op, color]) => (
            <div key={op} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{ width: 9, height: 9, borderRadius: "50%", background: color }} />
              <span style={{ color: "#94a3b8", fontSize: "10px" }}>{op}</span>
            </div>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", gap: 14 }}>
            {Object.entries(STATUS_COLOR).map(([s, c]) => (
              <div key={s} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", border: `2px solid ${c}` }} />
                <span style={{ color: "#64748b", fontSize: "10px" }}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {/* By Operator */}
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 300 }}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: "0 0 4px" }}>MW Capacity by Operator</h3>
          <p style={{ color: "#64748b", fontSize: "11px", margin: "0 0 14px" }}>Total IT load capacity across tracked facilities</p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byOperator} layout="vertical" margin={{ left: 4, right: 24, top: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
              <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit=" MW" />
              <YAxis type="category" dataKey="operator" tick={{ fill: "#94a3b8", fontSize: 10 }} width={100} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "white" }}
                formatter={(v: unknown, _n: string, props: { payload?: DataCenter }) => {
                  const op = props?.payload?.operator ?? "";
                  const entry = byOperator.find(e => e.operator === op);
                  return [`${v} MW (${entry?.count ?? 0} facilities)`, "Capacity"];
                }}
              />
              <Bar dataKey="mw" radius={[0, 4, 4, 0]}>
                {byOperator.map((entry, i) => (
                  <Cell key={i} fill={OPERATOR_COLORS[entry.operator] ?? "#6366f1"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* By State */}
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 280 }}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: "0 0 4px" }}>MW Capacity by State</h3>
          <p style={{ color: "#64748b", fontSize: "11px", margin: "0 0 14px" }}>Top 8 states by total MW · Northern Virginia dominates</p>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byState} layout="vertical" margin={{ left: 4, right: 24, top: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
              <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit=" MW" />
              <YAxis type="category" dataKey="state" tick={{ fill: "#94a3b8", fontSize: 11 }} width={30} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "white" }}
                formatter={(v: unknown, _n: string, props: { payload?: { count?: number } }) => [
                  `${v} MW (${props?.payload?.count ?? 0} facilities)`, "Capacity",
                ]}
              />
              <Bar dataKey="mw" fill="#3b82f6" radius={[0, 4, 4, 0]}>
                {byState.map((_, i) => (
                  <Cell key={i} fill={`hsl(${210 + i * 12}, 80%, ${60 - i * 3}%)`} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Data table */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Facility Directory</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>{sorted.length} facilities · click column headers to sort</p>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                {[
                  { label: "Operator",   field: null },
                  { label: "Facility",   field: "name" as const },
                  { label: "Market",     field: null },
                  { label: "State",      field: null },
                  { label: "MW",         field: "mw" as const },
                  { label: "Sq Ft (K)",  field: "sqft_k" as const },
                  { label: "Tier",       field: null },
                  { label: "Status",     field: null },
                  { label: "Opened",     field: null },
                  { label: "Source",     field: null },
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
              {sorted.map(dc => {
                const color = OPERATOR_COLORS[dc.operator] ?? "#6366f1";
                const statusColor = STATUS_COLOR[dc.status] ?? "#94a3b8";
                const isSelected = selected?.id === dc.id;
                return (
                  <tr key={dc.id}
                    onClick={() => setSelected(isSelected ? null : dc)}
                    style={{
                      borderBottom: "1px solid #1e293b",
                      cursor: "pointer",
                      background: isSelected ? "#162032" : "transparent",
                      transition: "background 0.1s",
                    }}
                  >
                    <td style={{ padding: "9px 12px" }}>
                      <span style={{ padding: "2px 8px", borderRadius: 4, background: `${color}22`, color, fontSize: "11px", fontWeight: 600 }}>
                        {dc.operator}
                      </span>
                    </td>
                    <td style={{ padding: "9px 12px", color: "#e2e8f0", fontWeight: 500 }}>{dc.name}</td>
                    <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{dc.market}</td>
                    <td style={{ padding: "9px 12px", color: "#94a3b8", fontSize: "11px" }}>{dc.state}</td>
                    <td style={{ padding: "9px 12px", color: "white", fontWeight: 700 }}>{dc.mw}</td>
                    <td style={{ padding: "9px 12px", color: "#94a3b8" }}>{dc.sqft_k}K</td>
                    <td style={{ padding: "9px 12px", color: "#64748b", fontSize: "11px" }}>{dc.tier}</td>
                    <td style={{ padding: "9px 12px" }}>
                      <span style={{ color: statusColor, fontSize: "11px" }}>● {dc.status}</span>
                    </td>
                    <td style={{ padding: "9px 12px", color: "#64748b", fontSize: "11px" }}>{dc.year_opened ?? "—"}</td>
                    <td style={{ padding: "9px 12px" }}>
                      <a href={dc.source_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
                        style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "2px 7px", borderRadius: 4, background: "#0f1e38", border: "1px solid #2563eb", color: "#60a5fa", fontSize: "10px", textDecoration: "none" }}>
                        <ExternalLink size={9} />Link
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
