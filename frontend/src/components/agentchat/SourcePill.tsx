import type { CSSProperties } from "react";
import { ExternalLink, Globe } from "lucide-react";
import { tokens } from "../../styles/insightTokens";

/**
 * SourcePill — provenance pill (source name + click-through URL).
 *
 * Used by:
 *   - The agentchat citation list (DB cite shape: `[table#row_id]`).
 *   - V2 web citation list (web shape: title + favicon + agree/disagree).
 *
 * The agree/disagree tag is optional; when present it renders as a single
 * char glyph (✓ / ✗ / ◐) so screen readers can voice the `aria-label`.
 */

const c = tokens.color;
const t = tokens.typography;
const r = tokens.radius;

export type AgreeTag = "agree" | "disagree" | "context";

export interface SourcePillProps {
  /** Display label (e.g. "Reuters", "curated_deals", "[curated_deals#42]"). */
  label: string;
  /** Sub-label rendered after the main label, e.g. row id or article title. */
  subLabel?: string;
  /** Optional click-through URL. If absent, pill is non-interactive. */
  url?: string | null;
  /** Optional agree/disagree tag (V2). */
  tag?: AgreeTag | null;
  /** Show favicon glyph instead of plain icon? Default false (DB cite). */
  showFavicon?: boolean;
  style?: CSSProperties;
}

const TAG_GLYPH: Record<AgreeTag, string> = {
  agree: "\u2713",
  disagree: "\u2717",
  context: "\u25D0",
};

const TAG_COLOR: Record<AgreeTag, string> = {
  agree: tokens.color.semantic.success,
  disagree: tokens.color.semantic.danger,
  context: tokens.color.text.caption,
};

export default function SourcePill({
  label,
  subLabel,
  url,
  tag,
  showFavicon = false,
  style,
}: SourcePillProps) {
  const inner = (
    <>
      {showFavicon ? <Globe size={12} color={c.text.faint} /> : null}
      <span style={{ color: c.text.deepest, fontWeight: 600 }}>{label}</span>
      {subLabel ? <span style={{ color: c.text.muted }}>{subLabel}</span> : null}
      {tag ? (
        <span
          aria-label={`citation tag: ${tag}`}
          style={{ color: TAG_COLOR[tag], marginLeft: 2 }}
        >
          {TAG_GLYPH[tag]}
        </span>
      ) : null}
      {url ? (
        <ExternalLink size={10} color={c.brand.primaryHover} style={{ marginLeft: 2 }} />
      ) : null}
    </>
  );

  const baseStyle: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    height: 28,
    padding: "0 10px",
    background: c.bg.card,
    border: `1px solid ${c.border.default}`,
    borderRadius: r.pill,
    fontSize: t.meta.fontSize,
    lineHeight: 1,
    color: c.text.muted,
    textDecoration: "none",
    whiteSpace: "nowrap",
    ...style,
  };

  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer noopener"
        style={baseStyle}
        aria-label={`open source: ${label}${subLabel ? ` — ${subLabel}` : ""}`}
      >
        {inner}
      </a>
    );
  }
  return <span style={baseStyle}>{inner}</span>;
}
