import { useId, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";

/**
 * Collapsible — generic reusable collapsible section per
 * docs/planning/save-and-history/04-ux-design.md §2.2.
 *
 * Children are conditionally rendered only while open, so any lazy data
 * fetch wired to `onFirstExpand` fires once on the user's first interaction
 * and stays hot across subsequent collapses (the consumer's cache survives;
 * only the DOM unmounts).
 *
 * Chevron rotates from 0deg (collapsed, points right) to 90deg (expanded,
 * points down) over 150ms ease-out. Honors `prefers-reduced-motion: reduce`.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;

const COLLAPSIBLE_STYLES = `
@media (prefers-reduced-motion: reduce) {
  [data-collapsible-chevron] {
    transition: none !important;
  }
}
`;

export interface CollapsibleProps {
  title: string;
  /** Rendered as "({count})" after the title; pass null to hide. */
  count?: number | null;
  /** When count is loading, render "(…)" — pass true to show the pending marker. */
  countPending?: boolean;
  /** Default false (per plan §7 default #2). */
  defaultOpen?: boolean;
  /** Fires the FIRST time the user expands (not on subsequent expands). */
  onFirstExpand?: () => void;
  children: React.ReactNode;
}

export default function Collapsible({
  title,
  count = null,
  countPending = false,
  defaultOpen = false,
  onFirstExpand,
  children,
}: CollapsibleProps) {
  const [open, setOpen] = useState<boolean>(defaultOpen);
  const hasEverOpenedRef = useRef<boolean>(defaultOpen);
  const baseId = useId();
  const headerId = `${baseId}-header`;
  const regionId = `${baseId}-region`;

  const onToggle = () => {
    setOpen((prev) => {
      const next = !prev;
      if (next && !hasEverOpenedRef.current) {
        hasEverOpenedRef.current = true;
        onFirstExpand?.();
      }
      return next;
    });
  };

  const countText = countPending
    ? "(…)"
    : count !== null && count !== undefined
      ? `(${count})`
      : null;

  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
      }}
    >
      <style>{COLLAPSIBLE_STYLES}</style>
      <button
        id={headerId}
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={regionId}
        aria-label={`${open ? "Collapse" : "Expand"} ${title}`}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-start",
          gap: s.s2,
          width: "100%",
          textAlign: "left",
          background: open ? c.bg.surfaceAlt : "transparent",
          color: open ? c.text.primary : c.text.body,
          border: "none",
          borderBottom: `1px solid ${
            open ? c.border.default : c.border.weak
          }`,
          padding: `${s.s3}px ${s.s4}px`,
          fontFamily: "inherit",
          fontSize: t.subtitle.fontSize,
          fontWeight: t.subtitle.fontWeight,
          lineHeight: t.subtitle.lineHeight,
          cursor: "pointer",
          transition: `${tokens.motion.transitionColor}, ${tokens.motion.transitionBg}`,
        }}
      >
        <ChevronRight
          size={14}
          aria-hidden="true"
          data-collapsible-chevron="true"
          style={{
            transform: open ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 150ms ease-out",
            color: open ? c.text.primary : c.text.body,
            flex: "0 0 auto",
          }}
        />
        <span>{title}</span>
        {countText ? (
          <span
            aria-live="polite"
            style={{
              color: countPending ? c.text.faint : c.text.caption,
              fontSize: t.caption.fontSize,
              fontWeight: t.caption.fontWeight,
              marginLeft: s.s1,
            }}
          >
            {countText}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          id={regionId}
          role="region"
          aria-labelledby={headerId}
          style={{
            paddingTop: s.s4,
            paddingBottom: s.s5,
          }}
        >
          {children}
        </div>
      ) : null}
    </section>
  );
}
