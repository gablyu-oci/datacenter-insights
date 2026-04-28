import React, { useEffect, useRef, useState, useCallback } from "react";
import { setOptions, importLibrary } from "@googlemaps/js-api-loader";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { SatelliteSite } from "../../types";
import {
  CheckCircle, Clock, AlertTriangle, MapPin, Satellite,
  ZoomIn, Video, X, RotateCcw, Eye, Layers,
  ExternalLink, History, TrendingUp, GitBranch,
} from "lucide-react";

interface SatResponse { data: SatelliteSite[]; colors: Record<string, string>; }

interface AerialVideoData {
  videoUrl: string;
  thumbUrl: string;
  captureDate: { year: number; month: number; day: number };
  duration: string;
}

// ESRI Wayback imagery releases — key dated snapshots free to use, no API key required.
// Release IDs from https://wayback.maptiles.arcgis.com config.
const WAYBACK_RELEASES: { year: string; label: string; releaseId: number }[] = [
  { year: "2019", label: "Early 2019", releaseId: 10 },
  { year: "2020", label: "Early 2020", releaseId: 20 },
  { year: "2021", label: "Early 2021", releaseId: 30 },
  { year: "2022", label: "Early 2022", releaseId: 40 },
  { year: "2023", label: "Early 2023", releaseId: 54 },
  { year: "2024", label: "Early 2024", releaseId: 62 },
];

const STATUS_COLOR: Record<string, string> = {
  "Operational": "#22c55e",
  "Active Construction": "#f59e0b",
  "Expanding": "#3b82f6",
  "Land Prep": "#94a3b8",
};

const STATUS_ICON: Record<string, React.ReactNode> = {
  "Operational": <CheckCircle size={14} color="#22c55e" />,
  "Active Construction": <AlertTriangle size={14} color="#f59e0b" />,
  "Expanding": <Clock size={14} color="#3b82f6" />,
  "Land Prep": <MapPin size={14} color="#94a3b8" />,
};

const MILESTONE_COLOR: Record<string, string> = {
  announcement: "#3b82f6",
  permit: "#f59e0b",
  construction: "#22c55e",
  milestone: "#a855f7",
  projected: "#475569",
};

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const GMAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string;
setOptions({ key: GMAPS_KEY, v: "weekly" });

// ── Aerial View API ────────────────────────────────────────────────────────

async function fetchAerialVideo(address: string): Promise<AerialVideoData | null> {
  const url = `https://aerialview.googleapis.com/v1/videos:lookupVideo?key=${GMAPS_KEY}&address=${encodeURIComponent(address)}`;
  const res = await fetch(url);
  const data = await res.json();
  if (data.state !== "ACTIVE") return null;
  return {
    videoUrl: data.uris?.MP4_HIGH?.landscapeUri ?? data.uris?.MP4_MEDIUM?.landscapeUri ?? "",
    thumbUrl: data.uris?.IMAGE?.landscapeUri ?? "",
    captureDate: data.metadata?.captureDate ?? { year: 0, month: 0, day: 0 },
    duration: data.metadata?.duration ?? "",
  };
}

// ── Aerial video modal ─────────────────────────────────────────────────────

