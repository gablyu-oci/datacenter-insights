import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Globe, ExternalLink } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import type { WebCitation } from "../../../types/sseEvents";

/**
 * CitationHoverCard — UX §U5.2.
 *
 * Plain-DOM hover-card (NOT a chart, NOT a portal-managed library) anchored
 * to a citation pill. Mounts after a 300ms hover (0ms on keyboard focus),
 * dismisses on pointer-leave + 100ms grace OR Escape.
 *
 * Position: prefers below-right of the anchor; flips above when within
 * 100px of the viewport bottom. Z-index 100 (sits above chart tooltips
 * which are at 50 per UX §U5.2).
 */

const c = tokens.color;
const t = tokens.typography;
const r = tokens.radius;

const CARD_WIDTH = 300;
const VIEWPORT_BOTTOM_FLIP_THRESHOLD = 100;
const Z_INDEX = 100;

type Agree = WebCitation["agree_or_disagree"];

const AGREE_GLYPH: Record<Agree, string> = {
  agree: "\u2713",
  disagree: "\u2717",
  context: "\u25D0",
};

const AGREE_LABEL: Record<Agree, string> = {
  agree: "AGREE",
  disagree: "DISAGREE",
  context: "CONTEXT",
};

const AGREE_COLOR: Record<Agree, string> = {
  // Per UX §U5.1: amber (NOT red) for disagree — red is reserved for
  // error states. Shape redundancy carries semantic weight.
  agree: c.semantic.success,
  disagree: c.semantic.warning,
  context: c.text.caption,
};

export interface CitationHoverCardProps {
  citation: WebCitation;
  /** Anchoring element. When null, the card is unmounted. */
  anchor: HTMLElement | null;
  /**
   * Caller-controlled visibility. The hover/focus/Escape lifecycle is
   * implemented in `CitationPill`; this component only renders the visual.
   */
  open: boolean;
  /**
   * Optional handler for pointer events on the card itself, so the parent
   * can keep the card mounted while the cursor moves over it.
   */
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
}

interface Position {
  top: number;
  left: number;
  flipped: boolean;
}

function hostFromUrl(url: string): string {
  try {
    return new URL(url).host;
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

function formatRetrieved(iso: string | undefined): string {
  if (!iso) return "";
  // Surface UTC date + HH:MM:SS so the hover-card spec line matches U5.2.
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const date = d.toISOString().slice(0, 10);
    const time = d.toISOString().slice(11, 19);
    return `${date} ${time} UTC`;
  } catch {
    return iso;
  }
}

export default function CitationHoverCard({
  citation,
  anchor,
  open,
  onPointerEnter,
  onPointerLeave,
}: CitationHoverCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<Position | null>(null);
  const [faviconBroken, setFaviconBroken] = useState(false);

  // Recompute position whenever the card opens (or anchor changes).
  useLayoutEffect(() => {
    if (!open || !anchor) {
      setPos(null);
      return;
    }
    const rect = anchor.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const distanceToBottom = viewportH - rect.bottom;
    const flipped = distanceToBottom < VIEWPORT_BOTTOM_FLIP_THRESHOLD;
    // Below-right by default; flip up if near the bottom.
    const top = flipped
      ? Math.max(8, rect.top + window.scrollY - 8 - 200) // best-effort upward
      : rect.bottom + window.scrollY + 6;
    const left = Math.min(
      rect.left + window.scrollX,
      window.scrollX + window.innerWidth - CARD_WIDTH - 8,
    );
    setPos({ top, left, flipped });
  }, [open, anchor]);

  // Reset favicon error state when citation changes.
  useEffect(() => {
    setFaviconBroken(false);
  }, [citation.url]);

  if (!open || !anchor || !pos) return null;

  const host = hostFromUrl(citation.url);
  const provider = citation.provider || host;
  const fav = faviconUrl(citation.url);
  const tag = citation.agree_or_disagree;

  const containerStyle: CSSProperties = {
    position: "absolute",
    top: pos.top,
    left: pos.left,
    width: CARD_WIDTH,
    background: c.bg.card,
    border: `1px solid ${c.border.default}`,
    borderRadius: r.lg,
    padding: 12,
    boxShadow: tokens.shadow.popover,
    zIndex: Z_INDEX,
    display: "flex",
    flexDirection: "column",
    gap: 8,
    color: c.text.body,
    fontSize: t.body.fontSize,
  };

  return (
    <div
      ref={cardRef}
      role="dialog"
      aria-label={`citation details: ${citation.title}`}
      style={containerStyle}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      {/* Header: favicon · provider · date */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          color: c.text.caption,
          fontSize: t.meta.fontSize,
        }}
      >
        {fav && !faviconBroken ? (
          <img
            src={fav}
            alt=""
            width={16}
            height={16}
            onError={() => setFaviconBroken(true)}
            style={{ display: "block" }}
          />
        ) : (
          <Globe size={14} color={c.text.faint} aria-hidden="true" />
        )}
        <span style={{ color: c.text.muted, fontWeight: 600 }}>{provider}</span>
        {citation.retrieved_at ? (
          <span style={{ color: c.text.faint }}>· {formatRetrieved(citation.retrieved_at).slice(0, 10)}</span>
        ) : null}
      </div>

      {/* Title */}
      <div
        style={{
          color: c.text.primary,
          fontSize: t.body.fontSize,
          fontWeight: 600,
          lineHeight: 1.4,
        }}
      >
        {citation.title}
      </div>

      <hr
        aria-hidden="true"
        style={{
          border: 0,
          borderTop: `1px solid ${c.border.default}`,
          margin: 0,
        }}
      />

      {/* Snippet (max 6 lines via line-clamp) */}
      <div
        style={{
          color: c.text.muted,
          fontSize: 12,
          lineHeight: 1.5,
          display: "-webkit-box",
          WebkitLineClamp: 6,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          fontStyle: "normal",
        }}
      >
        &ldquo;{citation.snippet}&rdquo;
      </div>

      <hr
        aria-hidden="true"
        style={{
          border: 0,
          borderTop: `1px solid ${c.border.default}`,
          margin: 0,
        }}
      />

      {/* Agree/disagree pill + rationale */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <span
          aria-label={`${AGREE_LABEL[tag]} citation`}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            height: 20,
            padding: "0 6px",
            background: "transparent",
            border: `1px solid ${AGREE_COLOR[tag]}`,
            color: AGREE_COLOR[tag],
            borderRadius: r.sm,
            fontSize: t.meta.fontSize,
            fontWeight: 600,
            whiteSpace: "nowrap",
          }}
        >
          <span aria-hidden="true">{AGREE_GLYPH[tag]}</span>
          {AGREE_LABEL[tag]}
        </span>
        <span
          style={{
            color: c.text.caption,
            fontSize: 11,
            fontStyle: "italic",
            flex: 1,
            lineHeight: 1.5,
            minWidth: 0,
          }}
        >
          {citation.rationale}
        </span>
      </div>

      {/* Footer: retrieved + open link */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          color: c.text.faint,
          fontSize: t.meta.fontSize,
          marginTop: 2,
        }}
      >
        <span>
          {citation.retrieved_at
            ? `Retrieved ${formatRetrieved(citation.retrieved_at)}`
            : null}
        </span>
        <a
          href={citation.url}
          target="_blank"
          rel="noreferrer noopener"
          style={{
            color: c.brand.primaryHover,
            fontSize: 12,
            textDecoration: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: 3,
          }}
        >
          open in new tab
          <ExternalLink size={11} aria-hidden="true" />
        </a>
      </div>
    </div>
  );
}
