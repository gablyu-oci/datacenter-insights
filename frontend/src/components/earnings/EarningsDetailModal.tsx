import { useEffect, useState } from "react";
import { X, ExternalLink, FileText } from "lucide-react";
import { useApi } from "../../hooks/useApi";
import ErrorPanel from "../shared/ErrorPanel";
import SentimentBadge, { normalizeSentiment } from "./SentimentBadge";

// ── Types ─────────────────────────────────────────────────────────────────
// Shapes match backend/routers/earnings.py:_serialize_transcript_detail.

export interface EarningsSentiment {
  ai_demand: string | null;
  power_constraints: string | null;
  datacenter_capex: string | null;
  overall: string | null;
}

export interface EarningsGuidance {
  revenue_growth?: string | null;
  capex_outlook?: string | null;
  raw_quote?: string | null;
}

export interface CapexMention {
  quote: string;
  dollar_amount?: string | null;
  context?: string | null;
  speaker?: string | null;
  section?: string | null;
}

export interface AIPowerMention {
  quote: string;
  theme?: "AI" | "datacenter" | "power" | "grid" | string | null;
  context?: string | null;
  speaker?: string | null;
  section?: string | null;
}

export interface CompetitiveMention {
  quote: string;
  mentioned_company?: string | null;
  sentiment?: string | null;
  speaker?: string | null;
  section?: string | null;
}

export interface MWCapacityMention {
  quote: string;
  mw_value?: number | string | null;
  location?: string | null;
  speaker?: string | null;
  section?: string | null;
}

export interface EarningsPassage {
  passage_id: string;
  ord: number;
  text: string;
  speaker: string | null;
  section: string | null;
  score: number;
}

export interface EarningsDetail {
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
  sentiment: EarningsSentiment;
  transcript_url: string | null;
  extractor_version: string | null;
  guidance: EarningsGuidance | null;
  capex_mentions: CapexMention[];
  ai_power_mentions: AIPowerMention[];
  competitive_mentions: CompetitiveMention[];
  mw_capacity_mentions: MWCapacityMention[];
  top_passages: EarningsPassage[];
}

// ── Theme chip colors (docs §5.3) ─────────────────────────────────────────

const THEME_CHIP: Record<string, { bg: string; border: string; text: string; label: string }> = {
  AI:         { bg: "#1e1b4b", border: "#6366f1", text: "#a5b4fc", label: "AI" },
  datacenter: { bg: "#0c1a3d", border: "#3b82f6", text: "#93c5fd", label: "DC" },
  power:      { bg: "#1c1917", border: "#f59e0b", text: "#fbbf24", label: "PWR" },
  grid:       { bg: "#1a1410", border: "#dc2626", text: "#fca5a5", label: "GRID" },
};

function themeChip(raw: string | null | undefined) {
  if (!raw) return THEME_CHIP.AI;
  const k = raw.toLowerCase();
  if (k === "ai") return THEME_CHIP.AI;
  if (k === "datacenter" || k === "dc") return THEME_CHIP.datacenter;
  if (k === "power" || k === "pwr") return THEME_CHIP.power;
  if (k === "grid") return THEME_CHIP.grid;
  return THEME_CHIP.AI;
}

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
  // Backend format is e.g. "2026Q1" → display "Q1 2026".
  const m = q.match(/^(\d{4})Q(\d)$/);
  if (m) return `Q${m[2]} ${m[1]}`;
  return q;
}

function attribution(speaker: string | null | undefined, section: string | null | undefined) {
  const sp = speaker?.trim() || "(speaker unknown)";
  return section ? `${sp} \u00b7 ${section}` : sp;
}

// ── Styled atoms ──────────────────────────────────────────────────────────

function SectionLabel({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <div
      style={{
        color: "#94a3b8",
        fontSize: "11px",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        marginBottom: 10,
      }}
    >
      {children}
      {typeof count === "number" && count > 0 ? ` (${count})` : null}
    </div>
  );
}

function QuoteBlock({
  quote,
  speaker,
  section,
}: {
  quote: string;
  speaker: string | null | undefined;
  section: string | null | undefined;
}) {
  return (
    <div
      style={{
        background: "#0f172a",
        border: "1px solid #1e293b",
        borderLeft: "3px solid #3b82f6",
        borderRadius: 6,
        padding: "10px 14px",
        margin: "6px 0",
      }}
    >
      <div
        style={{
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          fontSize: 12,
          lineHeight: 1.55,
          color: "#e2e8f0",
          whiteSpace: "pre-wrap",
        }}
      >
        {quote}
      </div>
      <div style={{ color: "#64748b", fontSize: 11, marginTop: 6 }}>
        &mdash; {attribution(speaker, section)}
      </div>
    </div>
  );
}

// ── Modal ─────────────────────────────────────────────────────────────────

interface EarningsDetailModalProps {
  transcriptId: number;
  onClose: () => void;
}

interface RawTranscriptResponse {
  transcript_id: number;
  ticker: string;
  company_name: string;
  quarter: string;
  call_date: string | null;
  speaker_count: number | null;
  word_count: number | null;
  raw_text: string;
}

