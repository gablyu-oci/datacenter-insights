import { useState, type CSSProperties, type KeyboardEvent } from "react";
import { tokens } from "../../../../styles/insightTokens";
import StatusPill from "./StatusPill";
import { formatRelativeTime } from "./constants";
import type { OpenQuestion, OpenQuestionMateriality } from "../types";

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

const MATERIALITY_DOT_COLOR: Record<OpenQuestionMateriality, string> = {
  high: "#ef4444", // red-500
  medium: "#f59e0b", // amber-500
  low: "#94a3b8", // slate-400
};

const MATERIALITY_DOT_CLASS: Record<OpenQuestionMateriality, string> = {
  high: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-slate-400",
};

export interface TrackedQuestionCardProps {
  question: OpenQuestion;
  /** Defaults to false; parent may pass true to start expanded. */
  defaultExpanded?: boolean;
  /** Called on click/keypress; parent may use to log analytics. */
  onSelect?: (id: string) => void;
}

/**
 * TrackedQuestionCard — single tracked-question row.
 *
 * Composition: id (mono) + StatusPill in the header, latest_note clamped
 * to 2 lines in the body (expand on click / Enter / Space), materiality
 * dot + label + relative time in the footer.
 */
export default function TrackedQuestionCard({
  question,
  defaultExpanded = false,
  onSelect,
}: TrackedQuestionCardProps) {
  const [expanded, setExpanded] = useState<boolean>(defaultExpanded);

  function toggle() {
    setExpanded((v) => !v);
    if (onSelect) onSelect(question.id);
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
  }

  const bodyClampStyle: CSSProperties = expanded
    ? { display: "block" }
    : ({
        display: "-webkit-box",
        WebkitLineClamp: 2,
        WebkitBoxOrient: "vertical",
        overflow: "hidden",
      } as CSSProperties);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={toggle}
      onKeyDown={onKeyDown}
      aria-expanded={expanded}
      data-testid={`tq-card-${question.id}`}
      style={{
        background: c.bg.card,
        border: `1px solid ${c.border.default}`,
        borderRadius: r.lg,
        padding: s.s3,
        display: "flex",
        flexDirection: "column",
        gap: s.s2,
        cursor: "pointer",
        outline: "none",
        transition: "border-color 120ms, background-color 120ms",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: s.s2,
          minWidth: 0,
        }}
      >
        <span
          title={question.id}
          style={{
            fontFamily: t.mono.fontFamily,
            fontSize: t.meta.fontSize,
            color: c.text.muted,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            minWidth: 0,
            flex: "1 1 auto",
          }}
        >
          {question.id}
        </span>
        <StatusPill status={question.status} />
      </div>

      <p
        data-testid={`tq-note-${question.id}`}
        style={{
          margin: 0,
          color: c.text.body,
          fontSize: t.body.fontSize,
          lineHeight: 1.4,
          ...bodyClampStyle,
        }}
      >
        {question.latest_note}
      </p>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          color: c.text.caption,
          fontSize: t.meta.fontSize,
        }}
      >
        <span
          aria-hidden="true"
          className={MATERIALITY_DOT_CLASS[question.materiality]}
          data-materiality={question.materiality}
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            borderRadius: "50%",
            marginRight: 6,
            backgroundColor: MATERIALITY_DOT_COLOR[question.materiality],
          }}
        />
        <span>{question.materiality}</span>
        <span style={{ marginLeft: "auto" }}>
          {formatRelativeTime(question.last_seen_iso)}
        </span>
      </div>
    </div>
  );
}

