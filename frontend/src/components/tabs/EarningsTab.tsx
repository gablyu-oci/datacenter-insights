import { useMemo, useState } from "react";
import { Mic } from "lucide-react";
import { useApi } from "../../hooks/useApi";
import ErrorPanel from "../shared/ErrorPanel";
import CitationFooter from "../shared/CitationFooter";
import SentimentBadge, {
  AXIS_LABEL,
  normalizeSentiment,
  type SentimentAxis,
  type SentimentValue,
} from "../earnings/SentimentBadge";
import EarningsDetailModal from "../earnings/EarningsDetailModal";

// ── Types ─────────────────────────────────────────────────────────────────
// Matches backend/routers/earnings.py:_serialize_transcript_summary.

interface EarningsListItem {
  id: number;
  cik: string | null;
  ticker: string | null;
  company_name: string | null;
  quarter: string | null;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  call_date: string | null;
  speaker_count: number | null;
  word_count: number | null;
  extracted_at: string | null;
  retrieved_at: string | null;
  sentiment: {
    ai_demand: string | null;
    power_constraints: string | null;
    datacenter_capex: string | null;
    overall: string | null;
  };
  has_guidance: boolean;
  capex_mention_count: number;
  ai_power_mention_count: number;
  competitive_mention_count: number;
  mw_capacity_mention_count: number;
  transcript_url: string | null;
  top_quote?: string | null;
  top_quote_speaker?: string | null;
}

interface EarningsListPayload {
  items: EarningsListItem[];
  total: number;
  limit: number;
  offset: number;
  filters: {
    ticker: string | null;
    company: string | null;
    quarter: string | null;
  };
}

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const DEFAULT_PAGE_SIZE = 30;

// ── Helpers ───────────────────────────────────────────────────────────────

function formatCallDate(iso: string | null): string {
  if (!iso) return "Date unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(d);
}

function formatQuarterDisplay(q: string | null): string {
  if (!q) return "";
  const m = q.match(/^(\d{4})Q(\d)$/);
  if (m) return `Q${m[2]} ${m[1]}`;
  return q;
}

function truncate(text: string, maxLen = 140): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3).trimEnd() + "...";
}

// ── Earnings card ─────────────────────────────────────────────────────────

interface EarningsCardProps {
  item: EarningsListItem;
  onOpen: (id: number) => void;
}

