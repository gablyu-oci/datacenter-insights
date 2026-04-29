import { useState } from "react";
import { useApi } from "../../hooks/useApi";
import { Building2, ChevronDown, ChevronUp, X, MapPin } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import ErrorPanel from "../shared/ErrorPanel";
import CitationFooter from "../shared/CitationFooter";
import SiteDetail from "../SiteDetail";

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

// ── Types ──────────────────────────────────────────────────────────────────

interface CompanySummary {
  id: number;
  canonical_name: string;
  short_name: string | null;
  ticker: string | null;
  public_private: string | null;
  site_count: number;
  mw_total: number;
}

interface CompaniesListResponse {
  data: CompanySummary[];
  total: number;
  page: number;
  page_size: number;
}

interface CompanyAliasEntry {
  source: string;
  raw_name: string;
  match_method: string | null;
  confidence: number | null;
}

interface CompanyDetail {
  id: number;
  canonical_name: string;
  short_name: string | null;
  ticker: string | null;
  public_private: string | null;
  alias_list: CompanyAliasEntry[];
}

interface RoleSummary {
  [role: string]: {
    site_count: number;
    mw_total: number;
  };
}

interface CompanySite {
  aterio_dc_uid: string;
  site_name: string | null;
  building_name: string | null;
  campus_name: string | null;
  city_name: string | null;
  state_code: string | null;
  power_capacity_mw: number | null;
}

interface CompanySitesResponse {
  data: CompanySite[];
  total: number;
  page: number;
  page_size: number;
}

// ── Company Detail Panel ──────────────────────────────────────────────────

