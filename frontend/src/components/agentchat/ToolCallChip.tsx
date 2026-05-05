import { useState, type CSSProperties } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { tokens } from "../../styles/insightTokens";

/**
 * ToolCallChip — collapsible chip that shows a single tool invocation.
 *
 * Used by both the global Q&A chat (legacy ToolTrace) and the AI Insights
 * tab (per-insight tool transcript).
 *
 * Accepts pre-truncated args/result strings so the caller controls how much
 * is shown — server-side truncation rule is `<=200 chars` per ARCH A5.
 */

const c = tokens.color;
const t = tokens.typography;
const r = tokens.radius;

export interface ToolCallChipProps {
  toolName: string;
  /** Truncated arg summary, e.g. SQL preview. */
  argsPreview?: string;
  /** Truncated result preview, e.g. row count or error_code. */
  resultPreview?: string;
  /** Optional row count surfaced as a separate badge. */
  rowCount?: number;
  /** Latency in ms, shown when present. */
  latencyMs?: number;
  ok?: boolean;
  /** Open by default? Default false (collapsed). */
  defaultOpen?: boolean;
  style?: CSSProperties;
}

export default function ToolCallChip({
  toolName,
  argsPreview,
  resultPreview,
  rowCount,
  latencyMs,
  ok = true,
  defaultOpen = false,
  style,
}: ToolCallChipProps) {
  const [open, setOpen] = useState(defaultOpen);

  const stripeColor = ok ? c.border.default : c.semantic.danger;

  return (
    <div
      style={{
        background: c.bg.surface,
        border: `1px solid ${stripeColor}`,
        borderLeft: `3px solid ${ok ? c.brand.primary : c.semantic.danger}`,
        borderRadius: r.md,
        fontSize: t.meta.fontSize,
        color: c.text.caption,
        ...style,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          background: "none",
          border: "none",
          color: c.text.caption,
          cursor: "pointer",
          padding: "6px 10px",
          width: "100%",
          textAlign: "left",
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontFamily: "inherit",
          fontSize: t.meta.fontSize,
        }}
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        <Wrench size={11} color={c.text.faint} />
        <code style={{ color: c.text.muted, fontFamily: t.mono.fontFamily }}>{toolName}</code>
        {typeof rowCount === "number" ? (
          <span style={{ color: c.text.faint }}>· {rowCount.toLocaleString()} rows</span>
        ) : null}
        {typeof latencyMs === "number" ? (
          <span style={{ color: c.text.faint }}>· {latencyMs} ms</span>
        ) : null}
        {!ok ? (
          <span style={{ color: c.semantic.danger, marginLeft: "auto" }}>failed</span>
        ) : null}
      </button>
      {open ? (
        <div
          style={{
            padding: "0 10px 8px 28px",
            display: "flex",
            flexDirection: "column",
            gap: 4,
            color: c.text.muted,
            fontFamily: t.mono.fontFamily,
            wordBreak: "break-all",
          }}
        >
          {argsPreview ? (
            <div>
              <span style={{ color: c.text.deepest }}>args:</span> {argsPreview}
            </div>
          ) : null}
          {resultPreview ? (
            <div>
              <span style={{ color: c.text.deepest }}>result:</span> {resultPreview}
            </div>
          ) : null}
          {!argsPreview && !resultPreview ? (
            <div style={{ color: c.text.faint }}>(no preview)</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