function EarningsCard({ item, onOpen }: EarningsCardProps) {
  // Fallback: list endpoint may not provide top_quote yet; show placeholder
  // until backend exposes it. We surface the count of available mentions as
  // a hint when no quote is included in the summary.
  const quote = item.top_quote ?? null;
  const speaker = item.top_quote_speaker ?? null;
  const mentionHint =
    item.capex_mention_count + item.ai_power_mention_count > 0
      ? `${item.capex_mention_count} capex \u00b7 ${item.ai_power_mention_count} AI/power mentions`
      : item.has_guidance
        ? "Guidance available"
        : "No structured highlights yet";

  return (
    <button
      type="button"
      onClick={() => onOpen(item.id)}
      aria-haspopup="dialog"
      aria-label={`Open ${item.company_name ?? item.ticker ?? "company"} ${item.quarter ?? ""} earnings call details`}
      style={{
        ...CARD_STYLE,
        textAlign: "left",
        cursor: "pointer",
        color: "inherit",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        transition: "background 0.1s",
      }}
      onMouseOver={(e) => (e.currentTarget.style.background = "#22304a")}
      onMouseOut={(e) => (e.currentTarget.style.background = "#1e293b")}
      onFocus={(e) => (e.currentTarget.style.outline = "2px solid #3b82f6")}
      onBlur={(e) => (e.currentTarget.style.outline = "none")}
    >
      {/* Row 1 - ticker + name + quarter */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {item.ticker && (
          <span
            style={{
              padding: "1px 7px",
              borderRadius: 4,
              fontSize: "10px",
              fontWeight: 600,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
              background: "#0f172a",
              border: "1px solid #1d4ed8",
              color: "#60a5fa",
            }}
          >
            {item.ticker}
          </span>
        )}
        <span
          style={{
            color: "white",
            fontSize: 14,
            fontWeight: 600,
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {item.company_name ?? "Unknown"}
        </span>
        {item.quarter && (
          <span
            style={{
              padding: "1px 7px",
              borderRadius: 4,
              fontSize: "10px",
              fontWeight: 600,
              background: "#0f172a",
              border: "1px solid #334155",
              color: "#94a3b8",
            }}
          >
            {formatQuarterDisplay(item.quarter)}
          </span>
        )}
      </div>

      {/* Row 2 - call date */}
      <div style={{ color: "#94a3b8", fontSize: 11 }}>{formatCallDate(item.call_date)}</div>

      {/* Row 3 - sentiment badges */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <span style={{ color: "#64748b", fontSize: 10, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase" }}>
            AI demand
          </span>
          <SentimentBadge axis="ai_demand" value={item.sentiment.ai_demand} size="sm" />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <span style={{ color: "#64748b", fontSize: 10, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase" }}>
            Power
          </span>
          <SentimentBadge axis="power_constraints" value={item.sentiment.power_constraints} size="sm" />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <span style={{ color: "#64748b", fontSize: 10, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase" }}>
            DC capex
          </span>
          <SentimentBadge axis="datacenter_capex" value={item.sentiment.datacenter_capex} size="sm" />
        </div>
      </div>

      {/* Row 4 - top quote or hint */}
      {quote ? (
        <div>
          <div
            style={{
              color: "#cbd5e1",
              fontSize: 12,
              fontStyle: "italic",
              lineHeight: 1.5,
            }}
          >
            &ldquo;{truncate(quote, 140)}&rdquo;
          </div>
          {speaker && (
            <div style={{ color: "#64748b", fontSize: 11, marginTop: 6 }}>
              &mdash; {speaker}
            </div>
          )}
        </div>
      ) : (
        <div style={{ color: "#64748b", fontSize: 11, fontStyle: "italic" }}>{mentionHint}</div>
      )}

      {/* Footer */}
      <CitationFooter
        sources={["Alpha Vantage"]}
        retrievedAt={item.retrieved_at ?? undefined}
        sourceUrl={item.transcript_url ?? undefined}
      />
    </button>
  );
}

// ── Filter bar ────────────────────────────────────────────────────────────

interface Filters {
  tickers: string[];
  quarter: string;
  axis: SentimentAxis;
  value: SentimentValue | "";
}

const DEFAULT_FILTERS: Filters = {
  tickers: [],
  quarter: "",
  axis: "overall",
  value: "",
};

interface CompanyOption {
  ticker: string;
  name: string;
}

interface FilterBarProps {
  filters: Filters;
  onChange: (next: Filters) => void;
  companyOptions: CompanyOption[];
  quarterOptions: string[];
}

function EarningsFilterBar({ filters, onChange, companyOptions, quarterOptions }: FilterBarProps) {
  const [tickerDropdownOpen, setTickerDropdownOpen] = useState(false);

  const isDirty =
    filters.tickers.length > 0 ||
    filters.quarter !== "" ||
    filters.axis !== "overall" ||
    filters.value !== "";

  const toggleTicker = (ticker: string) => {
    if (filters.tickers.includes(ticker)) {
      onChange({ ...filters, tickers: filters.tickers.filter((t) => t !== ticker) });
    } else {
      onChange({ ...filters, tickers: [...filters.tickers, ticker] });
    }
  };

  const visibleChips = filters.tickers.slice(0, 3);
  const extraCount = filters.tickers.length - visibleChips.length;

  return (
    <form
      role="search"
      aria-label="Filter earnings calls"
      onSubmit={(e) => e.preventDefault()}
      style={{
        background: "#1e293b",
        border: "1px solid #334155",
        borderRadius: 10,
        padding: "12px 16px",
        display: "flex",
        gap: 12,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      {/* Company multi-select */}
      <div style={{ position: "relative", minWidth: 240 }}>
        <button
          type="button"
          onClick={() => setTickerDropdownOpen((v) => !v)}
          aria-haspopup="listbox"
          aria-expanded={tickerDropdownOpen}
          style={{
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: 8,
            padding: "6px 10px",
            color: "#cbd5e1",
            fontSize: 12,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            flexWrap: "wrap",
            minHeight: 32,
            width: "100%",
            textAlign: "left",
          }}
        >
          {visibleChips.length === 0 ? (
            <span style={{ color: "#64748b" }}>Companies (all)</span>
          ) : (
            visibleChips.map((t) => (
              <span
                key={t}
                style={{
                  padding: "1px 7px",
                  borderRadius: 4,
                  fontSize: "10px",
                  fontWeight: 600,
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                  background: "#1e293b",
                  border: "1px solid #1d4ed8",
                  color: "#60a5fa",
                }}
              >
                {t}
              </span>
            ))
          )}
          {extraCount > 0 && <span style={{ color: "#94a3b8", fontSize: 11 }}>+{extraCount}</span>}
        </button>
        {tickerDropdownOpen && (
          <div
            role="listbox"
            style={{
              position: "absolute",
              top: "calc(100% + 4px)",
              left: 0,
              right: 0,
              maxHeight: 280,
              overflowY: "auto",
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 8,
              zIndex: 50,
              boxShadow: "0 16px 40px rgba(0,0,0,0.6)",
            }}
          >
            {companyOptions.length === 0 ? (
              <div style={{ padding: "10px 12px", color: "#64748b", fontSize: 12 }}>
                No companies in current results
              </div>
            ) : (
              companyOptions.map((co) => {
                const selected = filters.tickers.includes(co.ticker);
                return (
                  <button
                    type="button"
                    key={co.ticker}
                    role="option"
                    aria-selected={selected}
                    onClick={() => toggleTicker(co.ticker)}
                    style={{
                      display: "flex",
                      width: "100%",
                      padding: "8px 12px",
                      gap: 8,
                      background: selected ? "#1e293b" : "transparent",
                      border: "none",
                      borderLeft: selected ? "3px solid #3b82f6" : "3px solid transparent",
                      color: "#cbd5e1",
                      cursor: "pointer",
                      textAlign: "left",
                      fontSize: 12,
                    }}
                  >
                    <span
                      style={{
                        color: "#60a5fa",
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                        minWidth: 60,
                      }}
                    >
                      {co.ticker}
                    </span>
                    <span style={{ color: "#94a3b8" }}>{co.name}</span>
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>

      {/* Quarter */}
      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ color: "#64748b", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Quarter
        </span>
        <select
          value={filters.quarter}
          onChange={(e) => onChange({ ...filters, quarter: e.target.value })}
          style={{
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: 8,
            padding: "6px 10px",
            color: "#cbd5e1",
            fontSize: 12,
            minWidth: 140,
          }}
        >
          <option value="">All quarters</option>
          {quarterOptions.map((q) => (
            <option key={q} value={q}>
              {formatQuarterDisplay(q)}
            </option>
          ))}
        </select>
      </label>

      {/* Sentiment axis + value */}
      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ color: "#64748b", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Sentiment axis
        </span>
        <select
          value={filters.axis}
          onChange={(e) => onChange({ ...filters, axis: e.target.value as SentimentAxis })}
          style={{
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: 8,
            padding: "6px 10px",
            color: "#cbd5e1",
            fontSize: 12,
            minWidth: 130,
          }}
        >
          {(Object.keys(AXIS_LABEL) as SentimentAxis[]).map((a) => (
            <option key={a} value={a}>
              {AXIS_LABEL[a]}
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ color: "#64748b", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Value
        </span>
        <select
          value={filters.value}
          onChange={(e) =>
            onChange({ ...filters, value: e.target.value as SentimentValue | "" })
          }
          style={{
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: 8,
            padding: "6px 10px",
            color: "#cbd5e1",
            fontSize: 12,
            minWidth: 130,
          }}
        >
          <option value="">Any</option>
          <option value="bullish">Bullish</option>
          <option value="cautious">Cautious</option>
          <option value="bearish">Bearish</option>
          <option value="not_mentioned">Not mentioned</option>
        </select>
      </label>

      {isDirty && (
        <button
          type="button"
          onClick={() => onChange(DEFAULT_FILTERS)}
          style={{
            background: "transparent",
            border: "none",
            color: "#94a3b8",
            fontSize: 12,
            cursor: "pointer",
            padding: "6px 0",
            marginLeft: "auto",
          }}
          onMouseOver={(e) => (e.currentTarget.style.color = "#60a5fa")}
          onMouseOut={(e) => (e.currentTarget.style.color = "#94a3b8")}
        >
          Clear filters
        </button>
      )}
    </form>
  );
}

// ── Main tab ──────────────────────────────────────────────────────────────

export default function EarningsTab() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Build a stable URL with optional filters. The list endpoint supports
  // a single ticker via `?ticker=`; if multiple are selected we filter the
  // result client-side after the round trip.
  const apiPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(DEFAULT_PAGE_SIZE));
    if (filters.tickers.length === 1) params.set("ticker", filters.tickers[0]);
    if (filters.quarter) params.set("quarter", filters.quarter);
    return `/api/earnings?${params.toString()}`;
  }, [filters.tickers, filters.quarter]);

  const { data, loading, error, errorInfo, retry, lastFetchedAt, lineage } =
    useApi<EarningsListPayload>(apiPath);

  // Derive company + quarter options from the response. Stable derivation
  // means options don't churn when filters change.
  const companyOptions = useMemo<CompanyOption[]>(() => {
    const seen = new Map<string, string>();
    for (const it of data?.items ?? []) {
      if (it.ticker && !seen.has(it.ticker)) {
        seen.set(it.ticker, it.company_name ?? it.ticker);
      }
    }
    return Array.from(seen.entries())
      .map(([ticker, name]) => ({ ticker, name }))
      .sort((a, b) => a.ticker.localeCompare(b.ticker));
  }, [data]);

  const quarterOptions = useMemo<string[]>(() => {
    const seen = new Set<string>();
    for (const it of data?.items ?? []) {
      if (it.quarter) seen.add(it.quarter);
    }
    return Array.from(seen).sort().reverse();
  }, [data]);

  // Client-side narrowing for the cases the API doesn't natively handle.
  const visibleItems = useMemo<EarningsListItem[]>(() => {
    const rows = data?.items ?? [];
    return rows.filter((it) => {
      if (filters.tickers.length > 1) {
        if (!it.ticker || !filters.tickers.includes(it.ticker)) return false;
      }
      if (filters.value) {
        let actual: string | null = null;
        if (filters.axis === "ai_demand") actual = it.sentiment.ai_demand;
        else if (filters.axis === "power_constraints") actual = it.sentiment.power_constraints;
        else if (filters.axis === "datacenter_capex") actual = it.sentiment.datacenter_capex;
        else actual = it.sentiment.overall;
        if (normalizeSentiment(actual) !== filters.value) return false;
      }
      return true;
    });
  }, [data, filters]);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: 20 }}>
      {selectedId != null && (
        <EarningsDetailModal
          transcriptId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}

      {/* Header banner */}
      <div
        style={{
          background: "linear-gradient(135deg, #0a1628 0%, #0f2240 100%)",
          border: "1px solid #1d4ed8",
          borderRadius: 10,
          padding: "12px 20px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <Mic size={16} color="#3b82f6" />
        <span style={{ color: "white", fontWeight: 600, fontSize: 14 }}>Earnings Calls</span>
        <span
          aria-live="polite"
          style={{
            padding: "2px 8px",
            borderRadius: 4,
            background: "#0f172a",
            border: "1px solid #1d4ed8",
            color: "#60a5fa",
            fontSize: "10px",
            fontWeight: 600,
          }}
        >
          {data?.total ?? 0} calls tracked
        </span>
      </div>

      <EarningsFilterBar
        filters={filters}
        onChange={setFilters}
        companyOptions={companyOptions}
        quarterOptions={quarterOptions}
      />

      {error ? (
        <ErrorPanel
          title={errorInfo?.title}
          message={errorInfo?.message}
          onRetry={retry}
          lastAttempt={lastFetchedAt}
        />
      ) : loading ? (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            height: 240,
            color: "#3b82f6",
            fontSize: 14,
          }}
        >
          Loading earnings calls...
        </div>
      ) : visibleItems.length === 0 ? (
        <div style={{ ...CARD_STYLE, textAlign: "center", padding: "60px 20px" }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
            <Mic size={24} color="#64748b" />
          </div>
          <div style={{ color: "#cbd5e1", fontSize: 14, marginBottom: 8 }}>
            No earnings calls match these filters.
          </div>
          <div style={{ color: "#94a3b8", fontSize: 12, marginBottom: 16 }}>
            {(data?.total ?? 0) === 0
              ? "The Alpha Vantage adapter runs daily at 06:45 UTC and writes new transcripts within ~48h of a call."
              : "Try widening the quarter range or clearing the company multi-select."}
          </div>
          {(filters.tickers.length > 0 || filters.quarter || filters.value) && (
            <button
              type="button"
              onClick={() => setFilters(DEFAULT_FILTERS)}
              style={{
                background: "#3b82f6",
                color: "white",
                border: "none",
                borderRadius: 6,
                padding: "8px 16px",
                cursor: "pointer",
                fontSize: 13,
                fontWeight: 500,
              }}
            >
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: 16,
          }}
        >
          {visibleItems.map((item) => (
            <EarningsCard key={item.id} item={item} onOpen={setSelectedId} />
          ))}
        </div>
      )}

      {/* Tab-level provenance footer */}
      {!loading && !error && (
        <div style={{ ...CARD_STYLE, padding: "12px 20px" }}>
          <CitationFooter
            sources={["Alpha Vantage"]}
            retrievedAt={lineage?.retrieved_at}
            confidence={lineage?.confidence}
            sourceUrl={lineage?.source_url}
          />
        </div>
      )}
    </div>
  );
}
