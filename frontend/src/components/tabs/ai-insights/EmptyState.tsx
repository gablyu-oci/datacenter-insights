import { Lightbulb } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";

/**
 * EmptyState — first-load hero per UX U7.3.
 *
 * Shown when no prior session exists. Carries the primary CTA that kicks
 * off a new session run.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

export interface EmptyStateProps {
  onRun: () => void;
  disabled?: boolean;
  /** Override the helper text describing the platform's data scope. */
  subtitle?: string;
}

const DEFAULT_SUBTITLE =
  "The agent surveys hyperscaler datacenter sites, energy projects, and SEC events, then surfaces 5–10 non-trivial findings per run.";

export default function EmptyState({ onRun, disabled, subtitle }: EmptyStateProps) {
  return (
    <div
      style={{
        background: c.bg.card,
        border: `1px solid ${c.border.default}`,
        borderRadius: r.xl,
        padding: `${s.s8}px ${s.s7}px`,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: s.s4,
        maxWidth: 640,
        margin: `${s.s7}px auto`,
        textAlign: "center",
      }}
    >
      <Lightbulb size={56} color={c.brand.primary} aria-hidden="true" />
      <div
        style={{
          color: c.text.primary,
          fontSize: t.title.fontSize,
          fontWeight: t.title.fontWeight,
          lineHeight: t.title.lineHeight,
        }}
      >
        No sessions yet
      </div>
      <p
        style={{
          color: c.text.caption,
          fontSize: t.body.fontSize,
          lineHeight: 1.55,
          margin: 0,
          maxWidth: 460,
        }}
      >
        {subtitle ?? DEFAULT_SUBTITLE}
      </p>
      <button
        type="button"
        onClick={onRun}
        disabled={disabled}
        style={{
          background: disabled ? c.border.default : c.brand.primary,
          color: c.text.primary,
          border: "none",
          borderRadius: r.md,
          padding: "10px 18px",
          fontSize: t.body.fontSize,
          fontWeight: 600,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
      >
        Run my first insights session
      </button>
      <div style={{ color: c.text.faint, fontSize: t.meta.fontSize }}>Typical run: 60–180 s.</div>
    </div>
  );
}
