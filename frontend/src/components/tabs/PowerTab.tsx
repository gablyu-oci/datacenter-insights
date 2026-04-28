import { useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  LineChart, Line, ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { PowerCapacityResponse, PowerTimeseriesResponse } from "../../types";
import {
  ExternalLink, TrendingUp, Zap, Atom, Sun,
  ChevronDown, ChevronUp,
  X, FileText, Link2, Calendar, MapPin, Clock,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────

interface CuratedDeal {
  id: string;
  buyer: string;
  seller: string;
  deal_type: string;
  energy_source: string;
  capacity_mw: number | null;
  location: string;
  state: string;
  announced_date: string;
  status: string;
  duration_years: number | null;
  headline: string;
  source_type: string;
  source_url: string;
  edgar_url: string | null;
  excerpt: string;
  confidence: number;
  data_source: string;
}

interface GWSummaryEntry {
  gw_total: number;
  deals: number;
  nuclear_gw: number;
  renewable_gw: number;
}

interface AnnouncementsResponse {
  curated: CuratedDeal[];
  edgar: unknown[];
  gw_summary: Record<string, GWSummaryEntry>;
  total_deals: number;
  last_updated: string;
  data_sources: string[];
}

// ── Constants ──────────────────────────────────────────────────────────────

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const COMPANY_COLORS: Record<string, string> = {
  Microsoft: "#0078D4",
  Amazon: "#FF9900",
  Google: "#4285F4",
  Meta: "#1877F2",
  Oracle: "#C74634",
};

const ENERGY_ICONS: Record<string, typeof Atom> = {
  Nuclear: Atom,
  "Nuclear (SMR)": Atom,
  "Solar / Wind": Sun,
  "Mixed (Grid)": Zap,
  "Solar / Wind / Nuclear": Sun,
};

const STATUS_COLOR: Record<string, string> = {
  "Active": "#22c55e",
  "Active — DOE Financing Secured": "#22c55e",
  "Contracted": "#3b82f6",
  "FERC Review": "#f59e0b",
  "RFP Open": "#8b5cf6",
  "Planned": "#06b6d4",
  "Active Construction": "#f59e0b",
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtMW(mw: number | null) {
  if (!mw) return "—";
  return mw >= 1000 ? `${(mw / 1000).toFixed(1)} GW` : `${mw} MW`;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function MetricCard({ label, value, unit, sub, accent }: {
  label: string; value: string; unit?: string; sub?: string; accent?: string;
}) {
  return (
    <div style={{ ...CARD_STYLE, flex: 1, minWidth: 160 }}>
      <div style={{ color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>{label}</div>
      <div style={{ color: "white", fontSize: "26px", fontWeight: 700 }}>
        {value}<span style={{ color: "#64748b", fontSize: "13px", marginLeft: "2px" }}>{unit}</span>
      </div>
      {sub && <div style={{ color: accent ?? "#22c55e", fontSize: "11px", marginTop: "4px" }}>{sub}</div>}
    </div>
  );
}

function SourceBadge({ type, url }: { type: string; url: string }) {
  const isEdgar = url.includes("sec.gov");
  return (
    <a href={url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} style={{
      display: "inline-flex", alignItems: "center", gap: "4px",
      padding: "2px 8px", borderRadius: "4px",
      background: isEdgar ? "#1e3a5f" : "#1a2e1a",
      border: `1px solid ${isEdgar ? "#2563eb" : "#16a34a"}`,
      color: isEdgar ? "#60a5fa" : "#4ade80",
      fontSize: "10px", textDecoration: "none", cursor: "pointer",
    }}>
      <ExternalLink size={9} />{type}
    </a>
  );
}

function DealRow({ deal, expanded, onToggle }: {
  deal: CuratedDeal; expanded: boolean; onToggle: () => void;
}) {
  const EIcon = ENERGY_ICONS[deal.energy_source] ?? Zap;
  const buyerName = deal.buyer.split(" / ")[0];
  const buyerColor = COMPANY_COLORS[buyerName] ?? "#64748b";
  const statusColor = STATUS_COLOR[deal.status] ?? "#94a3b8";
  return (
    <>
      <tr onClick={onToggle} style={{
        borderBottom: expanded ? "none" : "1px solid #1e293b",
        cursor: "pointer", background: expanded ? "#162032" : "transparent",
      }}>
        <td style={{ padding: "10px 12px", width: "22px" }}>
          {expanded ? <ChevronUp size={14} color="#64748b" /> : <ChevronDown size={14} color="#64748b" />}
        </td>
        <td style={{ padding: "10px 12px" }}>
          <span style={{ padding: "2px 8px", borderRadius: "4px", background: `${buyerColor}22`, color: buyerColor, fontSize: "11px", fontWeight: 600 }}>
            {buyerName}
          </span>
        </td>
        <td style={{ padding: "10px 12px", color: "#e2e8f0", fontSize: "12px", maxWidth: "340px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <EIcon size={12} color="#64748b" />
            <span style={{ lineHeight: "1.4" }}>{deal.headline}</span>
          </div>
        </td>
        <td style={{ padding: "10px 12px", color: "white", fontWeight: 600, fontSize: "13px", whiteSpace: "nowrap" }}>{fmtMW(deal.capacity_mw)}</td>
        <td style={{ padding: "10px 12px", color: "#94a3b8", fontSize: "11px" }}>{deal.energy_source}</td>
        <td style={{ padding: "10px 12px", color: "#94a3b8", fontSize: "11px", whiteSpace: "nowrap" }}>{deal.announced_date}</td>
        <td style={{ padding: "10px 12px" }}>
          <span style={{ color: statusColor, fontSize: "11px" }}>● {deal.status}</span>
        </td>
        <td style={{ padding: "10px 12px" }}>
          <SourceBadge type={deal.source_type} url={deal.source_url} />
        </td>
      </tr>
      {expanded && (
        <tr style={{ borderBottom: "1px solid #1e293b", background: "#162032" }}>
          <td colSpan={8} style={{ padding: "0 12px 14px 48px" }}>
            <div style={{ display: "flex", gap: "24px", flexWrap: "wrap", marginBottom: "8px" }}>
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Seller</div><div style={{ color: "#e2e8f0", fontSize: "12px" }}>{deal.seller}</div></div>
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Location</div><div style={{ color: "#e2e8f0", fontSize: "12px" }}>{deal.location}</div></div>
              {deal.duration_years && <div><div style={{ color: "#64748b", fontSize: "10px" }}>Duration</div><div style={{ color: "#e2e8f0", fontSize: "12px" }}>{deal.duration_years} yr</div></div>}
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Confidence</div><div style={{ color: "#e2e8f0", fontSize: "12px" }}>{(deal.confidence * 100).toFixed(0)}%</div></div>
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Data Source</div><div style={{ color: "#e2e8f0", fontSize: "12px" }}>{deal.data_source}</div></div>
            </div>
            <div style={{ background: "#0f172a", borderRadius: "6px", padding: "10px 12px", color: "#94a3b8", fontSize: "12px", lineHeight: "1.6", borderLeft: "3px solid #3b82f6" }}>
              {deal.excerpt}
            </div>
            <div style={{ marginTop: "8px", display: "flex", gap: "8px" }}>
              <SourceBadge type={deal.source_type} url={deal.source_url} />
              {deal.edgar_url && deal.edgar_url !== deal.source_url && (
                <SourceBadge type="SEC EDGAR" url={deal.edgar_url} />
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Deal card used inside the modal ───────────────────────────────────────

function ModalDealCard({ deal }: { deal: CuratedDeal }) {
  const [open, setOpen] = useState(false);
  const EIcon = ENERGY_ICONS[deal.energy_source] ?? Zap;
  const statusColor = STATUS_COLOR[deal.status] ?? "#94a3b8";
  const isEdgar = deal.source_url.includes("sec.gov");

  return (
    <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "10px", overflow: "hidden" }}>
      <div onClick={() => setOpen(v => !v)} style={{ padding: "14px 16px", cursor: "pointer", display: "flex", gap: "12px", alignItems: "flex-start" }}>
        {/* Date + source badge */}
        <div style={{ minWidth: 72, flexShrink: 0 }}>
          <div style={{ color: "#64748b", fontSize: "10px", marginBottom: "4px" }}>{deal.announced_date.slice(0, 7)}</div>
          <div style={{
            padding: "2px 6px", borderRadius: "4px", fontSize: "9px", fontWeight: 700, textAlign: "center",
            background: isEdgar ? "#0f1e38" : "#1a2e1a",
            border: `1px solid ${isEdgar ? "#2563eb" : "#16a34a"}`,
            color: isEdgar ? "#60a5fa" : "#4ade80",
          }}>
            {isEdgar ? "SEC EDGAR" : "Press"}
          </div>
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: "white", fontWeight: 600, fontSize: "13px", lineHeight: 1.4, marginBottom: 6 }}>{deal.headline}</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 3, color: "#94a3b8", fontSize: "11px" }}><EIcon size={11} />{deal.energy_source}</span>
            <span style={{ color: "white", fontWeight: 700, fontSize: "12px" }}>{fmtMW(deal.capacity_mw)}</span>
            <span style={{ color: statusColor, fontSize: "11px" }}>● {deal.status}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 3, color: "#64748b", fontSize: "11px" }}><MapPin size={10} />{deal.location}</span>
          </div>
        </div>

        <div style={{ color: "#475569", flexShrink: 0 }}>{open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</div>
      </div>

      {open && (
        <div style={{ padding: "0 16px 16px", borderTop: "1px solid #1e293b" }}>
          {/* Meta grid */}
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 0 14px" }}>
            <div><div style={{ color: "#64748b", fontSize: "10px" }}>Seller</div><div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2 }}>{deal.seller}</div></div>
            {deal.duration_years && (
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Duration</div>
                <div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2, display: "flex", alignItems: "center", gap: 3 }}><Clock size={10} />{deal.duration_years} years</div>
              </div>
            )}
            <div><div style={{ color: "#64748b", fontSize: "10px" }}>Deal Type</div><div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2 }}>{deal.deal_type}</div></div>
            <div><div style={{ color: "#64748b", fontSize: "10px" }}>Announced</div>
              <div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2, display: "flex", alignItems: "center", gap: 3 }}><Calendar size={10} />{deal.announced_date}</div>
            </div>
          </div>

          {/* Excerpt */}
          <div style={{ background: "#1e293b", borderLeft: "3px solid #3b82f6", borderRadius: "0 6px 6px 0", padding: "10px 14px", color: "#94a3b8", fontSize: "12px", lineHeight: 1.7, marginBottom: 12 }}>
            {deal.excerpt}
          </div>

          {/* Source links */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ color: "#475569", fontSize: "10px", fontWeight: 600 }}>SOURCE</span>
            <a href={deal.source_url} target="_blank" rel="noreferrer" style={{
              display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 10px",
              borderRadius: 5, textDecoration: "none", fontSize: "11px",
              background: isEdgar ? "#0f1e38" : "#1a2e1a",
              border: `1px solid ${isEdgar ? "#2563eb" : "#16a34a"}`,
              color: isEdgar ? "#60a5fa" : "#4ade80",
            }}>
              <FileText size={10} />{deal.data_source}<ExternalLink size={9} />
            </a>
            {deal.edgar_url && deal.edgar_url !== deal.source_url && (
              <a href={deal.edgar_url} target="_blank" rel="noreferrer" style={{
                display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 10px",
                borderRadius: 5, textDecoration: "none", fontSize: "11px",
                background: "#0f1e38", border: "1px solid #2563eb", color: "#60a5fa",
              }}>
                <Link2 size={10} />SEC EDGAR Filing<ExternalLink size={9} />
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Company deals modal ────────────────────────────────────────────────────

function DealsModal({
  company, deals, gwEntry, onClose,
}: {
  company: string;
  deals: CuratedDeal[];
  gwEntry: GWSummaryEntry | undefined;
  onClose: () => void;
}) {
  const color = COMPANY_COLORS[company] ?? "#6366f1";
  const sorted = [...deals].sort((a, b) => b.announced_date.localeCompare(a.announced_date));

  return (
    // Backdrop
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
      {/* Modal panel */}
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "#0f172a",
          border: `1px solid ${color}60`,
          borderTop: `3px solid ${color}`,
          borderRadius: 14,
          width: "100%",
          maxWidth: 780,
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: `0 24px 80px rgba(0,0,0,0.6), 0 0 0 1px ${color}30`,
        }}
      >
        {/* Modal header */}
        <div style={{
          padding: "20px 24px",
          background: `linear-gradient(135deg, ${color}18 0%, transparent 100%)`,
          borderBottom: "1px solid #1e293b",
          flexShrink: 0,
        }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 4, height: 40, borderRadius: 2, background: color, flexShrink: 0 }} />
              <div>
                <div style={{ color: "white", fontSize: 22, fontWeight: 700 }}>{company}</div>
                <div style={{ color: "#64748b", fontSize: 12 }}>Power Contract Intelligence — All Verified Deals</div>
              </div>
            </div>
            <button onClick={onClose} style={{
              background: "#1e293b", border: "1px solid #334155", borderRadius: 6,
              padding: "6px 8px", cursor: "pointer", color: "#94a3b8",
              display: "flex", alignItems: "center",
            }}>
              <X size={15} />
            </button>
          </div>

          {/* Stats row */}
          {gwEntry && (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {[
                { label: "Total Contracted", value: `${gwEntry.gw_total.toFixed(1)} GW`, c: color },
                { label: "Nuclear",          value: `${gwEntry.nuclear_gw.toFixed(1)} GW`, c: "#f59e0b" },
                { label: "Renewable",        value: `${gwEntry.renewable_gw.toFixed(1)} GW`, c: "#22c55e" },
                { label: "Deals",            value: String(gwEntry.deals), c: "#94a3b8" },
              ].map(({ label, value, c }) => (
                <div key={label} style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8, padding: "8px 14px", flex: 1, minWidth: 90 }}>
                  <div style={{ color: "#64748b", fontSize: "10px", marginBottom: 2 }}>{label}</div>
                  <div style={{ color: c, fontSize: 18, fontWeight: 700 }}>{value}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Scrollable deal list */}
        <div style={{ overflowY: "auto", padding: "16px 24px 24px", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ color: "#475569", fontSize: "11px", marginBottom: 4 }}>
            {sorted.length} deals · newest first · click any deal to expand source
          </div>
          {sorted.length === 0
            ? <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>No verified deals on record.</div>
            : sorted.map(deal => <ModalDealCard key={deal.id} deal={deal} />)
          }
        </div>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function PowerTab() {
  const { data: capData, loading: capLoading } = useApi<PowerCapacityResponse>("/api/power/capacity");
  const { data: tsData, loading: tsLoading } = useApi<PowerTimeseriesResponse>("/api/power/timeseries");
  const { data: annData, loading: annLoading } = useApi<AnnouncementsResponse>("/api/power/announcements");

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterCompany, setFilterCompany] = useState("All");
  const [filterType, setFilterType] = useState("All");
  const [showCharts, setShowCharts] = useState(true);
  const [drillCompany, setDrillCompany] = useState<string | null>(null);

  if (capLoading || tsLoading) return <LoadingSpinner />;

  const companies = ["Microsoft", "Amazon", "Google", "Meta", "Oracle"];
  const colors = capData?.colors ?? {};
  const gwSummary = annData?.gw_summary ?? {};
  const deals = annData?.curated ?? [];

  const realGWData = Object.entries(gwSummary).map(([company, v]) => ({
    company,
    "Total GW": v.gw_total,
    "Nuclear GW": v.nuclear_gw,
    "Renewable GW": v.renewable_gw,
  })).sort((a, b) => b["Total GW"] - a["Total GW"]);

  const filteredDeals = deals.filter(d => {
    const buyerMatch = filterCompany === "All" || d.buyer.includes(filterCompany);
    const typeMatch = filterType === "All" || d.energy_source.includes(filterType);
    return buyerMatch && typeMatch;
  });

  const tsQuarters = tsData?.data["Microsoft"]?.map(d => d.quarter) ?? [];
  const lineData = tsQuarters.map(q => {
    const row: Record<string, string | number> = { quarter: q };
    companies.forEach(c => {
      const match = tsData?.data[c]?.find(d => d.quarter === q);
      if (match) row[c] = match.gw;
    });
    return row;
  });

  const totalAnnGW = Object.values(gwSummary).reduce((s, v) => s + v.gw_total, 0).toFixed(1);
  const totalNuclearGW = Object.values(gwSummary).reduce((s, v) => s + v.nuclear_gw, 0).toFixed(1);

  const drillDeals = drillCompany ? deals.filter(d => d.buyer.includes(drillCompany)) : [];

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}>

      {/* Modal */}
      {drillCompany && (
        <DealsModal
          company={drillCompany}
          deals={drillDeals}
          gwEntry={gwSummary[drillCompany]}
          onClose={() => setDrillCompany(null)}
        />
      )}


      {/* KPI row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <MetricCard label="Total Announced GW" value={totalAnnGW} unit="GW" sub={`${deals.length} verified deals across 5 companies`} />
        <MetricCard label="Nuclear GW Announced" value={totalNuclearGW} unit="GW" sub="Nuclear PPA + SMR + co-location" accent="#f59e0b" />
        <MetricCard label="Amazon Contracted" value="~200M" unit="MWh" sub="FY2025 10-K disclosure · 16-yr avg" accent="#FF9900" />
        <MetricCard label="Verified Sources" value={String(annData?.data_sources.length ?? 0)} sub="EDGAR + Press Releases + Reports" accent="#3b82f6" />
      </div>

      {/* Bar chart */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
              Contracted Power by Company — Verified Public Announcements (GW)
            </h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
              Click any company column to open deal details
            </p>
          </div>
          <button onClick={() => setShowCharts(v => !v)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: "12px" }}>
            {showCharts ? "Hide" : "Show"}
          </button>
        </div>
        {showCharts && (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart
              data={realGWData}
              style={{ cursor: "pointer" }}
              onClick={state => {
                // activeLabel is populated from the x-position of the click
                const label = state?.activeLabel as string | undefined;
                if (label) setDrillCompany(label);
              }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#0f172a" />
              <XAxis dataKey="company" tick={{ fill: "#94a3b8", fontSize: 12 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} unit=" GW" />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                labelStyle={{ color: "white" }}
                itemStyle={{ color: "#94a3b8" }}
                formatter={(v: number, name: string) => [`${v.toFixed(2)} GW`, name]}
                cursor={{ fill: "#ffffff10" }}
              />
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
              <Bar dataKey="Total GW"    fill="#3b82f6" radius={[4,4,0,0]} />
              <Bar dataKey="Nuclear GW"  fill="#f59e0b" radius={[4,4,0,0]} />
              <Bar dataKey="Renewable GW" fill="#22c55e" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Line chart */}
      {showCharts && (
        <div style={CARD_STYLE}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
            <div>
              <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>Cumulative Power Procurement Trend</h3>
              <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
                Quarterly modeled growth curve — calibrated to disclosed annual totals
                <span style={{ color: "#f59e0b", marginLeft: 8 }}>⚠ Modeled</span>
              </p>
            </div>
            <TrendingUp size={18} color="#3b82f6" />
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={lineData}
              style={{ cursor: "pointer" }}
              onClick={state => {
                const name = state?.activePayload?.[0]?.name as string | undefined;
                if (name) setDrillCompany(name);
              }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="quarter" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} unit=" GW" />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8 }}
                labelStyle={{ color: "white" }}
                cursor={{ stroke: "#334155" }}
              />
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
              {companies.map(c => (
                <Line key={c} type="monotone" dataKey={c} stroke={colors[c] ?? "#ccc"} strokeWidth={2} dot={false} activeDot={{ r: 6, style: { cursor: "pointer" } }} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Announcements table */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>Power Contract Announcements — Live Data</h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>{filteredDeals.length} verified deals · Click row for source excerpt</p>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <select value={filterCompany} onChange={e => setFilterCompany(e.target.value)}
              style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6, color: "white", padding: "5px 8px", fontSize: "12px" }}>
              {["All","Microsoft","Google","Amazon","Meta","Oracle"].map(c => <option key={c}>{c}</option>)}
            </select>
            <select value={filterType} onChange={e => setFilterType(e.target.value)}
              style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6, color: "white", padding: "5px 8px", fontSize: "12px" }}>
              {["All","Nuclear","Solar / Wind","Mixed"].map(t => <option key={t}>{t}</option>)}
            </select>
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #334155" }}>
                <th style={{ width: 20, padding: "8px 12px" }} />
                {["Buyer","Headline","Capacity","Energy Type","Announced","Status","Source"].map(h => (
                  <th key={h} style={{ color: "#64748b", textAlign: "left", padding: "8px 12px", fontWeight: 500, whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...filteredDeals]
                .sort((a, b) => b.announced_date.localeCompare(a.announced_date))
                .map(deal => (
                  <DealRow key={deal.id} deal={deal} expanded={expandedId === deal.id} onToggle={() => setExpandedId(expandedId === deal.id ? null : deal.id)} />
                ))}
            </tbody>
          </table>
        </div>
      </div>

      {annLoading && null}
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px" }}>
      <div style={{ color: "#3b82f6", fontSize: "14px" }}>Loading intelligence data…</div>
    </div>
  );
}