function AerialModal({ site, onClose }: { site: SatelliteSite; onClose: () => void }) {
  const [state, setState] = useState<"loading" | "active" | "not_found">("loading");
  const [video, setVideo] = useState<AerialVideoData | null>(null);

  useEffect(() => {
    setState("loading");
    fetchAerialVideo(site.address)
      .then(v => { setVideo(v); setState(v ? "active" : "not_found"); })
      .catch(() => setState("not_found"));
  }, [site.address]);

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 200, background: "rgba(0,0,0,0.85)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: "#0f172a", border: "1px solid #334155", borderTop: "3px solid #3b82f6", borderRadius: 14, width: "100%", maxWidth: 720, overflow: "hidden", boxShadow: "0 32px 80px rgba(0,0,0,0.7)" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #1e293b", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <Video size={15} color="#3b82f6" />
              <span style={{ color: "white", fontWeight: 700, fontSize: 15 }}>Aerial View</span>
              <span style={{ padding: "1px 7px", borderRadius: 4, background: "#0f1e38", border: "1px solid #2563eb", color: "#60a5fa", fontSize: "9px", fontWeight: 700 }}>GOOGLE AERIAL VIEW API</span>
            </div>
            <div style={{ color: "#64748b", fontSize: 12 }}>{site.name} · {site.address}</div>
          </div>
          <button onClick={onClose} style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 6, padding: "5px 7px", cursor: "pointer", color: "#94a3b8", display: "flex" }}><X size={14} /></button>
        </div>
        <div style={{ padding: 20 }}>
          {state === "loading" && (
            <div style={{ height: 300, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12 }}>
              <div style={{ width: 36, height: 36, border: "3px solid #1e293b", borderTop: "3px solid #3b82f6", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
              <div style={{ color: "#64748b", fontSize: 13 }}>Fetching aerial footage…</div>
              <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            </div>
          )}
          {state === "not_found" && (
            <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12, textAlign: "center" }}>
              <Video size={32} color="#334155" />
              <div style={{ color: "#64748b", fontSize: 13 }}>No aerial footage available for this location.</div>
              <div style={{ color: "#475569", fontSize: 11 }}>Use the 45° tilt view on the map for an aerial perspective, or the Progress History mode to see construction changes over time.</div>
            </div>
          )}
          {state === "active" && video && (
            <div>
              <div style={{ position: "relative", borderRadius: 10, overflow: "hidden", background: "#000", marginBottom: 14 }}>
                <video src={video.videoUrl} poster={video.thumbUrl} controls autoPlay loop muted style={{ width: "100%", display: "block", maxHeight: 380, objectFit: "cover" }} />
                <div style={{ position: "absolute", top: 8, left: 8, padding: "2px 8px", borderRadius: 4, background: "rgba(0,0,0,0.7)", border: "1px solid #334155", color: "#22c55e", fontSize: "10px", fontWeight: 600 }}>● LIVE AERIAL</div>
              </div>
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                {[
                  { label: "Location", value: site.address },
                  { label: "Captured", value: `${video.captureDate.year}-${String(video.captureDate.month).padStart(2, "0")}-${String(video.captureDate.day).padStart(2, "0")}` },
                  { label: "Duration", value: video.duration },
                  { label: "Source", value: "Google Aerial View API" },
                ].map(({ label, value }) => (
                  <div key={label}>
                    <div style={{ color: "#64748b", fontSize: "10px" }}>{label}</div>
                    <div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2 }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Construction milestone timeline ────────────────────────────────────────

function MilestoneTimeline({ site, companyColor }: { site: SatelliteSite; companyColor: string }) {
  const milestones = site.milestones ?? [];
  if (milestones.length === 0) return null;

  const now = new Date();
  const past = milestones.filter(m => new Date(m.date) <= now);
  const future = milestones.filter(m => new Date(m.date) > now);

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ color: "#64748b", fontSize: "10px", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>
        Construction Timeline
      </div>
      <div style={{ position: "relative" }}>
        {/* Vertical spine */}
        <div style={{ position: "absolute", left: 7, top: 8, bottom: 8, width: 2, background: "#1e293b" }} />

        {milestones.map((m, i) => {
          const isPast = new Date(m.date) <= now;
          const isProjected = m.type === "projected";
          const dotColor = isPast ? (MILESTONE_COLOR[m.type] ?? companyColor) : "#334155";
          return (
            <div key={i} style={{ display: "flex", gap: 12, marginBottom: 10, position: "relative" }}>
              <div style={{
                width: 16, height: 16, borderRadius: "50%", flexShrink: 0, marginTop: 1,
                background: isPast ? dotColor : "#0f172a",
                border: `2px solid ${dotColor}`,
                zIndex: 1,
              }} />
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <span style={{
                    color: isPast ? "#e2e8f0" : "#475569",
                    fontSize: "12px", fontWeight: isPast ? 500 : 400,
                    fontStyle: isProjected ? "italic" : "normal",
                  }}>
                    {m.label}
                  </span>
                  {isProjected && (
                    <span style={{ color: "#475569", fontSize: "9px", fontWeight: 600, letterSpacing: "0.05em" }}>PROJECTED</span>
                  )}
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 2 }}>
                  <span style={{ color: "#475569", fontSize: "10px" }}>{m.date.slice(0, 7)}</span>
                  <span style={{ color: dotColor, fontSize: "10px" }}>{m.pct}% complete</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Velocity note */}
      {past.length >= 2 && (
        <div style={{ background: "#0f172a", borderRadius: 6, padding: "8px 10px", marginTop: 6 }}>
          <div style={{ color: "#64748b", fontSize: "10px", marginBottom: 3 }}>Build velocity estimate</div>
          <div style={{ color: "#e2e8f0", fontSize: "12px" }}>
            {(() => {
              const first = past[0];
              const last = past[past.length - 1];
              const months = Math.max(1, (new Date(last.date).getTime() - new Date(first.date).getTime()) / (1000 * 60 * 60 * 24 * 30));
              const pctPerMonth = ((last.pct - first.pct) / months).toFixed(1);
              const acrPerMonth = (site.size_acres * (last.pct - first.pct) / 100 / months).toFixed(1);
              return `~${pctPerMonth}% / month · ~${acrPerMonth} acres developed / month`;
            })()}
          </div>
          {future.length > 0 && (
            <div style={{ color: "#64748b", fontSize: "11px", marginTop: 4 }}>
              Next: <span style={{ color: "#94a3b8" }}>{future[0].label}</span>
              <span style={{ color: "#475569" }}> · {future[0].date.slice(0, 7)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Build velocity comparison chart ───────────────────────────────────────

function VelocityChart({ sites, colors }: { sites: SatelliteSite[]; colors: Record<string, string> }) {
  const data = sites
    .filter(s => (s.milestones ?? []).length >= 2 && s.construction_pct < 100)
    .map(s => {
      const ms = s.milestones!;
      const now = new Date();
      const past = ms.filter(m => new Date(m.date) <= now);
      if (past.length < 2) return null;
      const first = past[0];
      const last = past[past.length - 1];
      const months = Math.max(1, (new Date(last.date).getTime() - new Date(first.date).getTime()) / (1000 * 60 * 60 * 24 * 30));
      const velocity = parseFloat(((last.pct - first.pct) / months).toFixed(2));
      return { name: s.name.replace(" Campus", "").replace(" Data Center", ""), company: s.company, velocity, pct: s.construction_pct };
    })
    .filter(Boolean)
    .sort((a, b) => b!.velocity - a!.velocity) as { name: string; company: string; velocity: number; pct: number }[];

  if (data.length === 0) return null;

  return (
    <div style={CARD_STYLE}>
      <div style={{ marginBottom: 14 }}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <TrendingUp size={14} color="#3b82f6" />
          Build Velocity — Active Sites (% completion / month)
        </h3>
        <p style={{ color: "#64748b", fontSize: "11px", margin: "4px 0 0" }}>
          Derived from public milestone dates · higher = faster construction pace
        </p>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
          <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} unit="%" domain={[0, "dataMax + 0.5"]} />
          <YAxis type="category" dataKey="name" tick={{ fill: "#94a3b8", fontSize: 10 }} width={160} />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "white" }}
            formatter={(v: unknown) => [`${v}% / month`, "Build velocity"]}
          />
          <Bar dataKey="velocity" radius={[0, 4, 4, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={colors[entry.company] ?? "#3b82f6"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Google Maps + ESRI Wayback progress overlay ───────────────────────────

type ViewMode = "satellite" | "aerial" | "progress";

function SatelliteMap({
  sites, colors, selectedSite, onSelectSite, viewMode,
  waybackReleaseId, waybackOpacity,
}: {
  sites: SatelliteSite[];
  colors: Record<string, string>;
  selectedSite: SatelliteSite | null;
  onSelectSite: (s: SatelliteSite | null) => void;
  viewMode: ViewMode;
  waybackReleaseId: number;
  waybackOpacity: number;
}) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<google.maps.Marker[]>([]);
  const infoWindowRef = useRef<google.maps.InfoWindow | null>(null);
  const waybackLayerRef = useRef<google.maps.ImageMapType | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [heading, setHeading] = useState(0);

  useEffect(() => {
    if (!mapRef.current || sites.length === 0) return;
    async function init() {
      const { Map, InfoWindow } = await importLibrary("maps") as google.maps.MapsLibrary;
      const { Marker } = await importLibrary("marker") as google.maps.MarkerLibrary;
      if (!mapRef.current) return;

      const map = new Map(mapRef.current, {
        center: { lat: 38.5, lng: -96 },
        zoom: 5,
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

      // ESRI Wayback overlay layer
      const waybackLayer = new google.maps.ImageMapType({
        getTileUrl: (coord: google.maps.Point, zoom: number) =>
          `https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/${waybackReleaseId}/${zoom}/${coord.y}/${coord.x}`,
        tileSize: new google.maps.Size(256, 256),
        opacity: 0,
        name: "Historical Imagery",
        maxZoom: 19,
      });
      waybackLayerRef.current = waybackLayer;
      map.overlayMapTypes.push(waybackLayer);

      const infoWindow = new InfoWindow();
      infoWindowRef.current = infoWindow;

      markersRef.current.forEach(m => m.setMap(null));
      markersRef.current = [];

      sites.forEach(site => {
        const companyColor = colors[site.company] ?? "#6366f1";
        const statusColor = STATUS_COLOR[site.status] ?? "#64748b";
        const marker = new Marker({
          position: { lat: site.lat, lng: site.lon },
          map,
          title: site.name,
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            fillColor: companyColor,
            fillOpacity: 0.9,
            strokeColor: statusColor,
            strokeWeight: 3,
            scale: site.size_acres > 150 ? 14 : 10,
          },
          animation: google.maps.Animation.DROP,
        });

        const infoContent = `
          <div style="background:#1e293b;color:#e2e8f0;padding:12px 14px;border-radius:8px;min-width:220px;font-family:system-ui,sans-serif;">
            <div style="font-weight:700;font-size:13px;margin-bottom:4px;color:#fff">${site.name}</div>
            <div style="font-size:11px;color:#94a3b8;margin-bottom:8px">${site.company}</div>
            <div style="display:flex;gap:16px;margin-bottom:8px">
              <div><div style="color:#64748b;font-size:10px">Status</div><div style="color:${statusColor};font-size:12px;font-weight:600">${site.status}</div></div>
              <div><div style="color:#64748b;font-size:10px">Size</div><div style="color:#e2e8f0;font-size:12px">${site.size_acres} acres</div></div>
              <div><div style="color:#64748b;font-size:10px">Complete</div><div style="color:#e2e8f0;font-size:12px">${site.construction_pct}%</div></div>
            </div>
            <div style="background:#0f172a;border-radius:4px;height:6px;margin-bottom:8px">
              <div style="background:${statusColor};border-radius:4px;height:6px;width:${site.construction_pct}%"></div>
            </div>
            <div style="color:#475569;font-size:10px">${site.lat.toFixed(4)}, ${site.lon.toFixed(4)}</div>
          </div>`;

        marker.addListener("click", () => {
          infoWindow.setContent(infoContent);
          infoWindow.open(map, marker);
          map.panTo({ lat: site.lat, lng: site.lon });
          map.setZoom(viewMode === "aerial" ? 17 : viewMode === "progress" ? 16 : 13);
          if (viewMode === "aerial") map.setTilt(45);
          onSelectSite(site);
        });
        markersRef.current.push(marker);
      });
    }
    init().catch((err: unknown) => setMapError(String(err)));
    return () => { markersRef.current.forEach(m => m.setMap(null)); };
  }, [sites, colors]);

  // Update Wayback release when year changes (rebuild overlay tile source)
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    // Remove old overlay and rebuild with new release ID
    map.overlayMapTypes.clear();
    const layer = new google.maps.ImageMapType({
      getTileUrl: (coord: google.maps.Point, zoom: number) =>
        `https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/${waybackReleaseId}/${zoom}/${coord.y}/${coord.x}`,
      tileSize: new google.maps.Size(256, 256),
      opacity: viewMode === "progress" ? waybackOpacity : 0,
      name: "Historical Imagery",
      maxZoom: 19,
    });
    waybackLayerRef.current = layer;
    map.overlayMapTypes.push(layer);
  }, [waybackReleaseId]);

  // Update opacity without rebuilding
  useEffect(() => {
    const layer = waybackLayerRef.current;
    if (!layer) return;
    layer.setOpacity(viewMode === "progress" ? waybackOpacity : 0);
  }, [waybackOpacity, viewMode]);

  // Aerial tilt + pan
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    if (viewMode === "aerial" && selectedSite) {
      map.setTilt(45); map.setZoom(17);
      map.setHeading(heading);
      map.panTo({ lat: selectedSite.lat, lng: selectedSite.lon });
    } else if (viewMode === "aerial") {
      map.setTilt(45); map.setZoom(Math.max(map.getZoom() ?? 5, 12));
    } else {
      map.setTilt(0); map.setHeading(0);
    }
  }, [viewMode, selectedSite, heading]);

  // Pan to selected site from card
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !selectedSite) return;
    map.panTo({ lat: selectedSite.lat, lng: selectedSite.lon });
    const zoom = viewMode === "aerial" ? 17 : viewMode === "progress" ? 16 : 13;
    map.setZoom(zoom);
    if (viewMode === "aerial") { map.setTilt(45); map.setHeading(heading); }
  }, [selectedSite]);

  const rotateLeft = useCallback(() => setHeading(h => (h - 45 + 360) % 360), []);
  const rotateRight = useCallback(() => setHeading(h => (h + 45) % 360), []);

  if (mapError) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#ef4444", fontSize: 13, flexDirection: "column", gap: 8 }}>
      <AlertTriangle size={24} /><span>Google Maps failed to load: {mapError}</span>
    </div>
  );

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <div ref={mapRef} style={{ width: "100%", height: "100%", borderRadius: 8 }} />

      {/* Aerial heading controls */}
      {viewMode === "aerial" && selectedSite && (
        <div style={{ position: "absolute", bottom: 16, left: "50%", transform: "translateX(-50%)", display: "flex", alignItems: "center", gap: 8, background: "rgba(15,23,42,0.92)", border: "1px solid #334155", borderRadius: 8, padding: "8px 14px" }}>
          <button onClick={rotateLeft} style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 5, padding: "4px 8px", color: "#94a3b8", cursor: "pointer", display: "flex", alignItems: "center" }}><RotateCcw size={13} /></button>
          <span style={{ color: "#64748b", fontSize: "11px" }}>Heading {heading}°</span>
          <button onClick={rotateRight} style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 5, padding: "4px 8px", color: "#94a3b8", cursor: "pointer", display: "flex", alignItems: "center", transform: "scaleX(-1)" }}><RotateCcw size={13} /></button>
          <div style={{ width: 1, height: 16, background: "#334155", margin: "0 4px" }} />
          <span style={{ color: "#475569", fontSize: "10px" }}>45° tilt · oblique view</span>
        </div>
      )}

      {/* Progress mode watermark */}
      {viewMode === "progress" && (
        <div style={{ position: "absolute", bottom: 16, left: 16, background: "rgba(15,23,42,0.9)", border: "1px solid #334155", borderRadius: 6, padding: "5px 10px", fontSize: "10px", color: "#64748b" }}>
          <span style={{ color: "#f59e0b" }}>Historical layer: </span>ESRI World Imagery Wayback · blended over current satellite
        </div>
      )}
    </div>
  );
}

