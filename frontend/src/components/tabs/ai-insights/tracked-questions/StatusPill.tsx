import type { CSSProperties } from "react";
import type { OpenQuestionStatus } from "../types";
import { STATUS_CLASS } from "./constants";

/**
 * StatusPill — reusable badge for the four tracked-question statuses.
 *
 * The Tailwind classnames in `STATUS_CLASS` are the canonical reference
 * (per docs/ai_insights_v2_sidebar_design.md §6.3); they are also asserted
 * by the test suite. Because this codebase does not ship Tailwind at the
 * runtime CSS layer, we ALSO inline the equivalent hex values in `style`
 * so the visual matches the spec without a Tailwind build step.
 */

export interface StatusPillProps {
  status: OpenQuestionStatus;
  /** Optional leading number to make a count chip (e.g. "7 watching"). */
  count?: number;
  size?: "sm" | "md";
  className?: string;
}

const STATUS_STYLE: Record<OpenQuestionStatus, CSSProperties> = {
  watching: {
    color: "#1d4ed8",
    backgroundColor: "#eff6ff",
    borderColor: "#bfdbfe",
  },
  confirmed: {
    color: "#047857",
    backgroundColor: "#ecfdf5",
    borderColor: "#a7f3d0",
  },
  disproved: {
    color: "#475569",
    backgroundColor: "#f1f5f9",
    borderColor: "#e2e8f0",
  },
  stale: {
    color: "#b45309",
    backgroundColor: "#fffbeb",
    borderColor: "#fde68a",
  },
};

const STATUS_LABEL: Record<OpenQuestionStatus, string> = {
  watching: "WATCHING",
  confirmed: "CONFIRMED",
  disproved: "DISPROVED",
  stale: "STALE",
};

export default function StatusPill({
  status,
  count,
  size = "sm",
  className,
}: StatusPillProps) {
  const sizeStyle: CSSProperties =
    size === "md"
      ? { height: 24, padding: "0 10px", fontSize: 12 }
      : { height: 20, padding: "0 8px", fontSize: 11 };

  const fullClassName = [
    "tq-status-pill",
    STATUS_CLASS[status],
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span
      data-status={status}
      className={fullClassName}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        borderRadius: 999,
        borderWidth: 1,
        borderStyle: "solid",
        fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace",
        fontWeight: 600,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        whiteSpace: "nowrap",
        ...STATUS_STYLE[status],
        ...sizeStyle,
      }}
    >
      {typeof count === "number" ? (
        <span aria-hidden="true" style={{ fontWeight: 700 }}>
          {count}
        </span>
      ) : null}
      <span>{STATUS_LABEL[status]}</span>
    </span>
  );
}
