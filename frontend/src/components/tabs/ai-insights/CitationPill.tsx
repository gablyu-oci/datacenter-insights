import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Globe, ExternalLink } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import type { WebCitation } from "../../../types/sseEvents";
import CitationHoverCard from "./CitationHoverCard";

/**
 * CitationPill — UX §U5.1.
 *
 * Wraps a `WebCitation` as an inline pill (favicon · host · title · agree
 * glyph) and mounts a `CitationHoverCard` on hover/focus. Used by both
 * the V2 citations row inside `InsightCard` and inline assistant messages
 * in `InsightChatDock`.
 *
 * Lifecycle:
 *   - Hover: 300ms delay before mount.
 *   - Keyboard focus: mounts immediately (0ms).
 *   - Pointer leave: 100ms grace window so the user can move the cursor
 *     onto the hover-card itself.
 *   - Escape key dismisses while focused.
 */

const c = tokens.color;
const t = tokens.typography;

const HOVER_OPEN_MS = 300;
const HOVER_CLOSE_GRACE_MS = 100;

type Agree = WebCitation["agree_or_disagree"];

const AGREE_GLYPH: Record<Agree, string> = {
  agree: "\u2713",
  disagree: "\u2717",
  context: "\u25D0",
};

const AGREE_COLOR: Record<Agree, string> = {
  agree: c.semantic.success,
  disagree: c.semantic.warning,
  context: c.text.caption,
};

const AGREE_ARIA: Record<Agree, string> = {
  agree: "agreeing citation",
  disagree: "disagreeing citation",
  context: "contextual citation",
};

function hostFromUrl(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function faviconUrl(url: string): string | null {
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.host}/favicon.ico`;
  } catch {
    return null;
  }
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n - 1)}\u2026` : s;
}

export interface CitationPillProps {
  citation: WebCitation;
  /** Optional override for the pill style (e.g. inline vs row). */
  style?: CSSProperties;
}

export default function CitationPill({ citation, style }: CitationPillProps) {
  const anchorRef = useRef<HTMLAnchorElement>(null);
  const [open, setOpen] = useState(false);
  const [faviconBroken, setFaviconBroken] = useState(false);
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setFaviconBroken(false);
  }, [citation.url]);

  // Cleanup timers on unmount.
  useEffect(() => {
    return () => {
      if (openTimerRef.current) clearTimeout(openTimerRef.current);
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    };
  }, []);

  const cancelClose = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const scheduleOpen = useCallback(() => {
    cancelClose();
    if (openTimerRef.current) clearTimeout(openTimerRef.current);
    openTimerRef.current = setTimeout(() => setOpen(true), HOVER_OPEN_MS);
  }, [cancelClose]);

  const scheduleClose = useCallback(() => {
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    closeTimerRef.current = setTimeout(
      () => setOpen(false),
      HOVER_CLOSE_GRACE_MS,
    );
  }, []);

  const openImmediate = useCallback(() => {
    cancelClose();
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    setOpen(true);
  }, [cancelClose]);

  // Esc key dismiss while focused.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const tag = citation.agree_or_disagree;
  const host = hostFromUrl(citation.url);
  const fav = faviconUrl(citation.url);
  const labelText = truncate(citation.title, 60);

  const baseStyle: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    height: 28,
    padding: "0 10px",
    background: c.bg.card,
    border: `1px solid ${c.border.default}`,
    borderRadius: 14,
    fontSize: t.meta.fontSize,
    lineHeight: 1,
    color: c.text.muted,
    textDecoration: "none",
    whiteSpace: "nowrap",
    cursor: "pointer",
    maxWidth: "100%",
    ...style,
  };

  return (
    <>
      <a
        ref={anchorRef}
        href={citation.url}
        target="_blank"
        rel="noreferrer noopener"
        aria-label={`${AGREE_ARIA[tag]} from ${host}: ${citation.title}. Open in new tab.`}
        style={baseStyle}
        onPointerEnter={scheduleOpen}
        onPointerLeave={scheduleClose}
        onFocus={openImmediate}
        onBlur={scheduleClose}
      >
        {fav && !faviconBroken ? (
          <img
            src={fav}
            alt=""
            width={16}
            height={16}
            onError={() => setFaviconBroken(true)}
            style={{ display: "block", flexShrink: 0 }}
          />
        ) : (
          <Globe size={12} color={c.text.faint} aria-hidden="true" />
        )}
        <span style={{ color: c.text.deepest, fontWeight: 600 }}>{host}</span>
        <span
          style={{
            color: c.text.muted,
            overflow: "hidden",
            textOverflow: "ellipsis",
            minWidth: 0,
          }}
        >
          {"\u00b7 "}{labelText}
        </span>
        <span
          aria-label={`citation tag: ${tag}`}
          style={{
            color: AGREE_COLOR[tag],
            marginLeft: 2,
            fontWeight: 700,
          }}
        >
          {AGREE_GLYPH[tag]}
        </span>
        <ExternalLink
          size={10}
          color={c.brand.primaryHover}
          style={{ marginLeft: 2, flexShrink: 0 }}
          aria-hidden="true"
        />
      </a>
      <CitationHoverCard
        citation={citation}
        anchor={anchorRef.current}
        open={open}
        onPointerEnter={cancelClose}
        onPointerLeave={scheduleClose}
      />
    </>
  );
}

/**
 * CitationsRow — convenience renderer for an inline row of citation pills,
 * used inside `InsightCard` between the body and provenance footer.
 *
 * Caps inline pills at `maxInline`; remaining citations roll up into a
 * `+N more` chip whose click is a no-op for V2 (V3 hooks an
 * InsightCitationsModal). Per UX §U5.3.
 */
export interface CitationsRowProps {
  citations: WebCitation[];
  /** Default 3 inline + the +N more chip per UX §U5.3 (we use 3 here). */
  maxInline?: number;
  /** Optional click handler for the `+N more` chip. */
  onShowMore?: () => void;
}

export function CitationsRow({
  citations,
  maxInline = 3,
  onShowMore,
}: CitationsRowProps) {
  if (!citations || citations.length === 0) return null;
  const visible = citations.slice(0, maxInline);
  const remainder = citations.length - visible.length;

  return (
    <div
      role="list"
      aria-label="external citations"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 6,
        alignItems: "center",
      }}
    >
      {visible.map((cit, i) => (
        <span role="listitem" key={`${cit.url}-${i}`}>
          <CitationPill citation={cit} />
        </span>
      ))}
      {remainder > 0 ? (
        <button
          type="button"
          onClick={onShowMore}
          aria-label={`show ${remainder} more citations`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            height: 28,
            padding: "0 10px",
            background: c.bg.card,
            border: `1px solid ${c.border.default}`,
            borderRadius: 14,
            fontSize: t.meta.fontSize,
            color: c.text.caption,
            cursor: onShowMore ? "pointer" : "default",
            fontFamily: "inherit",
          }}
        >
          +{remainder} more
        </button>
      ) : null}
    </div>
  );
}

