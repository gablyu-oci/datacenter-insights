import { useApi } from "../hooks/useApi";
import { X, MapPin, ExternalLink, Calendar, FileText, Zap, Server, Building2 } from "lucide-react";

// ── Types ───────────────────────────────────────────────────────────────────

interface SiteRecord {
  aterio_dc_uid: string;
  building_name: string | null;
  campus_name: string | null;
  site_name: string | null;
  full_address: string | null;
  city_name: string | null;
  state_code: string | null;
  county_name: string | null;
  provider_name: string | null;
  stage: string | null;
  power_capacity_mw: number | null;
  total_mw: number | null;
  site_acreage: number | null;
  pct_construction: number | null;
  announcement_date: string | null;
  activated_date: string | null;
  datasheet_url: string | null;
  permit_url: string | null;
  capex_url: string | null;
  latitude: number | null;
  longitude: number | null;
}

interface RoleCompany {
  company_id: number;
  canonical_name: string;
  short_name: string | null;
  ticker: string | null;
  confidence: number | null;
  source: string | null;
}

type RoleSummary = Record<string, RoleCompany[]>;

interface EventRow {
  id: number;
  aterio_dc_uid: string | null;
  event_type: string | null;
  event_date: string | null;
  description: string | null;
  source_url: string | null;
  source: string | null;
}

interface EventsResponse {
  data: EventRow[];
  total: number;
}

// ── Constants ───────────────────────────────────────────────────────────────

const ROLE_COLORS: Record<string, string> = {
  provider: "#3b82f6",
  end_user: "#22c55e",
  developer: "#f59e0b",
  operator: "#8b5cf6",
  owner: "#06b6d4",
  investor: "#ec4899",
  utility: "#f97316",
  customer: "#10b981",
  permittee_llc: "#a855f7",
  permit_parent: "#ef4444",
  financing: "#fbbf24",
  equipment: "#14b8a6",
  provider_backer: "#6366f1",
};

const EVENT_TYPE_COLORS: Record<string, string> = {
  announcement: "#3b82f6",
  permit_filed: "#f59e0b",
  construction_start: "#22c55e",
  activation: "#10b981",
  expansion: "#8b5cf6",
  cancellation: "#ef4444",
};

interface SiteDetailProps {
  aterioDcUid: string;
  onClose: () => void;
}