function CompanyDetailPanel({ companyId, onClose, onOpenSite }: { companyId: number; onClose: () => void; onOpenSite: (uid: string) => void }) {
  const { data: detail, loading: detLoading, error: detError } = useApi<CompanyDetail>(`/api/companies/${companyId}`);
  const { data: roleData, loading: roleLoading } = useApi<RoleSummary>(`/api/companies/${companyId}/role-summary`);
  const { data: sitesData, loading: sitesLoading } = useApi<CompanySitesResponse>(`/api/companies/${companyId}/sites?page_size=20`);

  const loading = detLoading || roleLoading || sitesLoading;

  // Build pie/bar chart data from role summary
  const roleChartData = roleData
    ? Object.entries(roleData).map(([role, stats]) => ({
        role: role.replace(/_/g, " "),
        site_count: stats.site_count,
        mw_total: stats.mw_total,
      }))
    : [];
  const ROLE_COLOR_PALETTE = ["#3b82f6", "#22c55e", "#f59e0b", "#8b5cf6", "#06b6d4", "#ec4899", "#f97316", "#10b981", "#a855f7", "#14b8a6"];

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(0,0,0,0.75)",
        backdropFilter: "blur(3px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: "24px",
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "#0f172a",
          border: "1px solid #334155",
          borderTop: "3px solid #3b82f6",
          borderRadius: 14,
          width: "100%",
          maxWidth: 700,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "16px 20px",
          borderBottom: "1px solid #1e293b",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <div>
            <div style={{ color: "white", fontWeight: 700, fontSize: 18 }}>
              {loading ? "Loading..." : (detail?.canonical_name ?? "Company")}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 2 }}>
              {detail?.ticker && (
                <span style={{ color: "#64748b", fontSize: "12px" }}>Ticker: <span style={{ color: "#94a3b8" }}>{detail.ticker}</span></span>
              )}
              {detail?.public_private && (
                <span style={{
                  padding: "1px 7px", borderRadius: 4, fontSize: "10px", fontWeight: 600,
                  background: detail.public_private === "public" ? "#052e16" : "#1c1917",
                  border: `1px solid ${detail.public_private === "public" ? "#16a34a" : "#44403c"}`,
                  color: detail.public_private === "public" ? "#4ade80" : "#a8a29e",
                }}>
                  {detail.public_private.toUpperCase()}
                </span>
              )}
            </div>
            {detail?.alias_list && detail.alias_list.length > 0 && (
              <div style={{ color: "#475569", fontSize: "11px", marginTop: 4 }}>
                Also known as: {detail.alias_list.slice(0, 5).map(a => a.raw_name).join(", ")}
                {detail.alias_list.length > 5 && ` +${detail.alias_list.length - 5} more`}
              </div>
            )}
          </div>
          <button onClick={onClose} style={{
            background: "#1e293b", border: "1px solid #334155", borderRadius: 6,
            padding: "5px 7px", cursor: "pointer", color: "#94a3b8", display: "flex",
          }}>
            <X size={14} />
          </button>
        </div>

        {/* Content */}
        <div style={{ overflowY: "auto", padding: "16px 20px 20px" }}>
          {detError ? (
            <div style={{ color: "#ef4444", fontSize: 13, padding: "20px 0", textAlign: "center" }}>
              Failed to load company details.
            </div>
          ) : (
            <>
              {/* Role Summary */}
              {roleData && Object.keys(roleData).length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>
                    Role Distribution
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                    {Object.entries(roleData).map(([role, stats], i) => (
                      <div key={role} style={{
                        background: "#1e293b",
                        border: "1px solid #334155",
                        borderRadius: 8,
                        padding: "10px 14px",
                        minWidth: 120,
                        flex: 1,
                        borderLeft: `3px solid ${ROLE_COLOR_PALETTE[i % ROLE_COLOR_PALETTE.length]}`,
                      }}>
                        <div style={{ color: ROLE_COLOR_PALETTE[i % ROLE_COLOR_PALETTE.length], fontSize: "11px", fontWeight: 600, marginBottom: 4 }}>{role.replace(/_/g, " ")}</div>
                        <div style={{ color: "white", fontSize: 16, fontWeight: 700 }}>{stats.site_count} sites</div>
                        <div style={{ color: "#64748b", fontSize: "11px" }}>{stats.mw_total?.toFixed(0) ?? 0} MW total</div>
                      </div>
                    ))}
                  </div>

                  {roleChartData.length > 0 && (
                    <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8, padding: 12 }}>
                      <div style={{ color: "#94a3b8", fontSize: "10px", marginBottom: 6 }}>Sites by role</div>
                      <ResponsiveContainer width="100%" height={Math.max(120, roleChartData.length * 28)}>
                        <BarChart data={roleChartData} layout="vertical" margin={{ left: 4, right: 16, top: 4, bottom: 4 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" horizontal={false} />
                          <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} />
                          <YAxis type="category" dataKey="role" tick={{ fill: "#94a3b8", fontSize: 10 }} width={110} />
                          <Tooltip
                            contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                            formatter={(v) => [`${v} sites`, "Count"]}
                          />
                          <Bar dataKey="site_count" radius={[0, 4, 4, 0]}>
                            {roleChartData.map((_, i) => (
                              <Cell key={i} fill={ROLE_COLOR_PALETTE[i % ROLE_COLOR_PALETTE.length]} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              )}

              {/* Sites list */}
              <div>
                <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>
                  Sites ({sitesData?.total ?? 0} total)
                </div>
                {sitesLoading ? (
                  <div style={{ color: "#3b82f6", textAlign: "center", padding: "20px 0" }}>Loading sites...</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {(sitesData?.data ?? []).map((site, i) => {
                      const displayName = site.building_name || site.campus_name || site.site_name || site.aterio_dc_uid;
                      const location = [site.city_name, site.state_code].filter(Boolean).join(", ");
                      return (
                        <button
                          key={site.aterio_dc_uid ?? i}
                          onClick={() => onOpenSite(site.aterio_dc_uid)}
                          style={{
                            background: "#1e293b",
                            border: "1px solid #334155",
                            borderRadius: 8,
                            padding: "10px 14px",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            textAlign: "left",
                            cursor: "pointer",
                            color: "inherit",
                          }}
                          onMouseOver={e => (e.currentTarget.style.background = "#22304a")}
                          onMouseOut={e => (e.currentTarget.style.background = "#1e293b")}
                        >
                          <div>
                            <div style={{ color: "#e2e8f0", fontSize: "12px", fontWeight: 500 }}>
                              {displayName}
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
                              <MapPin size={10} color="#64748b" />
                              <span style={{ color: "#64748b", fontSize: "11px" }}>
                                {location || "Location not specified"}
                              </span>
                            </div>
                          </div>
                          {site.power_capacity_mw != null && (
                            <div style={{ color: "white", fontWeight: 700, fontSize: "13px" }}>
                              {site.power_capacity_mw.toFixed(0)} MW
                            </div>
                          )}
                        </button>
                      );
                    })}
                    {(sitesData?.total ?? 0) > 20 && (
                      <div style={{ color: "#64748b", fontSize: "11px", textAlign: "center", padding: "8px 0" }}>
                        Showing 20 of {sitesData?.total} sites
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function CompaniesTab() {
  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } = useApi<CompaniesListResponse>("/api/companies/?order_by=site_count&page_size=50");
  const [sortField, setSortField] = useState<"site_count" | "mw_total" | "canonical_name">("site_count");
  const [sortAsc, setSortAsc] = useState(false);
  const [selectedCompanyId, setSelectedCompanyId] = useState<number | null>(null);
  const [selectedSiteUid, setSelectedSiteUid] = useState<string | null>(null);

  if (loading) return <Loader />;

  if (error) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} lastAttempt={lastFetchedAt} />
      </div>
    );
  }

  const companies = data?.data ?? [];
  const total = data?.total ?? companies.length;

  if (companies.length === 0) {
    return (
      <div style={{ padding: "24px" }}>
        <div style={{ ...CARD_STYLE, textAlign: "center", padding: "60px 20px" }}>
          <div style={{ color: "#94a3b8", fontSize: "14px" }}>No company data available yet.</div>
        </div>
      </div>
    );
  }

  const sorted = [...companies].sort((a, b) => {
    if (sortField === "canonical_name") {
      return sortAsc
        ? a.canonical_name.localeCompare(b.canonical_name)
        : b.canonical_name.localeCompare(a.canonical_name);
    }
    const av = a[sortField] ?? 0;
    const bv = b[sortField] ?? 0;
    return sortAsc ? av - bv : bv - av;
  });

  const toggleSort = (field: typeof sortField) => {
    if (sortField === field) setSortAsc(v => !v);
    else { setSortField(field); setSortAsc(false); }
  };

  const totalSites = companies.reduce((s, c) => s + (c.site_count ?? 0), 0);
  const totalMW = companies.reduce((s, c) => s + (c.mw_total ?? 0), 0);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>

      {selectedCompanyId != null && (
        <CompanyDetailPanel
          companyId={selectedCompanyId}
          onClose={() => setSelectedCompanyId(null)}
          onOpenSite={(uid) => setSelectedSiteUid(uid)}
        />
      )}
      {selectedSiteUid && (
        <SiteDetail aterioDcUid={selectedSiteUid} onClose={() => setSelectedSiteUid(null)} />
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
          <Building2 size={16} color="#3b82f6" />
          <span style={{ color: "white", fontWeight: 600, fontSize: 14 }}>Company Directory</span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#0f172a", border: "1px solid #1d4ed8", color: "#60a5fa", fontSize: "10px", fontWeight: 600 }}>
            {total} companies tracked
          </span>
          <span style={{ padding: "2px 8px", borderRadius: 4, background: "#052e16", border: "1px solid #16a34a", color: "#4ade80", fontSize: "9px", fontWeight: 600 }}>
            LIVE
          </span>
        </div>
      </div>

      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Total Companies</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>{total}</div>
        </div>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Total Sites</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>{totalSites.toLocaleString()}</div>
        </div>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Total MW</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>{totalMW.toLocaleString()}<span style={{ color: "#64748b", fontSize: "13px", marginLeft: "3px" }}>MW</span></div>
        </div>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Showing</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>{companies.length}<span style={{ color: "#64748b", fontSize: "13px", marginLeft: "3px" }}>of {total}</span></div>
        </div>
      </div>

      {/* Top-5 by site count */}
      {companies.length > 0 && (
        <div style={CARD_STYLE}>
          <h3 style={{ color: "white", fontWeight: 600, fontSize: 14, margin: "0 0 4px" }}>Top 5 Companies by Site Count</h3>
          <p style={{ color: "#64748b", fontSize: "11px", margin: "0 0 14px" }}>Distinct sites associated across all roles</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={[...companies].sort((a, b) => (b.site_count ?? 0) - (a.site_count ?? 0)).slice(0, 5)}
              layout="vertical"
              margin={{ left: 4, right: 16, top: 4, bottom: 4 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" horizontal={false} />
              <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} />
              <YAxis type="category" dataKey="canonical_name" tick={{ fill: "#94a3b8", fontSize: 10 }} width={150} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                formatter={(v) => [`${v} sites`, "Sites"]}
              />
              <Bar dataKey="site_count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <CitationFooter
            sources={["Aterio Database"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={lineage?.source_url}
          />
        </div>
      )}

      {/* Companies table */}
      <div style={CARD_STYLE}>
        <h3 style={{ color: "white", fontWeight: 600, fontSize: 15, margin: "0 0 16px" }}>
          Company Directory -- Click row to view details
        </h3>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                {[
                  { label: "Company", field: "canonical_name" as const },
                  { label: "Ticker", field: null },
                  { label: "Type", field: null },
                  { label: "Sites", field: "site_count" as const },
                  { label: "Total MW", field: "mw_total" as const },
                ].map(({ label, field }) => (
                  <th
                    key={label}
                    onClick={field ? () => toggleSort(field) : undefined}
                    style={{
                      color: "#64748b", textAlign: "left", padding: "10px 14px",
                      fontWeight: 500, whiteSpace: "nowrap",
                      cursor: field ? "pointer" : "default",
                      userSelect: "none",
                    }}
                  >
                    {label}
                    {field && sortField === field && (
                      sortAsc
                        ? <ChevronUp size={10} style={{ display: "inline", marginLeft: 3 }} />
                        : <ChevronDown size={10} style={{ display: "inline", marginLeft: 3 }} />
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map(c => (
                <tr
                  key={c.id}
                  onClick={() => setSelectedCompanyId(c.id)}
                  style={{
                    borderBottom: "1px solid #1e293b",
                    cursor: "pointer",
                    transition: "background 0.1s",
                  }}
                  onMouseOver={e => (e.currentTarget.style.background = "#162032")}
                  onMouseOut={e => (e.currentTarget.style.background = "transparent")}
                >
                  <td style={{ padding: "10px 14px", color: "#e2e8f0", fontWeight: 500 }}>{c.canonical_name}</td>
                  <td style={{ padding: "10px 14px", color: "#64748b" }}>{c.ticker ?? "--"}</td>
                  <td style={{ padding: "10px 14px" }}>
                    {c.public_private ? (
                      <span style={{
                        padding: "1px 7px", borderRadius: 4, fontSize: "10px", fontWeight: 600,
                        background: c.public_private === "public" ? "#052e16" : "#1c1917",
                        border: `1px solid ${c.public_private === "public" ? "#16a34a" : "#44403c"}`,
                        color: c.public_private === "public" ? "#4ade80" : "#a8a29e",
                      }}>
                        {c.public_private.toUpperCase()}
                      </span>
                    ) : <span style={{ color: "#475569" }}>--</span>}
                  </td>
                  <td style={{ padding: "10px 14px", color: "white", fontWeight: 700 }}>{c.site_count}</td>
                  <td style={{ padding: "10px 14px", color: "white", fontWeight: 700 }}>{(c.mw_total ?? 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <CitationFooter
          sources={["Aterio Database"]}
          retrievedAt={lineage?.retrieved_at}
          confidence={lineage?.confidence}
          sourceUrl={lineage?.source_url}
        />
      </div>
    </div>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading companies...</div>;
}
