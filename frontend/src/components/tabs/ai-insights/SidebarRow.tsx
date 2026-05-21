import { useState, type CSSProperties } from "react";
import { Bell } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";

/**
 * SidebarRow — compact, selectable row used by InsightSidebar for Today,
 * Saved, and Past-runs groups. Per docs/planning/ai-insights-mail-layout/
 * 03-ux-spec.md §3.
 */

const c = tokens.color;
const t = tokens.typography;

export interface SidebarRowProps {
  headline: string;
  selected: boolean;
  saved?: boolean;
  onClick: () => void;
  ariaLabel?: string;
  /** Extra left padding for nested past-run children. */
  indent?: number;
}

export default function SidebarRow({
  headline,
  selected,
  saved = false,
  onClick,
  ariaLabel,
  indent = 0,
}: SidebarRowProps) {
  const [hover, setHover] = useState(false);

  const showAltBg = selected || hover;

  const rowStyle: CSSProperties = {
    display: "flex",
    alignItems: "flex-start",
    gap: 6,
    width: "100%",
    textAlign: "left",
    background: showAltBg ? c.bg.surfaceAlt : "transparent",
    color: selected ? c.text.primary : c.text.body,
    borderTop: "none",
    borderRight: "none",
    borderBottom: `1px solid ${c.border.weak}`,
    borderLeft: `3px solid ${selected ? c.brand.primary : "transparent"}`,
    padding: `10px 12px 10px ${12 + indent}px`,
    fontFamily: "inherit",
    fontSize: t.body.fontSize,
    fontWeight: t.body.fontWeight,
    lineHeight: t.body.lineHeight,
    cursor: "pointer",
    transition: `${tokens.motion.transitionColor}, ${tokens.motion.transitionBg}`,
  };

  const headlineStyle: CSSProperties = {
    flex: "1 1 auto",
    minWidth: 0,
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
    textOverflow: "ellipsis",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-current={selected ? "true" : undefined}
      aria-label={ariaLabel ?? `Select insight: ${headline}`}
      style={rowStyle}
    >
      <span style={headlineStyle}>{headline}</span>
      {saved ? (
        <span
          aria-hidden="true"
          style={{
            flex: "0 0 auto",
            display: "inline-flex",
            alignItems: "center",
            marginTop: 2,
          }}
        >
          <Bell
            size={11}
            color={c.brand.primary}
            fill="currentColor"
          />
        </span>
      ) : null}
    </button>
  );
}