export default function SiteDetail({ aterioDcUid, onClose }: SiteDetailProps) {
  const { data: site, loading: siteLoading, error: siteError } = useApi<SiteRecord>(`/api/sites/${aterioDcUid}`);
  const { data: roleData, loading: roleLoading } = useApi<RoleSummary>(`/api/sites/${aterioDcUid}/role-summary`);
  const { data: eventsData, loading: eventsLoading } = useApi<EventsResponse>(`/api/events/?aterio_dc_uid=${encodeURIComponent(aterioDcUid)}`);

  const events = eventsData?.data ?? [];
  const sortedEvents = [...events].sort((a, b) => {
    const ad = a.event_date ?? "";
    const bd = b.event_date ?? "";
    return bd.localeCompare(ad);
  });

  const headerName = site?.building_name || site?.campus_name || site?.site_name || aterioDcUid;
  const mw = site?.power_capacity_mw ?? site?.total_mw ?? null;
  const address = site?.full_address || [site?.city_name, site?.state_code].filter(Boolean).join(", ");

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.55)",
          backdropFilter: "blur(2px)",
          zIndex: 200,
          animation: "fadeIn 0.15s ease-out",
        }}
      />

      {/* Slide-in panel */}
      <aside
        role="dialog"
        aria-label="Site detail"
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: "min(480px, 95vw)",
          background: "#0f172a",
          borderLeft: "1px solid #334155",
          boxShadow: "-12px 0 40px rgba(0,0,0,0.6)",
          zIndex: 201,
          display: "flex",
          flexDirection: "column",
          color: "#e2e8f0",
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
          animation: "slideIn 0.2s ease-out",
        }}
      >
        <style>{`
          @keyframes slideIn {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
          }
          @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
          }
        `}</style>

        {/* Header */}
        <div style={{
          padding: "16px 20px",
          borderBottom: "1px solid #1e293b",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 10,
          flexShrink: 0,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
              <Server size={13} color="#3b82f6" />
              <span style={{ color: "#64748b", fontSize: "10px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Site Detail
              </span>
            </div>
            <div style={{ color: "white", fontWeight: 700, fontSize: 16, marginBottom: 2, overflow: "hidden", textOverflow: "ellipsis" }}>
              {siteLoading ? "Loading..." : headerName}
            </div>
            {site?.provider_name && (
              <div style={{ color: "#94a3b8", fontSize: 12 }}>{site.provider_name}</div>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 6,
              padding: "5px 7px",
              cursor: "pointer",
              color: "#94a3b8",
              display: "flex",
              flexShrink: 0,
            }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Body (scrollable) */}
        <div style={{ overflowY: "auto", flex: 1, padding: "16px 20px 24px" }}>
          {siteError ? (
            <div style={{
              background: "#1e293b",
              border: "1px solid #ef4444",
              borderLeft: "3px solid #ef4444",
              borderRadius: 8,
              padding: "16px",
              color: "#f87171",
              fontSize: 13,
            }}>
              Failed to load site details.
            </div>
          ) : siteLoading ? (
            <div style={{ color: "#3b82f6", fontSize: 13, padding: "30px 0", textAlign: "center" }}>
              Loading site details...
            </div>
          ) : (
            <>
              {/* Address + Location */}
              {address && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 6, color: "#94a3b8", fontSize: 12 }}>
                    <MapPin size={12} color="#64748b" style={{ marginTop: 2, flexShrink: 0 }} />
                    <span>{address}</span>
                  </div>
                  {site?.county_name && (
                    <div style={{ color: "#64748b", fontSize: 11, marginTop: 4, marginLeft: 18 }}>
                      {site.county_name} County
                    </div>
                  )}
                  {(site?.latitude != null && site?.longitude != null) && (
                    <div style={{ color: "#475569", fontSize: 10, marginTop: 4, marginLeft: 18 }}>
                      {site.latitude.toFixed(4)}, {site.longitude.toFixed(4)}
                    </div>
                  )}
                </div>
              )}

              {/* KPI grid */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 8,
                marginBottom: 18,
              }}>
                <KPI label="Power" value={mw != null ? `${mw.toFixed(0)} MW` : "--"} icon={<Zap size={11} color="#f59e0b" />} />
                <KPI label="Stage" value={site?.stage ?? "--"} icon={<Building2 size={11} color="#3b82f6" />} />
                <KPI label="Acres" value={site?.site_acreage != null ? site.site_acreage.toFixed(0) : "--"} />
                <KPI label="Construction %" value={site?.pct_construction != null ? `${site.pct_construction}%` : "--"} />
                {site?.announcement_date && (
                  <KPI label="Announced" value={site.announcement_date.slice(0, 10)} />
                )}
                {site?.activated_date && (
                  <KPI label="Activated" value={site.activated_date.slice(0, 10)} />
                )}
              </div>

              {/* Source links */}
              {(site?.datasheet_url || site?.permit_url || site?.capex_url) && (
                <div style={{ marginBottom: 18 }}>
                  <SectionLabel>Source Documents</SectionLabel>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {site?.datasheet_url && <SourceBadge label="Datasheet" url={site.datasheet_url} />}
                    {site?.permit_url && <SourceBadge label="Permit" url={site.permit_url} />}
                    {site?.capex_url && <SourceBadge label="Capex" url={site.capex_url} />}
                  </div>
                </div>
              )}

              {/* Role breakdown */}
              <div style={{ marginBottom: 18 }}>
                <SectionLabel>Companies by Role</SectionLabel>
                {roleLoading ? (
                  <div style={{ color: "#475569", fontSize: 12 }}>Loading roles...</div>
                ) : roleData && Object.keys(roleData).length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {Object.entries(roleData).map(([role, companies]) => {
                      const roleColor = ROLE_COLORS[role.toLowerCase()] ?? "#64748b";
                      const list = Array.isArray(companies) ? companies : [];
                      return (
                        <div key={role}>
                          <div style={{
                            color: roleColor,
                            fontSize: 10,
                            fontWeight: 700,
                            textTransform: "uppercase",
                            letterSpacing: "0.04em",
                            marginBottom: 4,
                          }}>
                            {role.replace(/_/g, " ")}
                          </div>
                          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                            {list.length === 0 ? (
                              <span style={{ color: "#475569", fontSize: 11 }}>--</span>
                            ) : list.map((c) => (
                              <span
                                key={c.company_id}
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 4,
                                  padding: "3px 9px",
                                  borderRadius: 14,
                                  background: `${roleColor}18`,
                                  border: `1px solid ${roleColor}44`,
                                  color: roleColor,
                                  fontSize: 11,
                                  fontWeight: 500,
                                }}
                              >
                                {c.canonical_name || c.short_name || "Unknown"}
                                {c.ticker && (
                                  <span style={{ color: "#475569", fontSize: 9 }}>({c.ticker})</span>
                                )}
                              </span>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ color: "#475569", fontSize: 12 }}>No role data for this site.</div>
                )}
              </div>

              {/* Event timeline */}
              <div>
                <SectionLabel>
                  Event Timeline {events.length > 0 && <span style={{ color: "#475569" }}>({events.length})</span>}
                </SectionLabel>
                {eventsLoading ? (
                  <div style={{ color: "#475569", fontSize: 12 }}>Loading events...</div>
                ) : sortedEvents.length === 0 ? (
                  <div style={{ color: "#475569", fontSize: 12 }}>No events recorded for this site.</div>
                ) : (
                  <div style={{ position: "relative", paddingLeft: 4 }}>
                    {sortedEvents.map((ev, i) => {
                      const color = EVENT_TYPE_COLORS[ev.event_type ?? ""] ?? "#64748b";
                      return (
                        <div key={ev.id ?? i} style={{ display: "flex", gap: 10, marginBottom: 12, position: "relative" }}>
                          <div style={{ flexShrink: 0, paddingTop: 3 }}>
                            <div style={{
                              width: 10,
                              height: 10,
                              borderRadius: "50%",
                              background: color,
                              border: "2px solid #0f172a",
                              boxShadow: `0 0 0 1px ${color}`,
                            }} />
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 2 }}>
                              <span style={{ color, fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                                {(ev.event_type ?? "event").replace(/_/g, " ")}
                              </span>
                              {ev.event_date && (
                                <span style={{ color: "#64748b", fontSize: 10, display: "inline-flex", alignItems: "center", gap: 3 }}>
                                  <Calendar size={9} />
                                  {ev.event_date.slice(0, 10)}
                                </span>
                              )}
                            </div>
                            {ev.description && (
                              <div style={{ color: "#cbd5e1", fontSize: 12, lineHeight: 1.5 }}>
                                {ev.description}
                              </div>
                            )}
                            {ev.source_url && (
                              <a
                                href={ev.source_url}
                                target="_blank"
                                rel="noreferrer"
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 3,
                                  color: "#3b82f6",
                                  fontSize: 10,
                                  marginTop: 3,
                                  textDecoration: "none",
                                }}
                              >
                                <ExternalLink size={9} />
                                {ev.source ?? "Source"}
                              </a>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: "10px 20px",
          borderTop: "1px solid #1e293b",
          color: "#475569",
          fontSize: 10,
          flexShrink: 0,
        }}>
          UID: {aterioDcUid}
        </div>
      </aside>
    </>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      color: "#94a3b8",
      fontSize: 10,
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.06em",
      marginBottom: 8,
    }}>
      {children}
    </div>
  );
}

function KPI({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div style={{
      background: "#1e293b",
      border: "1px solid #334155",
      borderRadius: 8,
      padding: "8px 10px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#64748b", fontSize: 10, marginBottom: 2 }}>
        {icon}
        {label}
      </div>
      <div style={{ color: "white", fontSize: 14, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function SourceBadge({ label, url }: { label: string; url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "4px 10px",
        borderRadius: 6,
        background: "#0f1e38",
        border: "1px solid #2563eb",
        color: "#60a5fa",
        fontSize: 11,
        textDecoration: "none",
      }}
    >
      <FileText size={10} />
      {label}
      <ExternalLink size={9} />
    </a>
  );
}
