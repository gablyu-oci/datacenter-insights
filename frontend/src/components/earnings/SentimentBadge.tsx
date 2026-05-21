import type { CSSProperties } from "react";

// ── Sentiment tokens ──────────────────────────────────────────────────────
// Color contracts come from docs/design/earnings_tab.md §5.2 and 5.3.
// Backend enum values: bullish | cautious | bearish | not_mentioned.

export type SentimentValue = "bullish" | "cautious" | "bearish" | "not_mentioned";
export type SentimentAxis = "ai_demand" | "power_constraints" | "datacenter_capex" | "overall";

interface SentimentToken {
  dot: string;
  bg: string;
  border: string;
  text: string;
  label: string;
}

export const SENTIMENT_TOKENS: Record<SentimentValue, SentimentToken> = {
  bullish:       { dot: "#10b981", bg: "#052e16", border: "#16a34a", text: "#4ade80", label: "Bullish" },
  cautious:      { dot: "#f59e0b", bg: "#1c1409", border: "#f59e0b", text: "#fbbf24", label: "Cautious" },
  bearish:       { dot: "#ef4444", bg: "#2a0a0a", border: "#dc2626", text: "#f87171", label: "Bearish" },
  not_mentioned: { dot: "#6b7280", bg: "#0f172a", border: "#334155", text: "#94a3b8", label: "Not mentioned" },
};

export const AXIS_LABEL: Record<SentimentAxis, string> = {
  ai_demand:         "AI demand",
  power_constraints: "Power",
  datacenter_capex:  "DC capex",
  overall:           "Overall",
};

// Map any incoming sentiment string to a known enum value (fallback to not_mentioned).
export function normalizeSentiment(value: string | null | undefined): SentimentValue {
  if (!value) return "not_mentioned";
  const v = value.toLowerCase();
  if (v === "bullish" || v === "cautious" || v === "bearish" || v === "not_mentioned") {
    return v;
  }
  return "not_mentioned";
}

interface SentimentBadgeProps {
  axis: SentimentAxis;
  value: string | null | undefined;
  size?: "sm" | "md";
  showAxisLabel?: boolean;
}

export default function SentimentBadge({
  axis,
  value,
  size = "sm",
  showAxisLabel = false,
}: SentimentBadgeProps) {
  const sentiment = normalizeSentiment(value);
  const tok = SENTIMENT_TOKENS[sentiment];

  const dotSize = size === "md" ? 8 : 6;
  const pillStyle: CSSProperties =
    size === "md"
      ? { padding: "3px 10px", fontSize: "11px" }
      : { padding: "1px 7px", fontSize: "10px" };

  const ariaLabel = `${AXIS_LABEL[axis]} sentiment: ${tok.label}`;

  return (
    <span
      role="status"
      aria-label={ariaLabel}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        ...pillStyle,
        borderRadius: 4,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        background: tok.bg,
        border: `1px solid ${tok.border}`,
        color: tok.text,
        whiteSpace: "nowrap",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: dotSize,
          height: dotSize,
          borderRadius: "50%",
          background: tok.dot,
          flexShrink: 0,
        }}
      />
      {showAxisLabel && (
        <span style={{ color: "#94a3b8", fontWeight: 600 }}>{AXIS_LABEL[axis]}:</span>
      )}
      <span>{tok.label}</span>
    </span>
  );
}
