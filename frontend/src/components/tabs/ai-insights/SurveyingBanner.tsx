import { Cog } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";

/**
 * SurveyingBanner — shimmer banner shown during the bootstrap+survey phase.
 *
 * Per UX U7.4 — appears after `session_started` and before the first
 * `insight_started`. Replaced by the first card on `insight_complete[0]`.
 *
 * Animation is a wall-clock-proportional progress bar (driver passes
 * `progress` 0..1) and a slow-rotating gear glyph; both respect
 * `prefers-reduced-motion`.
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

const KEYFRAMES = `
@keyframes insightSurveyGear {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
.insight-survey-gear {
  animation: insightSurveyGear 6s linear infinite;
  display: inline-flex;
}
@media (prefers-reduced-motion: reduce) {
  .insight-survey-gear { animation: none !important; }
}
`;

export interface SurveyingBannerProps {
  /** 0..1; clamped on render. */
  progress?: number;
  /** Top line — typically the count summary. */
  message?: string;
  /** Optional secondary line — e.g. "Hypotheses: 11 · Verified: 3". */
  detail?: string;
  /** Optional ETA string, right-aligned. */
  eta?: string;
}

export default function SurveyingBanner({
  progress = 0,
  message = "Surveying the platform…",
  detail,
  eta,
}: SurveyingBannerProps) {
  const pct = Math.max(0, Math.min(1, progress)) * 100;
  return (
    <>
      <style>{KEYFRAMES}</style>
      <div
        role="status"
        aria-live="polite"
        style={{
          background: c.bg.surfaceAlt,
          border: `1px solid ${c.border.weak}`,
          borderRadius: r.lg,
          padding: `${s.s4}px ${s.s4}px`,
          display: "flex",
          flexDirection: "column",
          gap: s.s2,
          color: c.text.muted,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="insight-survey-gear">
            <Cog size={16} color={c.brand.primary} />
          </span>
          <span style={{ fontSize: t.body.fontSize, color: c.text.muted }}>{message}</span>
          {eta ? (
            <span
              style={{
                marginLeft: "auto",
                color: c.text.caption,
                fontSize: t.meta.fontSize,
              }}
            >
              ETA {eta}
            </span>
          ) : null}
        </div>
        {detail ? (
          <div style={{ color: c.text.caption, fontSize: t.meta.fontSize }}>{detail}</div>
        ) : null}
        <div
          aria-hidden="true"
          style={{
            position: "relative",
            height: 6,
            background: c.bg.surface,
            borderRadius: 3,
            overflow: "hidden",
            border: `1px solid ${c.border.weak}`,
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              width: `${pct}%`,
              background: c.brand.primary,
              transition: tokens.motion.transitionColor.replace("color", "width"),
            }}
          />
        </div>
      </div>
    </>
  );
}
