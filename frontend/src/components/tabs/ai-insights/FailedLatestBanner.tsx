import { AlertTriangle } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import { formatUtcMinute, formatHourMinUtc } from "./utcFormat";

/**
 * FailedLatestBanner — visual scaffolding for the stale-run banner
 * described in 04-ux.md §3.4.1 + 04a-ux-delta-phase4-implementation.md §4.
 *
 * TODO(backend): wire to GET /api/insights/latest?include_failed=true once
 * the backend grows that variant. Until then this component is rendered
 * behind an always-false prop in AIInsightsTab so the visual is ready to
 * go without a live data source.
 *
 * Copy is exact:
 *   Top line:    "Today's auto-run failed at HH:mm UTC — showing yesterday's insights."
 *   Sub-line:    "Last successful run: YYYY-MM-DD HH:mm UTC"
 *   CTAs:        "View error" / "Retry now"  (right-aligned on top line)
 */

const c = tokens.color;
const t = tokens.typography;
const s = tokens.spacing;
const r = tokens.radius;

export interface FailedLatestBannerProps {
  /** ISO8601 of the failed run's failure timestamp. */
  failedAt: string;
  /** ISO8601 of the prior successful run, if any (drives the sub-line). */
  lastSuccessfulAt: string | null;
  /** Click handler for "View error". Opens the failure-reason details. */
  onViewError?: () => void;
  /** Click handler for "Retry now". Triggers a manual run via Run-again flow. */
  onRetry?: () => void;
}

export default function FailedLatestBanner({
  failedAt,
  lastSuccessfulAt,
  onViewError,
  onRetry,
}: FailedLatestBannerProps) {
  const failedHm = formatHourMinUtc(failedAt);
  const lastSuccessful = lastSuccessfulAt ? formatUtcMinute(lastSuccessfulAt) : null;

  return (
    <div
      role="status"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        background: c.bg.warningSubtle,
        border: `1px solid ${c.semantic.warning}`,
        borderRadius: r.md,
        padding: "10px 14px",
        marginBottom: s.s4,
        color: c.semantic.warning,
        fontSize: t.body.fontSize,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: s.s3,
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <AlertTriangle size={14} aria-hidden="true" />
          <span>
            Today's auto-run failed at {failedHm} — showing yesterday's insights.
          </span>
        </span>
        <span style={{ display: "inline-flex", gap: s.s3 }}>
          <button
            type="button"
            onClick={onViewError}
            style={{
              background: "transparent",
              border: "none",
              color: c.semantic.warning,
              fontSize: t.body.fontSize,
              cursor: "pointer",
              textDecoration: "underline",
              padding: 0,
            }}
          >
            View error
          </button>
          <button
            type="button"
            onClick={onRetry}
            style={{
              background: c.bg.surfaceAlt,
              border: `1px solid ${c.semantic.warning}`,
              color: c.semantic.warning,
              borderRadius: r.md,
              padding: "4px 10px",
              fontSize: t.body.fontSize,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry now
          </button>
        </span>
      </div>
      {lastSuccessful ? (
        <div
          // Indented to align with the body of the top line (not under the icon).
          style={{
            marginLeft: 22,
            color: c.text.caption,
            fontSize: t.meta.fontSize,
          }}
        >
          Last successful run: {lastSuccessful}
        </div>
      ) : null}
    </div>
  );
}
