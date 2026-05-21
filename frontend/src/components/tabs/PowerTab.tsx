import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  LineChart, Line, ResponsiveContainer,
} from "recharts";
import { useApi } from "../../hooks/useApi";
import type { PowerCapacityResponse } from "../../types";
import ErrorPanel from "../shared/ErrorPanel";
import CitationFooter from "../shared/CitationFooter";
import {
  ExternalLink, TrendingUp, Zap, Atom, Sun,
  ChevronDown, ChevronUp,
  X, FileText, Link2, Calendar, MapPin, Clock,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────

interface CuratedDeal {
  id: string;
  // Track C: buyer/seller/energy_source can be null on edgar rows that were
  // classified as power-related but failed individual-field extraction. The
  // table renders `—` for null values rather than hiding the row.
  buyer: string | null;
  seller: string | null;
  deal_type: string;
  energy_source: string | null;
  capacity_mw: number | null;
  location?: string;
  state?: string;
  announced_date: string | null;
  status?: string;
  duration_years?: number | null;
  headline: string | null;
  source_type: string;
  source_url: string;
  edgar_url: string | null;
  excerpt: string | null;
  confidence: number | null;
  data_source: string;
  // Optional fields populated by the live EDGAR extraction pipeline.
  // Curated/archived rows may omit these.
  source?: "live" | "curated_archived";
  archived?: boolean;
  flagged_capacity?: boolean;
  methodology?: string | null;
  canonical_deal_id?: string | null;
  appearance_count?: number;
  last_extracted?: string;
  // Track C — true when the LLM extractor classified the underlying filing
  // as power/datacenter related, even when buyer/capacity couldn't be
  // pulled. The dashboard uses this as the visibility filter.
  is_power_related?: boolean;
  signing_date?: string | null;
  deal_index?: number;
}

interface GWSummaryEntry {
  gw_total: number;
  deals: number;
  nuclear_gw: number;
  renewable_gw: number;
  gas_gw?: number;
  storage_gw?: number;
  other_gw?: number;
}

interface AnnouncementsResponse {
  curated: CuratedDeal[];
  edgar: CuratedDeal[];
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

// Five visually distinct hues — brand-leaning where possible, but no two
// in the blue family (Microsoft / Google / Meta were all blues before, so
// the trend lines were indistinguishable).
const COMPANY_COLORS: Record<string, string> = {
  Microsoft: "#38BDF8", // sky blue
  Amazon:    "#F97316", // amazon orange
  Google:    "#22C55E", // google green (secondary brand)
  Meta:      "#A78BFA", // violet (clearly not blue)
  Oracle:    "#EF4444", // oracle red
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
  if (!mw) return "\u2014";
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
  // Track C: tolerate null buyer / energy_source / status on edgar rows that
  // were classified power-related but the LLM extractor couldn't pull
  // individual fields from. Display `—` placeholders rather than crashing.
  const EIcon = ENERGY_ICONS[deal.energy_source ?? ""] ?? Zap;
  const buyerName = (deal.buyer ?? "—").split(" / ")[0];
  const buyerColor = COMPANY_COLORS[buyerName] ?? "#64748b";
  const statusColor = STATUS_COLOR[deal.status ?? ""] ?? "#94a3b8";
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
          <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
            <span style={{ padding: "2px 8px", borderRadius: "4px", background: `${buyerColor}22`, color: buyerColor, fontSize: "11px", fontWeight: 600 }}>
              {buyerName}
            </span>
            {/* LIVE provenance pill removed — implicit on this tab. */}
          </div>
        </td>
        <td style={{ padding: "10px 12px", color: "#e2e8f0", fontSize: "12px", maxWidth: "340px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <EIcon size={12} color="#64748b" />
            <span style={{ lineHeight: "1.4" }}>{deal.headline ?? <span style={{ color: "#64748b", fontStyle: "italic" }}>(power-related — body not yet parsed)</span>}</span>
            {/* FE3: appearance-count badge */}
            {deal.appearance_count != null && deal.appearance_count > 1 && (
              <span
                style={{
                  padding: "2px 6px", borderRadius: 4,
                  background: "#334155", color: "#cbd5e1",
                  fontSize: 10, fontWeight: 600, whiteSpace: "nowrap",
                }}
                title={`This deal has been mentioned in ${deal.appearance_count} filings`}
              >
                mentioned in {deal.appearance_count} filings
              </span>
            )}
          </div>
        </td>
        <td
          style={{ padding: "10px 12px", color: "white", fontWeight: 600, fontSize: "13px", whiteSpace: "nowrap" }}
          title={deal.methodology ?? undefined}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            {fmtMW(deal.capacity_mw)}
            {/* FE3: methodology info icon */}
            {deal.methodology && (
              <span
                style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 13, height: 13, borderRadius: "50%",
                  background: "#1e293b", border: "1px solid #475569",
                  color: "#94a3b8", fontSize: 9, fontWeight: 700,
                  cursor: "help",
                }}
                title={deal.methodology}
              >
                i
              </span>
            )}
            {/* FE3: flagged-capacity warning */}
            {deal.flagged_capacity && (
              <span
                style={{
                  padding: "1px 5px", borderRadius: 4,
                  background: "#78350f", color: "#fde68a",
                  border: "1px solid #b45309",
                  fontSize: 10, fontWeight: 700,
                }}
                title="Capacity > 100 GW — flagged for review"
              >
                ⚠
              </span>
            )}
          </span>
        </td>
        <td style={{ padding: "10px 12px", color: "#94a3b8", fontSize: "11px" }}>{deal.energy_source ?? "—"}</td>
        <td style={{ padding: "10px 12px", color: "#94a3b8", fontSize: "11px", whiteSpace: "nowrap" }}>{deal.announced_date ?? "—"}</td>
        <td style={{ padding: "10px 12px" }}>
          <span style={{ color: statusColor, fontSize: "11px" }}>&#x25CF; {deal.status ?? "—"}</span>
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
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Confidence</div><div style={{ color: "#e2e8f0", fontSize: "12px" }}>{((deal.confidence ?? 0) * 100).toFixed(0)}%</div></div>
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
  const EIcon = ENERGY_ICONS[deal.energy_source ?? ""] ?? Zap;
  const statusColor = STATUS_COLOR[deal.status ?? ""] ?? "#94a3b8";
  const sourceUrl = deal.source_url ?? "";
  const isEdgar = sourceUrl.includes("sec.gov") || (deal.source_type ?? "").startsWith("8-K") || (deal.source_type ?? "").startsWith("10-");
  const announcedYM = (deal.announced_date ?? "").slice(0, 7);

  return (
    <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "10px", overflow: "hidden" }}>
      <div onClick={() => setOpen(v => !v)} style={{ padding: "14px 16px", cursor: "pointer", display: "flex", gap: "12px", alignItems: "flex-start" }}>
        {/* Date + source badge */}
        <div style={{ minWidth: 72, flexShrink: 0 }}>
          <div style={{ color: "#64748b", fontSize: "10px", marginBottom: "4px" }}>{announcedYM || "—"}</div>
          <div style={{
            padding: "2px 6px", borderRadius: "4px", fontSize: "9px", fontWeight: 700, textAlign: "center",
            background: isEdgar ? "#0f1e38" : "#1a2e1a",
            border: `1px solid ${isEdgar ? "#2563eb" : "#16a34a"}`,
            color: isEdgar ? "#60a5fa" : "#4ade80",
          }}>
            {isEdgar ? "SEC EDGAR" : "Press"}
          </div>
          {/* FE2: live-vs-archived provenance pill */}
          {deal.source === "archive" && (
            <div style={{
              marginTop: 4,
              padding: "2px 6px", borderRadius: "4px",
              fontSize: "9px", fontWeight: 700, textAlign: "center",
              background: "#1f1a0a",
              border: "1px solid #92400e",
              color: "#fbbf24",
            }}>
              ARCHIVED
            </div>
          )}
        </div>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: "white", fontWeight: 600, fontSize: "13px", lineHeight: 1.4, marginBottom: 6 }}>{deal.headline ?? "(untitled)"}</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            {deal.energy_source && (
              <span style={{ display: "flex", alignItems: "center", gap: 3, color: "#94a3b8", fontSize: "11px" }}><EIcon size={11} />{deal.energy_source}</span>
            )}
            {deal.capacity_mw != null && (
              <span style={{ color: "white", fontWeight: 700, fontSize: "12px" }}>{fmtMW(deal.capacity_mw)}</span>
            )}
            {deal.status && (
              <span style={{ color: statusColor, fontSize: "11px" }}>&#x25CF; {deal.status}</span>
            )}
            {deal.location && (
              <span style={{ display: "flex", alignItems: "center", gap: 3, color: "#64748b", fontSize: "11px" }}><MapPin size={10} />{deal.location}</span>
            )}
          </div>
        </div>

        <div style={{ color: "#475569", flexShrink: 0 }}>{open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</div>
      </div>

      {open && (
        <div style={{ padding: "0 16px 16px", borderTop: "1px solid #1e293b" }}>
          {/* Meta grid */}
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 0 14px" }}>
            {deal.seller && (
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Seller</div>
                <div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2 }}>{deal.seller}</div>
              </div>
            )}
            {deal.duration_years && (
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Duration</div>
                <div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2, display: "flex", alignItems: "center", gap: 3 }}><Clock size={10} />{deal.duration_years} years</div>
              </div>
            )}
            {deal.deal_type && (
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Deal Type</div>
                <div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2 }}>{deal.deal_type}</div>
              </div>
            )}
            {deal.announced_date && (
              <div><div style={{ color: "#64748b", fontSize: "10px" }}>Announced</div>
                <div style={{ color: "#e2e8f0", fontSize: "12px", marginTop: 2, display: "flex", alignItems: "center", gap: 3 }}><Calendar size={10} />{deal.announced_date}</div>
              </div>
            )}
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
  const sorted = [...deals].sort((a, b) => (b.announced_date ?? "").localeCompare(a.announced_date ?? ""));

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
                <div style={{ color: "#64748b", fontSize: 12 }}>Power Contract Intelligence -- All Verified Deals</div>
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
                { label: "Natural Gas",      value: `${(gwEntry.gas_gw ?? 0).toFixed(1)} GW`, c: "#ef4444" },
                { label: "Storage",          value: `${(gwEntry.storage_gw ?? 0).toFixed(1)} GW`, c: "#a78bfa" },
                { label: "Other",            value: `${(gwEntry.other_gw ?? 0).toFixed(1)} GW`, c: "#64748b" },
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
            {sorted.length} deals -- newest first -- click any deal to expand source
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
  const { data: capData, loading: capLoading, error: capError, errorInfo: capErrorInfo, retry: capRetry, lastFetchedAt: capLastFetched, lineage: capLineage } = useApi<PowerCapacityResponse>("/api/power/capacity");
  // (Cumulative trend chart now derives from annData — no separate timeseries fetch needed.)
  const { data: annData, loading: annLoading, error: annError, errorInfo: annErrorInfo, retry: annRetry, lineage: annLineage } = useApi<AnnouncementsResponse>("/api/power/announcements");

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterCompany, setFilterCompany] = useState("All");
  const [filterType, setFilterType] = useState("All");
  const [showCharts, setShowCharts] = useState(true);
  const [drillCompany, setDrillCompany] = useState<string | null>(null);

  // Per-column sort + filter state for the announcements table.
  type DealSortField = "buyer" | "capacity_mw" | "energy_source" | "announced_date" | "status" | "source_type";
  type CapOp = ">=" | "<=" | ">" | "<" | "=" | "between";
  const [dealSortField, setDealSortField] = useState<DealSortField>("announced_date");
  const [dealSortAsc, setDealSortAsc] = useState(false);
  const [dealColFilters, setDealColFilters] = useState<{
    buyer: string;
    headline: string;
    energy: string;
    status: string;
    source: string;
    capacity: { op: CapOp; value: string; value2: string };
  }>({
    buyer: "", headline: "", energy: "", status: "", source: "",
    capacity: { op: ">=", value: "", value2: "" },
  });
  const _CAP_OP_LABELS: Record<CapOp, string> = { ">=": "≥", "<=": "≤", ">": ">", "<": "<", "=": "=", "between": "between" };
  const clearDealColFilters = () =>
    setDealColFilters({
      buyer: "", headline: "", energy: "", status: "", source: "",
      capacity: { op: ">=", value: "", value2: "" },
    });
  const toggleDealSort = (f: DealSortField) => {
    if (dealSortField === f) setDealSortAsc(v => !v);
    else { setDealSortField(f); setDealSortAsc(false); }
  };

  // Pagination state for the announcements table.
  const [dealPage, setDealPage] = useState(0);
  const [dealPageSize, setDealPageSize] = useState(25);
  // Reset to page 0 whenever any filter / sort / page-size changes so the
  // user never lands on an empty page. MUST be declared before any early
  // return below, or the Rules of Hooks will trip on loading renders.
  useEffect(() => {
    setDealPage(0);
  }, [filterCompany, filterType, dealColFilters, dealSortField, dealSortAsc, dealPageSize]);

  if (capLoading || annLoading) return <LoadingSpinner />;

  if (capError) {
    return (
      <div style={{ padding: "24px" }}>
        <ErrorPanel
          title={capErrorInfo?.title}
          message={capErrorInfo?.message}
          onRetry={capRetry}
          lastAttempt={capLastFetched}
        />
      </div>
    );
  }

  const companies = ["Microsoft", "Amazon", "Google", "Meta", "Oracle"];
  // Merge so the local palette is the floor, server-provided colors override
  // per-company. The previous `?? COMPANY_COLORS` fell through only when the
  // server sent null/undefined; the live endpoint sends `{}` which is truthy
  // and shadowed the local palette → every line rendered as the #ccc fallback.
  const colors = { ...COMPANY_COLORS, ...(capData?.colors ?? {}) };
  const gwSummary = annData?.gw_summary ?? {};
  // FE1: Main table now renders ONLY live EDGAR extractions. Curated rows are
  // still shipped in the payload (flagged archived: true) but are partitioned
  // server-side and surfaced only inside the per-company drill-down modal.
  // Defensive: explicitly skip any row that arrives with archived === true.
  // Track C: render any edgar row classified as power/datacenter related,
  // even if buyer or capacity_mw couldn't be extracted. The extractor's
  // STEP-1 sets `is_power_related` on every row; the dashboard filter trusts
  // that classification and shows the row with `—` placeholders for missing
  // fields. Per-user requirement (2026-05-04): "keep the rows even without
  // capacity or buyer, but it has to be power contracts and data center
  // related."
  const deals = (annData?.edgar ?? []).filter(
    d => d.archived !== true && (
      d.is_power_related === true ||
      // Backward-compat: a row with both buyer + capacity is by definition
      // power-related even if the flag wasn't set by the older extractor.
      (d.buyer && d.capacity_mw)
    )
  );

  // Grouped layout: omit fields that are zero so tooltips only list
  // categories the company actually contracted. (Recharts still reserves
  // the slot width on the x-axis for declared <Bar> components, but the
  // missing-value bar renders nothing.)
  const realGWData = Object.entries(gwSummary).map(([company, v]) => {
    const row: Record<string, string | number> = { company, _total: v.gw_total, "Total GW": v.gw_total };
    if (v.nuclear_gw > 0)        row["Nuclear GW"]   = v.nuclear_gw;
    if (v.renewable_gw > 0)      row["Renewable GW"] = v.renewable_gw;
    if ((v.gas_gw ?? 0) > 0)     row["Gas GW"]       = v.gas_gw as number;
    if ((v.storage_gw ?? 0) > 0) row["Storage GW"]   = v.storage_gw as number;
    if ((v.other_gw ?? 0) > 0)   row["Other GW"]     = v.other_gw as number;
    return row;
  }).sort((a, b) => (b._total as number) - (a._total as number));

  const filteredDeals = deals.filter(d => {
    // Defensive: edgar rows may have null buyer/energy_source post-Track-C.
    const buyerMatch = filterCompany === "All" || (d.buyer ?? "").includes(filterCompany);
    const typeMatch = filterType === "All" || (d.energy_source ?? "").includes(filterType);
    return buyerMatch && typeMatch;
  });

  // Distinct values per filterable column — populates datalist suggestions
  // for typeahead-on-text inputs.
  const dealOpts = (() => {
    const buyer = new Set<string>(), energy = new Set<string>(),
      status = new Set<string>(), source = new Set<string>();
    for (const d of deals) {
      if (d.buyer) buyer.add(d.buyer.split(" / ")[0].trim());
      if (d.energy_source) energy.add(d.energy_source);
      if (d.status) status.add(d.status);
      if (d.source_type) source.add(d.source_type);
    }
    const sorted = (s: Set<string>) => [...s].sort((a, b) => a.localeCompare(b));
    return { buyer: sorted(buyer), energy: sorted(energy), status: sorted(status), source: sorted(source) };
  })();

  // Apply per-column filters + sort to filteredDeals.
  const displayedDeals = (() => {
    const m = (s: string | null | undefined, q: string) =>
      q === "" || (s ?? "").toLowerCase().includes(q.toLowerCase());
    const cap = dealColFilters.capacity;
    const capV = cap.value === "" ? null : Number(cap.value);
    const capV2 = cap.value2 === "" ? null : Number(cap.value2);
    const capMatches = (mw: number | null | undefined): boolean => {
      if (capV === null || Number.isNaN(capV)) return true;
      const v = mw ?? 0;
      switch (cap.op) {
        case ">=": return v >= capV;
        case "<=": return v <= capV;
        case ">":  return v >  capV;
        case "<":  return v <  capV;
        case "=":  return v === capV;
        case "between":
          return capV2 !== null && !Number.isNaN(capV2) ? v >= capV && v <= capV2 : v >= capV;
      }
    };
    const filtered = filteredDeals.filter(d =>
      m(d.buyer, dealColFilters.buyer) &&
      m(d.headline, dealColFilters.headline) &&
      m(d.energy_source, dealColFilters.energy) &&
      m(d.status, dealColFilters.status) &&
      m(d.source_type, dealColFilters.source) &&
      capMatches(d.capacity_mw)
    );
    const dir = dealSortAsc ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const f = dealSortField;
      if (f === "capacity_mw") return ((a.capacity_mw ?? 0) - (b.capacity_mw ?? 0)) * dir;
      const av = (a[f] ?? "") as string;
      const bv = (b[f] ?? "") as string;
      return av.localeCompare(bv) * dir;
    });
  })();

  // Paginated slice of displayedDeals. Pure derived state — no hooks.
  // The reset-on-filter useEffect is declared above with the other hooks.
  const dealPageCount = Math.max(1, Math.ceil(displayedDeals.length / dealPageSize));
  const dealPageSafe = Math.min(dealPage, dealPageCount - 1);
  const dealPageStart = dealPageSafe * dealPageSize;
  const pagedDeals = displayedDeals.slice(dealPageStart, dealPageStart + dealPageSize);

  // Cumulative power-procurement trend, derived from the live announcements
  // (curated_deals + edgar_extractions). For each (quarter × buyer) we take
  // the running sum of capacity_mw and emit GW. No separate timeseries
  // endpoint needed — every dot on the chart corresponds to a real disclosed
  // deal in the DB.
  const lineData: Array<Record<string, string | number>> = (() => {
    type Item = { date: string; buyer: string; mw: number };
    // Keep in sync with _BUYER_ALIASES in backend/routers/power.py —
    // Aterio still uses "Facebook" for Meta campuses, some EDGAR filings
    // reference "Alphabet" rather than Google, and "AWS" is Amazon.
    const aliases: Record<string, string> = {
      facebook: "Meta",
      alphabet: "Google",
      aws: "Amazon",
    };
    const canon = (raw: string | null | undefined): string => {
      if (!raw) return "";
      const head = raw.split(" / ")[0].split("/")[0].trim().toLowerCase();
      for (const [alias, mapped] of Object.entries(aliases)) {
        if (head.includes(alias)) return mapped;
      }
      for (const c of companies) {
        if (head.includes(c.toLowerCase())) return c;
      }
      return "";
    };
    type RawDeal = { announced_date?: string | null; buyer?: string | null; capacity_mw?: number | null };
    const items: Item[] = [];
    for (const src of [annData?.curated ?? [], annData?.edgar ?? []]) {
      for (const d of src as RawDeal[]) {
        const b = canon(d.buyer);
        if (!b || !d.announced_date || !d.capacity_mw) continue;
        items.push({ date: d.announced_date.slice(0, 10), buyer: b, mw: d.capacity_mw });
      }
    }
    if (items.length === 0) return [];

    const quarter = (iso: string): string => {
      const y = iso.slice(0, 4);
      const m = parseInt(iso.slice(5, 7), 10) || 1;
      return `${y} Q${Math.floor((m - 1) / 3) + 1}`;
    };
    const byQ: Record<string, Record<string, number>> = {};
    for (const it of items) {
      const q = quarter(it.date);
      byQ[q] ??= {};
      byQ[q][it.buyer] = (byQ[q][it.buyer] ?? 0) + it.mw;
    }
    const quarters = Object.keys(byQ).sort();
    const running: Record<string, number> = {};
    return quarters.map(q => {
      const row: Record<string, string | number> = { quarter: q };
      for (const c of companies) {
        running[c] = (running[c] ?? 0) + (byQ[q][c] ?? 0);
        if (running[c] > 0) row[c] = +(running[c] / 1000).toFixed(2);
      }
      return row;
    });
  })();

  const totalAnnGW = Object.values(gwSummary).reduce((s, v) => s + v.gw_total, 0).toFixed(1);
  const totalNuclearGW = Object.values(gwSummary).reduce((s, v) => s + v.nuclear_gw, 0).toFixed(1);

  // FE3: compute most-recent extraction timestamp across edgar rows.
  // Rendered as a chip in the announcements-table section header. If no row
  // carries a `last_extracted` value the chip is hidden.
  const lastExtractedLabel = (() => {
    const stamps = (annData?.edgar ?? [])
      .map(d => d.last_extracted)
      .filter((s): s is string => typeof s === "string" && !!s)
      .map(s => Date.parse(s))
      .filter(n => !Number.isNaN(n));
    if (stamps.length === 0) return null;
    const latest = new Date(Math.max(...stamps));
    const yyyy = latest.getUTCFullYear();
    const mm = String(latest.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(latest.getUTCDate()).padStart(2, "0");
    const hh = String(latest.getUTCHours()).padStart(2, "0");
    const min = String(latest.getUTCMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min} UTC`;
  })();

  // Drill-down union: curated (historical hand-verified) + edgar (live LLM
  // extractions). Both arrays come from /api/power/announcements which already
  // canonicalises buyer names; we additionally accept seller-side matches so a
  // utility-side filing (e.g. Talen 8-K naming Meta as the buyer) shows up
  // when the user drills on "Meta". Sorted newest-first by announced_date.
  // FE2: Drill-down union preserves historical context — curated archived
  // rows are merged with live edgar rows, each tagged with `source` so the
  // modal can render a small badge ("LIVE" vs "ARCHIVED"). If the backend
  // already stamps a source tag on a row we trust it; otherwise we infer
  // from which array the row came in on, defaulting to "live".
  const drillDeals = (() => {
    if (!drillCompany) return [];
    const matches = (s: string | null | undefined) =>
      !!s && s.toLowerCase().includes(drillCompany.toLowerCase());
    const curatedTagged = (annData?.curated ?? []).map(d => ({
      ...d,
      source: (d.source ?? "curated_archived") as "live" | "curated_archived",
    }));
    const edgarTagged = (annData?.edgar ?? []).map(d => ({
      ...d,
      source: (d.source ?? "live") as "live" | "curated_archived",
    }));
    const all: CuratedDeal[] = [...curatedTagged, ...edgarTagged];
    return all
      .filter(d => matches(d.buyer) || matches(d.seller))
      .sort((a, b) => (b.announced_date ?? "").localeCompare(a.announced_date ?? ""));
  })();

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
        <MetricCard label="Amazon Contracted" value="~200M" unit="MWh" sub="FY2025 10-K disclosure -- 16-yr avg" accent="#FF9900" />
        <MetricCard label="Verified Sources" value={String(annData?.data_sources.length ?? 0)} sub="EDGAR + Press Releases + Reports" accent="#3b82f6" />
      </div>

      {/* Bar chart */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>
              Contracted Power by Company -- Verified Public Announcements (GW)
            </h3>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
              Source: Aterio + SEC EDGAR. Includes per-deal PPAs and co-location agreements with disclosed MW.
              Excludes grid-tariff service and aggregate 10-K disclosures. Click a column for deal details.
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
                formatter={(v, name) => [`${Number(v).toFixed(2)} GW`, String(name)]}
                cursor={{ fill: "#ffffff10" }}
              />
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "12px" }} />
              <Bar dataKey="Total GW"     fill="#3b82f6" radius={[4,4,0,0]} />
              <Bar dataKey="Nuclear GW"   fill="#f59e0b" radius={[4,4,0,0]} />
              <Bar dataKey="Renewable GW" fill="#22c55e" radius={[4,4,0,0]} />
              <Bar dataKey="Gas GW"       fill="#ef4444" radius={[4,4,0,0]} />
              <Bar dataKey="Storage GW"   fill="#a78bfa" radius={[4,4,0,0]} />
              <Bar dataKey="Other GW"     fill="#64748b" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
        <CitationFooter
          sources={annData?.data_sources}
          retrievedAt={annLineage?.retrieved_at}
          confidence={annLineage?.confidence}
          sourceUrl={annLineage?.source_url}
        />
      </div>

      {/* Line chart */}
      {showCharts && (
        <div style={CARD_STYLE}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
            <div>
              <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>Cumulative Power Procurement Trend</h3>
              <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
                Source: Aterio + SEC EDGAR.
              </p>
            </div>
            <TrendingUp size={18} color="#3b82f6" />
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={lineData}
              style={{ cursor: "pointer" }}
              onClick={state => {
                const payload = (state as { activePayload?: Array<{ name?: string }> })?.activePayload;
                const name = payload?.[0]?.name;
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
          <CitationFooter
            sources={annData?.data_sources ?? ["curated_deals", "EDGAR live"]}
            retrievedAt={annLineage?.retrieved_at}
            confidence={annLineage?.confidence}
            sourceUrl={annLineage?.source_url}
          />
        </div>
      )}

      {/* Announcements table */}
      <div style={CARD_STYLE}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <h3 style={{ color: "white", fontWeight: 600, fontSize: "15px", margin: 0 }}>Power Contract Announcements -- Live Data</h3>
              {/* FE3: last-extracted chip — only shown if any edgar row has a timestamp */}
              {lastExtractedLabel && (
                <span
                  style={{
                    padding: "2px 8px", borderRadius: 12,
                    background: "#0b1220", border: "1px solid #1e3a5f",
                    color: "#60a5fa", fontSize: 10, fontWeight: 600,
                    whiteSpace: "nowrap",
                  }}
                  title="Most recent EDGAR extraction timestamp across visible deals"
                >
                  Last extracted: {lastExtractedLabel}
                </span>
              )}
            </div>
            <p style={{ color: "#64748b", fontSize: "12px", margin: "4px 0 0" }}>
              {displayedDeals.length === 0
                ? `0 of ${filteredDeals.length} matching`
                : `Showing ${dealPageStart + 1}–${Math.min(dealPageStart + dealPageSize, displayedDeals.length)} of ${displayedDeals.length} (filtered from ${filteredDeals.length})`}
              {" "}· click column headers to sort · type or pick from each filter dropdown to narrow
            </p>
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
        {annError ? (
          <ErrorPanel
            title={annErrorInfo?.title}
            message={annErrorInfo?.message}
            onRetry={annRetry}
            variant="inline"
          />
        ) : annLoading ? (
          <div style={{ color: "#3b82f6", textAlign: "center", padding: "40px 0" }}>Loading announcements...</div>
        ) : filteredDeals.length === 0 ? (
          <div style={{ color: "#64748b", textAlign: "center", padding: "40px 0" }}>
            No deals match the current filters.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #334155" }}>
                  <th style={{ width: 20, padding: "8px 12px" }} />
                  {([
                    { label: "Buyer",       field: "buyer" as const },
                    { label: "Headline",    field: null },
                    { label: "Capacity",    field: "capacity_mw" as const },
                    { label: "Energy Type", field: "energy_source" as const },
                    { label: "Announced",   field: "announced_date" as const },
                    { label: "Status",      field: "status" as const },
                    { label: "Source",      field: "source_type" as const },
                  ]).map(({ label, field }) => (
                    <th key={label}
                      onClick={field ? () => toggleDealSort(field) : undefined}
                      style={{
                        color: "#64748b", textAlign: "left", padding: "8px 12px",
                        fontWeight: 500, whiteSpace: "nowrap",
                        cursor: field ? "pointer" : "default", userSelect: "none",
                      }}>
                      {label}
                      {field && dealSortField === field && (
                        dealSortAsc
                          ? <ChevronUp size={10} style={{ display: "inline", marginLeft: 3 }} />
                          : <ChevronDown size={10} style={{ display: "inline", marginLeft: 3 }} />
                      )}
                    </th>
                  ))}
                </tr>
                {/* Per-column filter row */}
                <tr style={{ borderBottom: "1px solid #334155", background: "#0b1220" }}>
                  <th style={{ padding: "4px 8px" }} />
                  {([
                    ["buyer", "Buyer", dealOpts.buyer],
                    ["headline", "Headline", null],
                  ] as const).map(([key, ph, opts]) => (
                    <th key={key} style={{ padding: "4px 8px" }}>
                      <input
                        type="text"
                        list={opts ? `dl-deal-${key}` : undefined}
                        value={dealColFilters[key]}
                        onChange={e => setDealColFilters(f => ({ ...f, [key]: e.target.value }))}
                        placeholder={ph}
                        style={{
                          width: "100%", boxSizing: "border-box",
                          background: "#0f172a", border: "1px solid #1e293b",
                          borderRadius: 4, color: "#e2e8f0",
                          padding: "4px 6px", fontSize: 11,
                        }}
                      />
                      {opts && (
                        <datalist id={`dl-deal-${key}`}>
                          {opts.map(o => <option key={o} value={o} />)}
                        </datalist>
                      )}
                    </th>
                  ))}
                  {/* Capacity (numeric, comparator) */}
                  <th style={{ padding: "4px 8px" }}>
                    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                      <select
                        value={dealColFilters.capacity.op}
                        onChange={e => setDealColFilters(f => ({ ...f, capacity: { ...f.capacity, op: e.target.value as CapOp } }))}
                        style={{
                          background: "#0f172a", border: "1px solid #1e293b",
                          borderRadius: 4, color: "#e2e8f0",
                          padding: "4px 4px", fontSize: 11, cursor: "pointer",
                        }}
                      >
                        {(Object.entries(_CAP_OP_LABELS) as [CapOp, string][]).map(([op, lbl]) => (
                          <option key={op} value={op}>{lbl}</option>
                        ))}
                      </select>
                      <input
                        type="number"
                        value={dealColFilters.capacity.value}
                        onChange={e => setDealColFilters(f => ({ ...f, capacity: { ...f.capacity, value: e.target.value } }))}
                        placeholder="MW"
                        style={{
                          flex: 1, minWidth: 50, boxSizing: "border-box",
                          background: "#0f172a", border: "1px solid #1e293b",
                          borderRadius: 4, color: "#e2e8f0",
                          padding: "4px 6px", fontSize: 11,
                        }}
                      />
                      {dealColFilters.capacity.op === "between" && (
                        <input
                          type="number"
                          value={dealColFilters.capacity.value2}
                          onChange={e => setDealColFilters(f => ({ ...f, capacity: { ...f.capacity, value2: e.target.value } }))}
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
                  {([
                    ["energy", "Energy", dealOpts.energy],
                  ] as const).map(([key, ph, opts]) => (
                    <th key={key} style={{ padding: "4px 8px" }}>
                      <input
                        type="text"
                        list={`dl-deal-${key}`}
                        value={dealColFilters[key]}
                        onChange={e => setDealColFilters(f => ({ ...f, [key]: e.target.value }))}
                        placeholder={ph}
                        style={{
                          width: "100%", boxSizing: "border-box",
                          background: "#0f172a", border: "1px solid #1e293b",
                          borderRadius: 4, color: "#e2e8f0",
                          padding: "4px 6px", fontSize: 11,
                        }}
                      />
                      <datalist id={`dl-deal-${key}`}>
                        {opts.map(o => <option key={o} value={o} />)}
                      </datalist>
                    </th>
                  ))}
                  {/* Announced date — left blank; sort via header click */}
                  <th style={{ padding: "4px 8px" }} />
                  {([
                    ["status", "Status", dealOpts.status],
                    ["source", "Source", dealOpts.source],
                  ] as const).map(([key, ph, opts]) => (
                    <th key={key} style={{ padding: "4px 8px" }}>
                      <input
                        type="text"
                        list={`dl-deal-${key}`}
                        value={dealColFilters[key]}
                        onChange={e => setDealColFilters(f => ({ ...f, [key]: e.target.value }))}
                        placeholder={ph}
                        style={{
                          width: "100%", boxSizing: "border-box",
                          background: "#0f172a", border: "1px solid #1e293b",
                          borderRadius: 4, color: "#e2e8f0",
                          padding: "4px 6px", fontSize: 11,
                        }}
                      />
                      <datalist id={`dl-deal-${key}`}>
                        {opts.map(o => <option key={o} value={o} />)}
                      </datalist>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayedDeals.length === 0 && (
                  <tr>
                    <td colSpan={8} style={{ padding: "20px", textAlign: "center", color: "#64748b" }}>
                      No deals match the column filters.
                      {(dealColFilters.buyer || dealColFilters.headline || dealColFilters.energy ||
                        dealColFilters.status || dealColFilters.source ||
                        dealColFilters.capacity.value !== "") && (
                        <button
                          onClick={clearDealColFilters}
                          style={{ marginLeft: 12, background: "transparent", border: "1px solid #334155", color: "#94a3b8", borderRadius: 4, padding: "3px 10px", cursor: "pointer", fontSize: 11 }}
                        >Clear filters</button>
                      )}
                    </td>
                  </tr>
                )}
                {pagedDeals.map(deal => (
                  <DealRow key={deal.id} deal={deal} expanded={expandedId === deal.id} onToggle={() => setExpandedId(expandedId === deal.id ? null : deal.id)} />
                ))}
              </tbody>
            </table>
            {/* Pagination controls */}
            {displayedDeals.length > 0 && (
              <div style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "12px 4px 0", gap: 12, flexWrap: "wrap",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#94a3b8", fontSize: 12 }}>
                  <span>Page {dealPageSafe + 1} of {dealPageCount}</span>
                  <span style={{ color: "#475569" }}>·</span>
                  <span>Page size:</span>
                  <select
                    value={dealPageSize}
                    onChange={e => setDealPageSize(Number(e.target.value))}
                    style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 4, color: "#94a3b8", padding: "3px 6px", fontSize: 12 }}
                  >
                    {[10, 25, 50, 100].map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    onClick={() => setDealPage(0)}
                    disabled={dealPageSafe === 0}
                    style={{
                      background: "#0f172a", border: "1px solid #334155", borderRadius: 4,
                      color: dealPageSafe === 0 ? "#475569" : "#94a3b8",
                      padding: "4px 10px", fontSize: 12,
                      cursor: dealPageSafe === 0 ? "not-allowed" : "pointer",
                    }}
                  >« First</button>
                  <button
                    onClick={() => setDealPage(p => Math.max(0, p - 1))}
                    disabled={dealPageSafe === 0}
                    style={{
                      background: "#0f172a", border: "1px solid #334155", borderRadius: 4,
                      color: dealPageSafe === 0 ? "#475569" : "#94a3b8",
                      padding: "4px 10px", fontSize: 12,
                      cursor: dealPageSafe === 0 ? "not-allowed" : "pointer",
                    }}
                  >‹ Prev</button>
                  <button
                    onClick={() => setDealPage(p => Math.min(dealPageCount - 1, p + 1))}
                    disabled={dealPageSafe >= dealPageCount - 1}
                    style={{
                      background: "#0f172a", border: "1px solid #334155", borderRadius: 4,
                      color: dealPageSafe >= dealPageCount - 1 ? "#475569" : "#94a3b8",
                      padding: "4px 10px", fontSize: 12,
                      cursor: dealPageSafe >= dealPageCount - 1 ? "not-allowed" : "pointer",
                    }}
                  >Next ›</button>
                  <button
                    onClick={() => setDealPage(dealPageCount - 1)}
                    disabled={dealPageSafe >= dealPageCount - 1}
                    style={{
                      background: "#0f172a", border: "1px solid #334155", borderRadius: 4,
                      color: dealPageSafe >= dealPageCount - 1 ? "#475569" : "#94a3b8",
                      padding: "4px 10px", fontSize: 12,
                      cursor: dealPageSafe >= dealPageCount - 1 ? "not-allowed" : "pointer",
                    }}
                  >Last »</button>
                </div>
              </div>
            )}
          </div>
        )}
        <CitationFooter
          sources={annData?.data_sources}
          retrievedAt={capLineage?.retrieved_at}
          confidence={capLineage?.confidence}
          sourceUrl={capLineage?.source_url}
        />
      </div>
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "400px" }}>
      <div style={{ color: "#3b82f6", fontSize: "14px" }}>Loading intelligence data...</div>
    </div>
  );
}