// ── Progress History panel ─────────────────────────────────────────────────

function ProgressPanel({
  sites, colors, selectedSite, onSelectSite,
  waybackYear, onYearChange,
  waybackOpacity, onOpacityChange,
}: {
  sites: SatelliteSite[];
  colors: Record<string, string>;
  selectedSite: SatelliteSite | null;
  onSelectSite: (s: SatelliteSite | null) => void;
  waybackYear: string;
  onYearChange: (y: string) => void;
  waybackOpacity: number;
  onOpacityChange: (v: number) => void;
}) {
  const site = selectedSite ?? sites[0];

  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
      {/* Controls */}
      <div style={{ ...CARD_STYLE, flex: "0 0 auto", minWidth: 260, maxWidth: 300 }}>
        <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 12 }}>
          Historical Imagery Controls
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ color: "#64748b", fontSize: "10px", marginBottom: 6 }}>Reference Year</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {WAYBACK_RELEASES.map(r => (
              <button
                key={r.year}
                onClick={() => onYearChange(r.year)}
                style={{
                  padding: "4px 10px", borderRadius: 5, border: "none", cursor: "pointer", fontSize: "11px",
                  fontWeight: waybackYear === r.year ? 600 : 400,
                  background: waybackYear === r.year ? "#2563eb" : "#1e293b",
                  color: waybackYear === r.year ? "white" : "#64748b",
                }}
              >{r.year}</button>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
            <span style={{ color: "#64748b", fontSize: "10px" }}>Historical Layer Opacity</span>
            <span style={{ color: "#e2e8f0", fontSize: "10px", fontWeight: 600 }}>{Math.round(waybackOpacity * 100)}%</span>
          </div>
          <input
            type="range" min={0} max={100} value={Math.round(waybackOpacity * 100)}
            onChange={e => onOpacityChange(Number(e.target.value) / 100)}
            style={{ width: "100%", accentColor: "#3b82f6" }}
          />
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "#475569", fontSize: "9px" }}>Current only</span>
            <span style={{ color: "#475569", fontSize: "9px" }}>Historical only</span>
          </div>
        </div>

        <div style={{ background: "#0f172a", borderRadius: 8, padding: "10px 12px", border: "1px solid #1e293b" }}>
          <div style={{ color: "#64748b", fontSize: "10px", marginBottom: 4 }}>How to use</div>
          <div style={{ color: "#94a3b8", fontSize: "11px", lineHeight: 1.6 }}>
            Select a reference year, then slide opacity to blend older imagery with current satellite. Click a site on the map or a card below to pan and view its construction progress.
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <div style={{ color: "#475569", fontSize: "9px", lineHeight: 1.6 }}>
            Imagery via <a href="https://livingatlas.arcgis.com/wayback/" target="_blank" rel="noreferrer" style={{ color: "#3b82f6" }}>ESRI World Imagery Wayback</a> · high-resolution historical imagery archive · free public access
          </div>
        </div>
      </div>

      {/* Site milestone panel */}
      {site && (
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 280, maxWidth: 420, overflowY: "auto", maxHeight: 460 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <div>
              <div style={{ color: "white", fontWeight: 600, fontSize: 13 }}>{site.name}</div>
              <div style={{ color: "#64748b", fontSize: "11px" }}>{site.company} · {site.address}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              {STATUS_ICON[site.status]}
              <span style={{ color: STATUS_COLOR[site.status], fontSize: "11px" }}>{site.status}</span>
            </div>
          </div>

          {/* Completion bar */}
          <div style={{ background: "#0f172a", borderRadius: 4, height: 6, marginBottom: 6 }}>
            <div style={{ background: colors[site.company] ?? "#3b82f6", borderRadius: 4, height: 6, width: `${site.construction_pct}%`, transition: "width 0.4s" }} />
          </div>
          <div style={{ color: "#64748b", fontSize: "10px", marginBottom: 12 }}>{site.construction_pct}% complete · {site.size_acres} acres</div>

          <MilestoneTimeline site={site} companyColor={colors[site.company] ?? "#3b82f6"} />
        </div>
      )}

      {/* Site selector if no site chosen */}
      {!selectedSite && sites.length > 0 && (
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ color: "#64748b", fontSize: "11px", marginBottom: 8 }}>Click a site on the map, or select below:</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {sites.filter(s => s.status !== "Operational").map((s, i) => (
              <button key={i} onClick={() => onSelectSite(s)} style={{
                background: "#1e293b", border: `1px solid ${colors[s.company] ?? "#334155"}40`,
                borderLeft: `3px solid ${colors[s.company] ?? "#334155"}`,
                borderRadius: 6, padding: "8px 12px", cursor: "pointer", textAlign: "left",
              }}>
                <div style={{ color: "white", fontSize: "12px", fontWeight: 500 }}>{s.name}</div>
                <div style={{ color: "#64748b", fontSize: "10px" }}>{s.company} · {s.construction_pct}%</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function SatelliteTab() {
  const { data, loading } = useApi<SatResponse>("/api/satellite");
  const [selectedSite, setSelectedSite] = useState<SatelliteSite | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("satellite");
  const [aerialSite, setAerialSite] = useState<SatelliteSite | null>(null);
  const [waybackYear, setWaybackYear] = useState("2021");
  const [waybackOpacity, setWaybackOpacity] = useState(0.5);

  if (loading) return <PageLoader />;

  const sites = data?.data ?? [];
  const colors = data?.colors ?? {};

  const byStatus = {
    Operational: sites.filter(s => s.status === "Operational").length,
    "Active Construction": sites.filter(s => s.status === "Active Construction").length,
    Expanding: sites.filter(s => s.status === "Expanding").length,
    "Land Prep": sites.filter(s => s.status === "Land Prep").length,
  };

  const waybackRelease = WAYBACK_RELEASES.find(r => r.year === waybackYear) ?? WAYBACK_RELEASES[2];

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>

      {aerialSite && <AerialModal site={aerialSite} onClose={() => setAerialSite(null)} />}

      {/* Header banner */}
      <div style={{ background: "linear-gradient(135deg, #0c1a2e 0%, #0f2744 100%)", border: "1px solid #1d4ed8", borderRadius: 10, padding: "12px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Satellite size={16} color="#3b82f6" />
          <span style={{ color: "white", fontWeight: 600, fontSize: 13 }}>Buildout Satellite Site Intelligence</span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#0f172a", border: "1px solid #1d4ed8", color: "#60a5fa", fontSize: "10px", fontWeight: 600 }}>
            {sites.length} publicly announced sites
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ padding: "3px 9px", borderRadius: 5, background: "#0f1e38", border: "1px solid #2563eb", color: "#60a5fa", fontSize: "10px" }}>
            Google Maps + Aerial View · ESRI Wayback Imagery
          </span>
        </div>
      </div>

      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {Object.entries(byStatus).map(([status, count]) => (
          <div key={status} style={{ ...CARD_STYLE, flex: 1, minWidth: 150 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
              {STATUS_ICON[status]}
              <span style={{ color: "#94a3b8", fontSize: "12px" }}>{status}</span>
            </div>
            <div style={{ color: "white", fontSize: 28, fontWeight: 700 }}>{count}</div>
            <div style={{ color: "#64748b", fontSize: "11px" }}>sites</div>
          </div>
        ))}
      </div>

      {/* Build velocity chart */}
      <VelocityChart sites={sites} colors={colors} />

      {/* Map card */}
      <div style={{ ...CARD_STYLE, padding: 0, overflow: "hidden" }}>
        {/* Map header */}
        <div style={{ padding: "14px 18px", borderBottom: "1px solid #334155", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: 0 }}>Datacenter Site Map</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "3px 0 0" }}>
              {viewMode === "aerial"
                ? "45° oblique aerial · use heading controls to rotate"
                : viewMode === "progress"
                  ? `Historical layer: ${waybackYear} imagery blended at ${Math.round(waybackOpacity * 100)}% opacity · click a site to view its timeline`
                  : "Click any marker to inspect · switch to Progress History to see construction changes over time"}
            </p>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* View mode toggle */}
            <div style={{ display: "flex", background: "#0f172a", border: "1px solid #334155", borderRadius: 7, padding: 3, gap: 3 }}>
              {([
                { mode: "satellite" as ViewMode, icon: <Layers size={12} />, label: "Satellite" },
                { mode: "aerial" as ViewMode, icon: <Eye size={12} />, label: "Aerial 45°" },
                { mode: "progress" as ViewMode, icon: <History size={12} />, label: "Progress History" },
              ]).map(({ mode, icon, label }) => (
                <button key={mode} onClick={() => setViewMode(mode)} style={{
                  display: "flex", alignItems: "center", gap: 5,
                  padding: "5px 12px", borderRadius: 5, border: "none", cursor: "pointer", fontSize: "11px", fontWeight: 600,
                  background: viewMode === mode ? (mode === "progress" ? "#1e293b" : "#1e293b") : "transparent",
                  color: viewMode === mode ? (mode === "progress" ? "#f59e0b" : "white") : "#64748b",
                  transition: "all 0.15s",
                }}>
                  {icon}{label}
                </button>
              ))}
            </div>

            {selectedSite && (
              <div style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6, padding: "6px 12px", fontSize: "12px", display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: "#64748b" }}>Viewing:</span>
                <span style={{ color: "white", fontWeight: 600 }}>{selectedSite.name}</span>
                <button onClick={() => setSelectedSite(null)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", padding: 0 }}>✕</button>
              </div>
            )}
          </div>
        </div>

        {/* Map */}
        <div style={{ height: 480, position: "relative" }}>
          <SatelliteMap
            sites={sites} colors={colors}
            selectedSite={selectedSite} onSelectSite={setSelectedSite}
            viewMode={viewMode}
            waybackReleaseId={waybackRelease.releaseId}
            waybackOpacity={waybackOpacity}
          />
        </div>

        {/* Legend */}
        <div style={{ padding: "10px 18px", borderTop: "1px solid #1e293b", display: "flex", gap: 20, flexWrap: "wrap" }}>
          {Object.entries(colors).map(([company, color]) => (
            <div key={company} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 10, height: 10, borderRadius: "50%", background: color as string }} />
              <span style={{ color: "#94a3b8", fontSize: "11px" }}>{company}</span>
            </div>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", gap: 16 }}>
            {Object.entries(STATUS_COLOR).map(([s, c]) => (
              <div key={s} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", border: `2px solid ${c}` }} />
                <span style={{ color: "#64748b", fontSize: "10px" }}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Progress History panel — shown in progress mode */}
      {viewMode === "progress" && (
        <ProgressPanel
          sites={sites} colors={colors}
          selectedSite={selectedSite} onSelectSite={setSelectedSite}
          waybackYear={waybackYear} onYearChange={setWaybackYear}
          waybackOpacity={waybackOpacity} onOpacityChange={setWaybackOpacity}
        />
      )}

      {/* Milestone legend */}
      {viewMode === "progress" && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", padding: "0 4px" }}>
          {Object.entries(MILESTONE_COLOR).map(([type, color]) => (
            <div key={type} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{ width: 10, height: 10, borderRadius: "50%", background: color, flexShrink: 0 }} />
              <span style={{ color: "#64748b", fontSize: "10px", textTransform: "capitalize" }}>{type}</span>
            </div>
          ))}
        </div>
      )}

      {/* Site cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 12 }}>
        {sites.map((site, i) => {
          const isSelected = selectedSite?.name === site.name;
          return (
            <div key={i} style={{
              ...CARD_STYLE,
              borderLeft: `3px solid ${colors[site.company] ?? "#666"}`,
              padding: "14px 16px",
              cursor: "pointer",
              outline: isSelected ? `2px solid ${colors[site.company] ?? "#3b82f6"}` : "none",
              outlineOffset: 2,
              transition: "outline 0.15s",
            }}>
              <div onClick={() => setSelectedSite(isSelected ? null : site)}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                  <div>
                    <div style={{ color: "white", fontWeight: 600, fontSize: 13 }}>{site.name}</div>
                    <div style={{ color: "#64748b", fontSize: "11px" }}>{site.company}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    {STATUS_ICON[site.status]}
                    <span style={{ color: STATUS_COLOR[site.status], fontSize: "11px" }}>{site.status}</span>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 16, marginBottom: 10 }}>
                  <div><div style={{ color: "#64748b", fontSize: "11px" }}>Size</div><div style={{ color: "#e2e8f0", fontSize: 13 }}>{site.size_acres} acres</div></div>
                  <div><div style={{ color: "#64748b", fontSize: "11px" }}>Completion</div><div style={{ color: "#e2e8f0", fontSize: 13 }}>{site.construction_pct}%</div></div>
                  {site.announced && <div><div style={{ color: "#64748b", fontSize: "11px" }}>Announced</div><div style={{ color: "#e2e8f0", fontSize: "11px" }}>{site.announced}</div></div>}
                </div>

                <div style={{ background: "#0f172a", borderRadius: 4, height: 4, marginBottom: 10 }}>
                  <div style={{ background: STATUS_COLOR[site.status], borderRadius: 4, height: 4, width: `${site.construction_pct}%` }} />
                </div>

                {/* Milestone count badge */}
                {site.milestones && site.milestones.length > 0 && (
                  <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 8 }}>
                    <GitBranch size={10} color="#475569" />
                    <span style={{ color: "#475569", fontSize: "10px" }}>
                      {site.milestones.filter(m => new Date(m.date) <= new Date()).length} of {site.milestones.length} milestones reached
                    </span>
                  </div>
                )}

                {site.source && (
                  <a href={site.source_url ?? "#"} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
                    style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 4, marginBottom: 8, background: "#0f1e38", border: "1px solid #1d4ed8", color: "#60a5fa", fontSize: "10px", textDecoration: "none" }}>
                    <ExternalLink size={9} />{site.source}
                  </a>
                )}
              </div>

              {/* Action buttons */}
              <div style={{ display: "flex", gap: 6, paddingTop: 8, borderTop: "1px solid #1e293b" }}>
                <button onClick={() => { setSelectedSite(site); setViewMode("satellite"); }}
                  style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4, padding: "5px 0", background: "#0f172a", border: "1px solid #334155", borderRadius: 6, color: "#94a3b8", cursor: "pointer", fontSize: "10px" }}>
                  <ZoomIn size={10} />Satellite
                </button>
                <button onClick={() => { setSelectedSite(site); setViewMode("aerial"); }}
                  style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4, padding: "5px 0", background: "#0f172a", border: "1px solid #334155", borderRadius: 6, color: "#94a3b8", cursor: "pointer", fontSize: "10px" }}>
                  <Eye size={10} />Aerial 45°
                </button>
                <button onClick={() => { setSelectedSite(site); setViewMode("progress"); }}
                  style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4, padding: "5px 0", background: "#1c1408", border: "1px solid #92400e", borderRadius: 6, color: "#f59e0b", cursor: "pointer", fontSize: "10px" }}>
                  <History size={10} />Progress
                </button>
                <button onClick={() => setAerialSite(site)}
                  style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4, padding: "5px 0", background: "#0f1e38", border: "1px solid #2563eb", borderRadius: 6, color: "#60a5fa", cursor: "pointer", fontSize: "10px" }}>
                  <Video size={10} />Video
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PageLoader() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 400, color: "#3b82f6" }}>
      Loading satellite data…
    </div>
  );
}