export default function EarningsDetailModal({ transcriptId, onClose }: EarningsDetailModalProps) {
  const { data, loading, error, errorInfo, retry, lastFetchedAt } =
    useApi<EarningsDetail>(`/api/earnings/${transcriptId}`);

  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [transcriptText, setTranscriptText] = useState<string | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);

  const onToggleTranscript = async () => {
    if (transcriptOpen) {
      setTranscriptOpen(false);
      return;
    }
    setTranscriptOpen(true);
    if (transcriptText !== null) return;
    setTranscriptLoading(true);
    setTranscriptError(null);
    try {
      const apiBase = import.meta.env.VITE_API_BASE_URL || "";
      const resp = await fetch(`${apiBase}/api/earnings/${transcriptId}/transcript-text`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      const text = (body?.data?.raw_text ?? "") as string;
      setTranscriptText(text);
    } catch (e) {
      setTranscriptError(e instanceof Error ? e.message : String(e));
    } finally {
      setTranscriptLoading(false);
    }
  };

  // Esc-to-close + body scroll lock.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const detail = data;
  const sentiment = detail?.sentiment;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Earnings call details"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 100,
        background: "#0f172aee",
        backdropFilter: "blur(3px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#1e293b",
          border: "1px solid #334155",
          borderTop: "3px solid #3b82f6",
          borderRadius: 14,
          width: "100%",
          maxWidth: 760,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid #0f172a",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 12,
          }}
        >
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {detail?.ticker && (
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
                  {detail.ticker}
                </span>
              )}
              <div style={{ color: "white", fontWeight: 700, fontSize: 16 }}>
                {detail?.company_name ?? (loading ? "Loading..." : "Earnings call")}
              </div>
              {detail?.quarter && (
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
                  {formatQuarterDisplay(detail.quarter)}
                </span>
              )}
              <span style={{ color: "#94a3b8", fontSize: 11 }}>
                {formatCallDate(detail?.call_date ?? null)}
              </span>
            </div>
            {sentiment && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <SentimentBadge axis="ai_demand" value={sentiment.ai_demand} size="md" showAxisLabel />
                <SentimentBadge axis="power_constraints" value={sentiment.power_constraints} size="md" showAxisLabel />
                <SentimentBadge axis="datacenter_capex" value={sentiment.datacenter_capex} size="md" showAxisLabel />
                <SentimentBadge axis="overall" value={sentiment.overall} size="md" showAxisLabel />
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close earnings call details"
            style={{
              background: "#0f172a",
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

        {/* Body */}
        <div style={{ overflowY: "auto", padding: "16px 20px 20px" }}>
          {error ? (
            <ErrorPanel
              title={errorInfo?.title}
              message={errorInfo?.message}
              onRetry={retry}
              lastAttempt={lastFetchedAt}
              variant="inline"
            />
          ) : loading || !detail ? (
            <div style={{ color: "#3b82f6", textAlign: "center", padding: "40px 0" }}>
              Loading transcript...
            </div>
          ) : (
            <>
              {/* Guidance */}
              {detail.guidance &&
                (detail.guidance.revenue_growth ||
                  detail.guidance.capex_outlook ||
                  detail.guidance.raw_quote) && (
                  <section style={{ marginBottom: 20 }}>
                    <SectionLabel>Guidance</SectionLabel>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "140px 1fr",
                        rowGap: 6,
                        columnGap: 12,
                        marginBottom: 8,
                      }}
                    >
                      {detail.guidance.revenue_growth && (
                        <>
                          <div style={{ color: "#64748b", fontSize: 11 }}>Revenue growth</div>
                          <div style={{ color: "#cbd5e1", fontSize: 12 }}>{detail.guidance.revenue_growth}</div>
                        </>
                      )}
                      {detail.guidance.capex_outlook && (
                        <>
                          <div style={{ color: "#64748b", fontSize: 11 }}>Capex outlook</div>
                          <div style={{ color: "#cbd5e1", fontSize: 12 }}>{detail.guidance.capex_outlook}</div>
                        </>
                      )}
                    </div>
                    {detail.guidance.raw_quote && (
                      <QuoteBlock quote={detail.guidance.raw_quote} speaker={null} section={null} />
                    )}
                  </section>
                )}

              {/* Capex */}
              {detail.capex_mentions.length > 0 && (
                <section style={{ marginBottom: 20 }}>
                  <SectionLabel count={detail.capex_mentions.length}>Capex Mentions</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {detail.capex_mentions.map((m, i) => (
                      <div key={i}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          {m.dollar_amount && (
                            <span
                              style={{
                                padding: "1px 7px",
                                borderRadius: 4,
                                fontSize: "10px",
                                fontWeight: 600,
                                background: "#052e16",
                                border: "1px solid #16a34a",
                                color: "#4ade80",
                              }}
                            >
                              {m.dollar_amount}
                            </span>
                          )}
                          {m.context && (
                            <span style={{ color: "#94a3b8", fontSize: 12 }}>{m.context}</span>
                          )}
                        </div>
                        <QuoteBlock quote={m.quote} speaker={m.speaker} section={m.section} />
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* AI & Power */}
              {detail.ai_power_mentions.length > 0 && (
                <section style={{ marginBottom: 20 }}>
                  <SectionLabel count={detail.ai_power_mentions.length}>AI &amp; Power Mentions</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {detail.ai_power_mentions.map((m, i) => {
                      const chip = themeChip(typeof m.theme === "string" ? m.theme : null);
                      return (
                        <div key={i}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            <span
                              style={{
                                padding: "1px 7px",
                                borderRadius: 4,
                                fontSize: "10px",
                                fontWeight: 600,
                                letterSpacing: "0.04em",
                                background: chip.bg,
                                border: `1px solid ${chip.border}`,
                                color: chip.text,
                              }}
                            >
                              {chip.label}
                            </span>
                            {m.context && (
                              <span style={{ color: "#94a3b8", fontSize: 12 }}>{m.context}</span>
                            )}
                          </div>
                          <QuoteBlock quote={m.quote} speaker={m.speaker} section={m.section} />
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}

              {/* Competitive */}
              {detail.competitive_mentions.length > 0 && (
                <section style={{ marginBottom: 20 }}>
                  <SectionLabel count={detail.competitive_mentions.length}>Competitive Mentions</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {detail.competitive_mentions.map((m, i) => (
                      <div key={i}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          {m.mentioned_company && (
                            <span style={{ color: "#60a5fa", fontSize: 12, fontWeight: 600 }}>
                              vs {m.mentioned_company}
                            </span>
                          )}
                          {m.sentiment && (
                            <SentimentBadge axis="overall" value={m.sentiment} size="sm" />
                          )}
                        </div>
                        <QuoteBlock quote={m.quote} speaker={m.speaker} section={m.section} />
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* MW capacity */}
              {detail.mw_capacity_mentions.length > 0 && (
                <section style={{ marginBottom: 20 }}>
                  <SectionLabel count={detail.mw_capacity_mentions.length}>MW Capacity Mentions</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {detail.mw_capacity_mentions.map((m, i) => (
                      <div key={i}>
                        <div style={{ color: "white", fontSize: 13, fontWeight: 600 }}>
                          {m.mw_value != null ? `${m.mw_value} MW` : ""}
                          {m.mw_value != null && m.location ? " \u00b7 " : ""}
                          {m.location ?? ""}
                        </div>
                        <QuoteBlock quote={m.quote} speaker={m.speaker} section={m.section} />
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Top BM25 passages */}
              {detail.top_passages.length > 0 && (
                <section style={{ marginBottom: 20 }}>
                  <SectionLabel count={detail.top_passages.length}>Top Quoted Moments</SectionLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {detail.top_passages.map((p) => (
                      <QuoteBlock
                        key={p.passage_id}
                        quote={p.text}
                        speaker={p.speaker}
                        section={p.section}
                      />
                    ))}
                  </div>
                </section>
              )}

              {/* Footer */}
              <div
                style={{
                  marginTop: 20,
                  paddingTop: 12,
                  borderTop: "1px solid #0f172a",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                <button
                  type="button"
                  onClick={onToggleTranscript}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "#3b82f6",
                    fontWeight: 600,
                    fontSize: 12,
                    padding: 0,
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <FileText size={11} />
                  {transcriptOpen ? "Hide full transcript" : "Read full transcript"}
                </button>
                {detail.transcript_url && (
                  <a
                    href={detail.transcript_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      color: "#64748b",
                      fontSize: 11,
                      textDecoration: "none",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                    }}
                  >
                    External source <ExternalLink size={10} />
                  </a>
                )}
                {transcriptOpen && (
                  <div
                    style={{
                      marginTop: 8,
                      padding: 12,
                      background: "#0f172a",
                      border: "1px solid #1e293b",
                      borderRadius: 6,
                      maxHeight: 360,
                      overflowY: "auto",
                      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                      fontSize: 12,
                      lineHeight: 1.6,
                      color: "#cbd5e1",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    {transcriptLoading && <span style={{ color: "#94a3b8" }}>Loading transcript…</span>}
                    {transcriptError && (
                      <span style={{ color: "#f87171" }}>
                        Failed to load transcript: {transcriptError}
                      </span>
                    )}
                    {transcriptText !== null && !transcriptLoading && !transcriptError && (
                      transcriptText || <span style={{ color: "#94a3b8" }}>Transcript text is empty.</span>
                    )}
                  </div>
                )}
                <div style={{ color: "#64748b", fontSize: 11 }}>
                  {detail.retrieved_at && (
                    <>Retrieved {detail.retrieved_at.split("T")[0]}</>
                  )}
                  {detail.extractor_version && <> &middot; Extractor v{detail.extractor_version}</>}
                  {detail.speaker_count != null && <> &middot; Speakers {detail.speaker_count}</>}
                  {detail.word_count != null && <> &middot; Words {detail.word_count.toLocaleString()}</>}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
