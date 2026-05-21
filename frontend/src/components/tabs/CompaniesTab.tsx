import type { ReactNode, CSSProperties } from "react";
import { useState, useEffect, useRef } from "react";
import { useApi } from "../../hooks/useApi";
import { Building2, ChevronDown, ChevronUp, X, MapPin, FileText, ExternalLink, Zap, Mic, Filter } from "lucide-react";
import { paginationWindow } from "./companies/paginationWindow";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import ErrorPanel from "../shared/ErrorPanel";
import CitationFooter from "../shared/CitationFooter";
import SiteDetail from "../SiteDetail";
import RoleDistribution from "./companies/RoleDistribution";
import SentimentBadge from "../earnings/SentimentBadge";
import EarningsDetailModal from "../earnings/EarningsDetailModal";

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

// ── Types ──────────────────────────────────────────────────────────────────

interface CompanyRoleEntry {
  role: string;
  site_count: number;
}

interface CompanySummary {
  id: number;
  canonical_name: string;
  short_name: string | null;
  ticker: string | null;
  public_private: string | null;
  site_count: number;
  mw_total: number;
  roles?: CompanyRoleEntry[];
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

interface FilingRow {
  id: number;
  filing_date: string | null;
  form_type: string;
  buyer_raw: string | null;
  seller_raw: string | null;
  capacity_mw: number | null;
  energy_source: string | null;
  excerpt: string | null;
  edgar_url: string | null;
}
interface FilingsResponse {
  data: FilingRow[];
  total: number;
}

// Earnings calls — list endpoint /api/companies/{id}/earnings.
// Shape mirrors backend/routers/earnings.py:_serialize_transcript_summary.
interface CompanyEarningsItem {
  id: number;
  ticker: string | null;
  quarter: string | null;
  call_date: string | null;
  sentiment: {
    ai_demand: string | null;
    power_constraints: string | null;
    datacenter_capex: string | null;
    overall: string | null;
  };
  has_guidance: boolean;
  capex_mention_count: number;
  ai_power_mention_count: number;
  transcript_url: string | null;
  guidance_quote?: string | null;
}

interface CompanyEarningsPayload {
  company_id: number;
  canonical_name: string;
  ticker: string | null;
  cik: string | null;
  items: CompanyEarningsItem[];
  total: number;
  limit: number;
  offset: number;
}

function formatQuarterShort(q: string | null): string {
  if (!q) return "";
  const m = q.match(/^(\d{4})Q(\d)$/);
  if (m) return `Q${m[2]} FY${m[1].slice(2)}`;
  return q;
}

function CompanyDetailPanel({ companyId, onClose, onOpenSite }: { companyId: number; onClose: () => void; onOpenSite: (uid: string) => void }) {
  const { data: detail, loading: detLoading, error: detError } = useApi<CompanyDetail>(`/api/companies/${companyId}`);
  const { data: roleData, loading: roleLoading } = useApi<RoleSummary>(`/api/companies/${companyId}/role-summary`);
  // Pull all sites (cap 1000) so we can do client-side aggregations like
  // sites-by-state and total-MW.
  const { data: sitesData, loading: sitesLoading } = useApi<CompanySitesResponse>(`/api/companies/${companyId}/sites?page_size=1000`);
  const { data: filingsData, loading: filingsLoading } = useApi<FilingsResponse>(`/api/companies/${companyId}/filings?limit=20`);
  // Earnings calls timeline (most recent 8). Empty list is a valid state.
  const { data: earningsData, loading: earningsLoading, error: earningsError } =
    useApi<CompanyEarningsPayload>(`/api/companies/${companyId}/earnings?limit=8`);
  const [selectedEarningsId, setSelectedEarningsId] = useState<number | null>(null);

  const loading = detLoading || roleLoading || sitesLoading;
  const ROLE_COLOR_PALETTE = ["#3b82f6", "#22c55e", "#f59e0b", "#8b5cf6", "#06b6d4", "#ec4899", "#f97316", "#10b981", "#a855f7", "#14b8a6"];

  // ── Aggregations driven by sitesData ─────────────────────────────────────
  type SiteRow = { state_code?: string | null; power_capacity_mw?: number | null };
  const sitesAll: SiteRow[] = (sitesData?.data ?? []) as SiteRow[];
  const totalMW = sitesAll.reduce((s, r) => s + (r.power_capacity_mw ?? 0), 0);
  const siteCount = sitesAll.length;
  const sitesWithMW = sitesAll.filter(r => (r.power_capacity_mw ?? 0) > 0).length;
  const avgMW = sitesWithMW > 0 ? totalMW / sitesWithMW : 0;
  const maxMW = sitesAll.reduce((m, r) => Math.max(m, r.power_capacity_mw ?? 0), 0);

  // Sites by state — top 10 states by site count, with MW total per state.
  const sitesByState = (() => {
    const m: Record<string, { sites: number; mw: number }> = {};
    for (const s of sitesAll) {
      const k = s.state_code ?? "?";
      m[k] ??= { sites: 0, mw: 0 };
      m[k].sites += 1;
      m[k].mw += s.power_capacity_mw ?? 0;
    }
    return Object.entries(m)
      .map(([state, v]) => ({ state, sites: v.sites, mw: Math.round(v.mw) }))
      .sort((a, b) => b.sites - a.sites)
      .slice(0, 10);
  })();

  return (
    <>
    {selectedEarningsId != null && (
      <EarningsDetailModal
        transcriptId={selectedEarningsId}
        onClose={() => setSelectedEarningsId(null)}
      />
    )}
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
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div style={{ color: "white", fontWeight: 700, fontSize: 18 }}>
                {loading ? "Loading..." : (detail?.canonical_name ?? "Company")}
              </div>
              {/* Role badges — derived from /role-summary roles map */}
              {roleData?.data && Object.keys(roleData.data).length > 0 && (
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {Object.entries(roleData.data)
                    .sort(([, a], [, b]) => (b as any).site_count - (a as any).site_count)
                    .map(([role, agg]) => (
                      <span key={role} style={{
                        padding: "1px 7px",
                        borderRadius: 4,
                        fontSize: "10px",
                        fontWeight: 600,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        background: "#0f172a",
                        border: "1px solid #334155",
                        color: "#94a3b8",
                      }} title={`${(agg as any).site_count} sites`}>
                        {role.replace(/_/g, " ")} · {(agg as any).site_count}
                      </span>
                    ))}
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
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
              {/* MW Summary */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>
                  Capacity Summary
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {[
                    { label: "Total MW", value: totalMW.toLocaleString(undefined, { maximumFractionDigits: 0 }), accent: "#f59e0b", icon: Zap },
                    { label: "Sites", value: siteCount.toLocaleString(), accent: "#3b82f6", icon: Building2 },
                    { label: "Avg MW / site", value: avgMW > 0 ? avgMW.toFixed(0) : "--", accent: "#22c55e", icon: Zap },
                    { label: "Largest", value: maxMW > 0 ? maxMW.toFixed(0) + " MW" : "--", accent: "#a855f7", icon: Zap },
                  ].map(({ label, value, accent, icon: Icon }) => (
                    <div key={label} style={{
                      background: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: 8,
                      padding: "10px 14px",
                      minWidth: 130,
                      flex: 1,
                      borderLeft: `3px solid ${accent}`,
                    }}>
                      <div style={{ color: accent, fontSize: "10px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", display: "flex", alignItems: "center", gap: 4 }}>
                        <Icon size={11} /> {label}
                      </div>
                      <div style={{ color: "white", fontSize: 18, fontWeight: 700, marginTop: 2 }}>{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Role Distribution — per-role tiles + nested counterparty donut grid */}
              {roleData && Object.keys(roleData).length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>
                    Role Distribution
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
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
                  {/* Counterparty donut grid — same section, more granular */}
                  <RoleDistribution companyId={companyId} companyName={detail?.canonical_name ?? ""} />
                </div>
              )}

              {/* Recent filings — EDGAR 8-K / 10-K extractions naming this company */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
                  <FileText size={11} /> Recent Filings ({filingsData?.total ?? 0})
                </div>
                {filingsLoading ? (
                  <div style={{ color: "#3b82f6", textAlign: "center", padding: "20px 0", fontSize: 12 }}>Loading filings...</div>
                ) : (filingsData?.data ?? []).length === 0 ? (
                  <div style={{ color: "#64748b", fontSize: 12, padding: "12px 14px", background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}>
                    No EDGAR filings extracted for this company yet. The cron-fed extractor adds new disclosures daily.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {(filingsData?.data ?? []).map(f => (
                      <a
                        key={f.id}
                        href={f.edgar_url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          background: "#1e293b",
                          border: "1px solid #334155",
                          borderRadius: 8,
                          padding: "10px 14px",
                          color: "inherit",
                          textDecoration: "none",
                          display: "flex",
                          gap: 12,
                          alignItems: "flex-start",
                        }}
                        onMouseOver={e => (e.currentTarget.style.background = "#22304a")}
                        onMouseOut={e => (e.currentTarget.style.background = "#1e293b")}
                      >
                        <div style={{ flexShrink: 0, fontSize: 11, color: "#94a3b8", minWidth: 84 }}>
                          <div style={{ color: "#cbd5e1", fontWeight: 600 }}>{f.filing_date ?? "?"}</div>
                          <div style={{ color: "#64748b", fontSize: 10, marginTop: 1 }}>{f.form_type}</div>
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
                            {f.buyer_raw && <span style={{ color: "#60a5fa", fontSize: 11, fontWeight: 600 }}>buyer: {f.buyer_raw}</span>}
                            {f.seller_raw && <span style={{ color: "#fbbf24", fontSize: 11, fontWeight: 600 }}>seller: {f.seller_raw}</span>}
                            {f.capacity_mw != null && <span style={{ color: "#22c55e", fontSize: 11, fontWeight: 600 }}>{f.capacity_mw.toFixed(0)} MW</span>}
                            {f.energy_source && <span style={{ color: "#a78bfa", fontSize: 10, padding: "1px 6px", background: "#0f172a", borderRadius: 4 }}>{f.energy_source}</span>}
                          </div>
                          <div style={{ color: "#94a3b8", fontSize: 11, lineHeight: 1.4, overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                            {f.excerpt || "(no extracted excerpt — open the filing to read)"}
                          </div>
                        </div>
                        <ExternalLink size={11} color="#64748b" style={{ flexShrink: 0, marginTop: 2 }} />
                      </a>
                    ))}
                  </div>
                )}
              </div>

              {/* Earnings calls timeline */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
                  <Mic size={11} /> Earnings Calls ({earningsData?.total ?? 0})
                </div>
                {earningsLoading ? (
                  <div style={{ color: "#3b82f6", textAlign: "center", padding: "20px 0", fontSize: 12 }}>Loading earnings calls...</div>
                ) : earningsError ? (
                  <ErrorPanel
                    title="Could not load earnings"
                    message="The earnings transcripts endpoint returned an error. Try again in a moment."
                    variant="inline"
                  />
                ) : (earningsData?.items ?? []).length === 0 ? (
                  <div style={{ color: "#64748b", fontSize: 12, padding: "12px 14px", background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}>
                    No earnings transcripts ingested for this company yet. The Alpha Vantage adapter refreshes daily off the earnings calendar.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {(earningsData?.items ?? []).map((e) => {
                      const headline = e.guidance_quote
                        ?? (e.has_guidance ? "Guidance disclosed" : null)
                        ?? (e.ai_power_mention_count + e.capex_mention_count > 0
                              ? `${e.capex_mention_count} capex \u00b7 ${e.ai_power_mention_count} AI/power mentions`
                              : "(no extracted highlights yet)");
                      return (
                        <button
                          key={e.id}
                          type="button"
                          onClick={() => setSelectedEarningsId(e.id)}
                          aria-haspopup="dialog"
                          style={{
                            background: "#1e293b",
                            border: "1px solid #334155",
                            borderRadius: 8,
                            padding: "10px 14px",
                            color: "inherit",
                            textAlign: "left",
                            display: "flex",
                            gap: 12,
                            alignItems: "center",
                            cursor: "pointer",
                          }}
                          onMouseOver={ev => (ev.currentTarget.style.background = "#22304a")}
                          onMouseOut={ev => (ev.currentTarget.style.background = "#1e293b")}
                        >
                          <div style={{ flexShrink: 0, minWidth: 84 }}>
                            <div style={{ color: "#cbd5e1", fontWeight: 600, fontSize: 11 }}>
                              {e.call_date ?? "?"}
                            </div>
                            <div style={{ color: "#64748b", fontSize: 10, marginTop: 1 }}>
                              Earnings call
                            </div>
                          </div>
                          <span style={{
                            padding: "1px 7px",
                            borderRadius: 4,
                            fontSize: "10px",
                            fontWeight: 600,
                            background: "#0f172a",
                            border: "1px solid #334155",
                            color: "#94a3b8",
                            flexShrink: 0,
                          }}>
                            {formatQuarterShort(e.quarter)}
                          </span>
                          <div style={{ flexShrink: 0 }}>
                            <SentimentBadge axis="overall" value={e.sentiment.overall} size="sm" />
                          </div>
                          <div style={{
                            flex: 1,
                            minWidth: 0,
                            color: "#94a3b8",
                            fontSize: 11,
                            lineHeight: 1.4,
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}>
                            {headline}
                          </div>
                        </button>
                      );
                    })}
                    {(earningsData?.total ?? 0) > 8 && (
                      <div style={{ color: "#64748b", fontSize: 11, textAlign: "center", padding: "8px 0" }}>
                        Showing 8 of {earningsData?.total} calls
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Sites by state */}
              {sitesByState.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ color: "#94a3b8", fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>
                    Sites by State (top 10)
                  </div>
                  <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8, padding: 12 }}>
                    <ResponsiveContainer width="100%" height={Math.max(140, sitesByState.length * 28)}>
                      <BarChart data={sitesByState} layout="vertical" margin={{ left: 4, right: 50, top: 4, bottom: 4 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" horizontal={false} />
                        <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10 }} />
                        <YAxis type="category" dataKey="state" tick={{ fill: "#94a3b8", fontSize: 11 }} width={36} />
                        <Tooltip
                          contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 12 }}
                          itemStyle={{ color: "#e2e8f0" }}
                          labelStyle={{ color: "white" }}
                          formatter={(v, _n, props) => [
                            `${v} sites · ${(props as { payload?: { mw?: number } })?.payload?.mw?.toLocaleString() ?? 0} MW`,
                            "By state",
                          ]}
                        />
                        <Bar dataKey="sites" radius={[0, 4, 4, 0]}>
                          {sitesByState.map((_, i) => (
                            <Cell key={i} fill={`hsl(${210 + i * 14}, 70%, ${60 - i * 2}%)`} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
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
    </>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

interface CompaniesAggregate {
  total_companies: number;
  total_sites: number;
  total_mw: number;
  stages_included: string[];
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const PAGE_SIZE = 50;

type SortField = "canonical_name" | "ticker" | "site_count" | "mw_total";
type SortDir = "asc" | "desc";
type PopoverKey = "canonical_name" | "ticker" | "public_private" | "role";

interface ColumnFiltersState {
  names: string[];
  tickers: string[];
  publicPrivates: string[];
  roles: string[];
}

const EMPTY_FILTERS: ColumnFiltersState = { names: [], tickers: [], publicPrivates: [], roles: [] };

// Initial direction for each column when it is clicked for the first time.
// Text columns sort A->Z (asc); numeric columns sort largest-first (desc).
function defaultDirFor(field: SortField): SortDir {
  return field === "canonical_name" || field === "ticker" ? "asc" : "desc";
}

function buildDirectoryUrl(params: {
  columnFilters: ColumnFiltersState;
  sortField: SortField;
  sortDir: SortDir;
  page: number;
  pageSize: number;
}): string {
  const sp = new URLSearchParams();
  sp.set("order_by", params.sortField);
  sp.set("direction", params.sortDir);
  sp.set("page", String(params.page));
  sp.set("page_size", String(params.pageSize));
  const f = params.columnFilters;
  if (f.names.length) sp.set("names", f.names.join(","));
  if (f.tickers.length) sp.set("tickers", f.tickers.join(","));
  if (f.publicPrivates.length) sp.set("public_privates", f.publicPrivates.join(","));
  if (f.roles.length) sp.set("roles_in", f.roles.join(","));
  return `/api/companies/?${sp.toString()}`;
}

export default function CompaniesTab() {
  // KPI row queries operational and under-construction separately so each
  // headline number is unambiguous about what stage it covers.
  const { data: activeAgg } = useApi<CompaniesAggregate>(
    `/api/companies/aggregate?stages=Active`,
  );
  const { data: constructionAgg } = useApi<CompaniesAggregate>(
    `/api/companies/aggregate?stages=Construction`,
  );

  // Column-header filter / sort / pagination state.
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(EMPTY_FILTERS);
  const [openPopover, setOpenPopover] = useState<PopoverKey | null>(null);
  const [sortField, setSortField] = useState<SortField>("site_count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(1);

  // One-shot fetch of all companies (up to 500) to populate the column-filter
  // popover option lists with the full universe of names / tickers / roles —
  // not just the current visible page.
  const [allOptions, setAllOptions] = useState<{
    names: string[];
    tickers: string[];
    roles: string[];
  }>({ names: [], tickers: [], roles: [] });
  useEffect(() => {
    fetch(`${API_BASE}/api/companies/?page_size=500&order_by=canonical_name&direction=asc`)
      .then((r) => r.json())
      .then((d) => {
        const payload: CompanyRow[] =
          (d?.data?.data as CompanyRow[]) ?? (d?.data as CompanyRow[]) ?? [];
        const names = new Set<string>();
        const tickers = new Set<string>();
        const roles = new Set<string>();
        for (const c of payload) {
          if (c.canonical_name) names.add(c.canonical_name);
          if (c.ticker) tickers.add(c.ticker);
          for (const r of c.roles ?? []) if (r.role) roles.add(r.role);
        }
        setAllOptions({
          names: [...names].sort((a, b) => a.localeCompare(b)),
          tickers: [...tickers].sort((a, b) => a.localeCompare(b)),
          roles: [...roles].sort((a, b) => a.localeCompare(b)),
        });
      })
      .catch(() => {/* silent — popovers will just show empty option lists */});
  }, []);

  // Server-data state — kept as "last good" so the table doesn't blank
  // during refetches. `fetching` drives the dim overlay.
  const [data, setData] = useState<CompaniesListResponse | null>(null);
  const [lineage, setLineage] = useState<{ source_url?: string; retrieved_at?: string; confidence?: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorInfo, setErrorInfo] = useState<{ title: string; message: string } | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);
  const reqIdRef = useRef(0);
  const [retryNonce, setRetryNonce] = useState(0);

  const [selectedCompanyId, setSelectedCompanyId] = useState<number | null>(null);
  const [selectedSiteUid, setSelectedSiteUid] = useState<string | null>(null);

  // Reset page when any non-page filter changes.
  useEffect(() => {
    setPage(1);
  }, [columnFilters, sortField, sortDir]);

  // Directory fetch. Uses a request-id ref so stale responses (e.g. from
  // rapid filter toggles) are dropped instead of clobbering newer data.
  useEffect(() => {
    const url = buildDirectoryUrl({
      columnFilters,
      sortField,
      sortDir,
      page,
      pageSize: PAGE_SIZE,
    });
    const myReq = ++reqIdRef.current;
    setFetching(true);
    setError(null);
    setErrorInfo(null);
    fetch(`${API_BASE}${url}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        if (myReq !== reqIdRef.current) return; // stale, drop
        let payload: CompaniesListResponse;
        if (d && typeof d === "object" && "data" in d && "lineage" in d) {
          setLineage(d.lineage ?? null);
          payload = d.data as CompaniesListResponse;
        } else {
          setLineage(null);
          payload = d as CompaniesListResponse;
        }
        setData(payload);
        setLastFetchedAt(new Date());
      })
      .catch((e) => {
        if (myReq !== reqIdRef.current) return;
        const msg = (e && (e.message || String(e))) || "Request failed";
        setError(msg);
        const isNetwork = /Failed to fetch|NetworkError/i.test(msg);
        setErrorInfo({
          title: isNetwork ? "Network error" : "Something went wrong",
          message: isNetwork
            ? "Could not reach the server. Check your connection."
            : msg,
        });
      })
      .finally(() => {
        if (myReq !== reqIdRef.current) return;
        setLoading(false);
        setFetching(false);
      });
  }, [columnFilters, sortField, sortDir, page, retryNonce]);

  const retry = () => setRetryNonce((n) => n + 1);

  const companies = data?.data ?? [];
  const total = data?.total ?? 0;

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir(defaultDirFor(field));
    }
  };

  // Aggregates by stage. Both come from the dedicated endpoint that does
  // COUNT(DISTINCT sites.id) + SUM(power_capacity_mw) — avoids the per-role
  // double-counting the per-company reduce produces.
  const activeBuildings = activeAgg?.total_sites ?? 0;
  const activeMW = activeAgg?.total_mw ?? 0;
  const constructionMW = constructionAgg?.total_mw ?? 0;
  const totalCompanies = activeAgg?.total_companies ?? total;
  const fmtPower = (mw: number) =>
    mw >= 1000 ? `${(mw / 1000).toFixed(1)}` : `${Math.round(mw).toLocaleString()}`;
  const fmtUnit = (mw: number) => (mw >= 1000 ? "GW" : "MW");

  if (loading && !data) return <Loader />;

  if (error && !data) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel title={errorInfo?.title} message={errorInfo?.message} onRetry={retry} lastAttempt={lastFetchedAt} />
      </div>
    );
  }

  // Column definition: each header is either a popover trigger (filter +
  // optionally sort) or a sort-only header (Sites / Total MW). The popover's
  // option list is sourced from `allOptions` (one-shot fetch on mount).
  interface ColumnDef {
    label: string;
    popover: PopoverKey | null;       // null = no popover; click toggles sort
    sortField: SortField | null;      // server-side sort key for this column
    filterValues: string[];           // current selection (for the dot indicator)
    options: string[];                // option list shown inside the popover
    onFilterChange: (next: string[]) => void;
  }
  const COLS: ColumnDef[] = [
    {
      label: "Company",
      popover: "canonical_name",
      sortField: "canonical_name",
      filterValues: columnFilters.names,
      options: allOptions.names,
      onFilterChange: (next) => setColumnFilters((f) => ({ ...f, names: next })),
    },
    {
      label: "Ticker",
      popover: "ticker",
      sortField: "ticker",
      filterValues: columnFilters.tickers,
      options: allOptions.tickers,
      onFilterChange: (next) => setColumnFilters((f) => ({ ...f, tickers: next })),
    },
    {
      label: "Type",
      popover: "public_private",
      sortField: null,
      filterValues: columnFilters.publicPrivates,
      options: ["public", "private", "null"],
      onFilterChange: (next) => setColumnFilters((f) => ({ ...f, publicPrivates: next })),
    },
    {
      label: "Roles",
      popover: "role",
      sortField: null,
      filterValues: columnFilters.roles,
      options: allOptions.roles,
      onFilterChange: (next) => setColumnFilters((f) => ({ ...f, roles: next })),
    },
    {
      label: "Sites",
      popover: null,
      sortField: "site_count",
      filterValues: [],
      options: [],
      onFilterChange: () => {},
    },
    {
      label: "Total MW",
      popover: null,
      sortField: "mw_total",
      filterValues: [],
      options: [],
      onFilterChange: () => {},
    },
  ];

  const pageTokens = paginationWindow(page, totalPages, 7);

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
        </div>
      </div>

      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Total Companies</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>{totalCompanies.toLocaleString()}</div>
        </div>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Total Active Buildings</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>{activeBuildings.toLocaleString()}</div>
        </div>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Total Active {fmtUnit(activeMW)}</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>
            {fmtPower(activeMW)}
            <span style={{ color: "#64748b", fontSize: "13px", marginLeft: "3px" }}>{fmtUnit(activeMW)}</span>
          </div>
        </div>
        <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>Total Under Construction {fmtUnit(constructionMW)}</div>
          <div style={{ color: "white", fontSize: "28px", fontWeight: 700 }}>
            {fmtPower(constructionMW)}
            <span style={{ color: "#64748b", fontSize: "13px", marginLeft: "3px" }}>{fmtUnit(constructionMW)}</span>
          </div>
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

        {fetching && companies.length === 0 ? (
          <Loader />
        ) : total === 0 ? (
          <div style={{ padding: "48px 20px", textAlign: "center" }}>
            <div style={{ color: "#94a3b8", fontSize: 13 }}>No companies match these filters.</div>
            <div style={{ color: "#64748b", fontSize: 11, marginTop: 6 }}>
              Open a column header to clear or adjust its filter.
            </div>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <div
              style={{
                opacity: fetching ? 0.6 : 1,
                pointerEvents: fetching ? "none" : "auto",
                transition: "opacity 0.2s linear",
              }}
              aria-busy={fetching}
            >
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #334155" }}>
                    {COLS.map((col) => {
                      const isActiveSort =
                        col.sortField !== null && sortField === col.sortField;
                      const ariaSort: "ascending" | "descending" | "none" =
                        isActiveSort
                          ? sortDir === "asc"
                            ? "ascending"
                            : "descending"
                          : "none";
                      const hasFilter = col.filterValues.length > 0;
                      const isPopoverOpen =
                        col.popover !== null && openPopover === col.popover;

                      const handleClick = () => {
                        if (col.popover) {
                          setOpenPopover((cur) =>
                            cur === col.popover ? null : col.popover,
                          );
                        } else if (col.sortField) {
                          toggleSort(col.sortField);
                        }
                      };

                      return (
                        <th
                          key={col.label}
                          onClick={handleClick}
                          aria-sort={col.sortField ? ariaSort : undefined}
                          aria-haspopup={col.popover ? "listbox" : undefined}
                          aria-expanded={col.popover ? isPopoverOpen : undefined}
                          style={{
                            color: hasFilter || isActiveSort ? "#60a5fa" : "#64748b",
                            textAlign: "left",
                            padding: "10px 14px",
                            fontWeight: 500,
                            whiteSpace: "nowrap",
                            cursor: col.popover || col.sortField ? "pointer" : "default",
                            userSelect: "none",
                            position: "relative",
                          }}
                        >
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                            {col.label}
                            {col.popover && (
                              <Filter
                                size={10}
                                style={{
                                  opacity: hasFilter ? 1 : 0.5,
                                  color: hasFilter ? "#3b82f6" : undefined,
                                }}
                              />
                            )}
                            {isActiveSort && (
                              sortDir === "asc"
                                ? <ChevronUp size={10} />
                                : <ChevronDown size={10} />
                            )}
                          </span>
                          {col.popover && isPopoverOpen && (
                            <ColumnFilterPopover
                              options={col.options}
                              selected={col.filterValues}
                              onChange={col.onFilterChange}
                              onClose={() => setOpenPopover(null)}
                              showSort={col.sortField !== null}
                              sortField={sortField}
                              sortDir={sortDir}
                              colSortField={col.sortField}
                              onSort={(dir) => {
                                if (!col.sortField) return;
                                setSortField(col.sortField);
                                setSortDir(dir);
                              }}
                            />
                          )}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {companies.map(c => (
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
                      <td style={{ padding: "10px 14px" }}>
                        <div style={{ display: "flex", gap: 3, flexWrap: "wrap", maxWidth: 220 }}>
                          {(c.roles ?? []).slice(0, 4).map(r => (
                            <span key={r.role} style={{
                              padding: "1px 6px",
                              borderRadius: 4,
                              fontSize: "9px",
                              fontWeight: 600,
                              letterSpacing: "0.03em",
                              background: "#0f172a",
                              border: "1px solid #334155",
                              color: "#94a3b8",
                              whiteSpace: "nowrap",
                            }} title={`${r.site_count} sites`}>
                              {r.role.replace(/_/g, " ")}
                            </span>
                          ))}
                          {(c.roles?.length ?? 0) > 4 && (
                            <span style={{ color: "#475569", fontSize: 9 }}>
                              +{(c.roles?.length ?? 0) - 4}
                            </span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: "10px 14px", color: "white", fontWeight: 700 }}>{c.site_count}</td>
                      <td style={{ padding: "10px 14px", color: "white", fontWeight: 700 }}>{(c.mw_total ?? 0).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Pagination bar */}
        {total > 0 && (
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
              rowGap: 8,
              marginTop: 16,
              borderTop: "1px solid #1e293b",
              paddingTop: 12,
            }}
          >
            <div aria-live="polite" style={{ color: "#94a3b8", fontSize: 12 }}>
              Showing {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <PageTile
                disabled={page === 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                ariaLabel="Previous page"
              >
                ‹
              </PageTile>
              {pageTokens.map((token, idx) => {
                if (token === "ellipsis") {
                  return (
                    <span
                      key={`ell-${idx}`}
                      aria-hidden="true"
                      tabIndex={-1}
                      style={{
                        width: 28,
                        height: 28,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#94a3b8",
                        fontSize: 12,
                        cursor: "default",
                      }}
                    >
                      …
                    </span>
                  );
                }
                const isActive = token === page;
                return (
                  <PageTile
                    key={token}
                    active={isActive}
                    ariaLabel={`Go to page ${token}`}
                    ariaCurrent={isActive ? "page" : undefined}
                    onClick={() => setPage(token)}
                  >
                    {token}
                  </PageTile>
                );
              })}
              <PageTile
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                ariaLabel="Next page"
              >
                ›
              </PageTile>
            </div>
          </div>
        )}

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

function PageTile({
  children,
  onClick,
  active = false,
  disabled = false,
  ariaLabel,
  ariaCurrent,
}: {
  children: ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
  ariaLabel?: string;
  ariaCurrent?: "page";
}) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-current={ariaCurrent}
      style={{
        width: 28,
        height: 28,
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 600,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        border: `1px solid ${active ? "#3b82f6" : "#334155"}`,
        background: active ? "#3b82f6" : "#1e293b",
        color: active ? "#ffffff" : "#94a3b8",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        padding: 0,
      }}
      onMouseOver={(e) => {
        if (!active && !disabled) e.currentTarget.style.background = "#22304a";
      }}
      onMouseOut={(e) => {
        if (!active && !disabled) e.currentTarget.style.background = "#1e293b";
      }}
    >
      {children}
    </button>
  );
}

function Loader() {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px", color: "#3b82f6" }}>Loading companies...</div>;
}

// Inline popover anchored to its parent `<th>` (which is position: relative).
// Renders sort buttons (when the column is sortable), a search input that
// client-side filters the option list, and a multi-select checkbox list.
// Each tick fires onChange synchronously so the parent re-issues the fetch.
function ColumnFilterPopover({
  options,
  selected,
  onChange,
  onClose,
  showSort,
  sortField,
  sortDir,
  colSortField,
  onSort,
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  onClose: () => void;
  showSort: boolean;
  sortField: SortField;
  sortDir: SortDir;
  colSortField: SortField | null;
  onSort: (dir: SortDir) => void;
}) {
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const q = search.trim().toLowerCase();
  const filtered = q === ""
    ? options
    : options.filter((o) => o.toLowerCase().includes(q));
  const isOn = (v: string) => selected.includes(v);
  const toggle = (v: string) => {
    onChange(isOn(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  };

  return (
    <div
      ref={ref}
      role="dialog"
      onClick={(e) => e.stopPropagation()}
      style={{
        position: "absolute",
        top: "calc(100% + 4px)",
        left: 0,
        minWidth: 240,
        maxWidth: 300,
        background: "#0f172a",
        border: "1px solid #334155",
        borderRadius: 8,
        boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
        zIndex: 50,
        padding: 8,
        color: "#e2e8f0",
        fontWeight: 400,
      }}
    >
      {showSort && colSortField && (
        <div
          style={{
            display: "flex",
            gap: 4,
            marginBottom: 6,
            paddingBottom: 6,
            borderBottom: "1px solid #1e293b",
          }}
        >
          <button
            type="button"
            onClick={() => onSort("asc")}
            style={sortBtnStyle(sortField === colSortField && sortDir === "asc")}
          >
            <ChevronUp size={10} style={{ marginRight: 2 }} /> A→Z
          </button>
          <button
            type="button"
            onClick={() => onSort("desc")}
            style={sortBtnStyle(sortField === colSortField && sortDir === "desc")}
          >
            <ChevronDown size={10} style={{ marginRight: 2 }} /> Z→A
          </button>
        </div>
      )}
      <input
        type="text"
        autoFocus
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search…"
        aria-label="Search options"
        style={{
          width: "100%",
          boxSizing: "border-box",
          height: 28,
          padding: "0 8px",
          background: "#1e293b",
          border: "1px solid #334155",
          borderRadius: 6,
          color: "#e2e8f0",
          fontSize: 12,
          marginBottom: 6,
        }}
      />
      {selected.length > 0 && (
        <button
          type="button"
          onClick={() => onChange([])}
          style={{
            background: "transparent",
            border: "none",
            color: "#60a5fa",
            fontSize: 10,
            padding: "2px 4px",
            cursor: "pointer",
            marginBottom: 4,
          }}
        >
          Clear ({selected.length})
        </button>
      )}
      <div style={{ maxHeight: 240, overflowY: "auto" }}>
        {filtered.length === 0 ? (
          <div
            style={{
              padding: "12px 8px",
              color: "#64748b",
              fontSize: 11,
              textAlign: "center",
            }}
          >
            No matches
          </div>
        ) : (
          filtered.map((opt) => (
            <label
              key={opt}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 6px",
                borderRadius: 4,
                cursor: "pointer",
                fontSize: 12,
                color: "#e2e8f0",
              }}
              onMouseOver={(e) => (e.currentTarget.style.background = "#1e293b")}
              onMouseOut={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <input
                type="checkbox"
                checked={isOn(opt)}
                onChange={() => toggle(opt)}
                style={{ cursor: "pointer" }}
              />
              <span
                style={{
                  flex: 1,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {opt === "null" ? "(no type)" : opt}
              </span>
            </label>
          ))
        )}
      </div>
    </div>
  );
}

function sortBtnStyle(active: boolean): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    border: `1px solid ${active ? "#3b82f6" : "#334155"}`,
    background: active ? "#3b82f6" : "transparent",
    color: active ? "#fff" : "#94a3b8",
    borderRadius: 4,
    fontSize: 10,
    cursor: "pointer",
    fontWeight: 600,
  };
}
