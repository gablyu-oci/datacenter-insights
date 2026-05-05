import { tokens } from "../../../styles/insightTokens";

/**
 * SkeletonStack — three skeleton cards with a shimmer pulse.
 *
 * The shimmer is a CSS keyframe inlined in a <style> tag (no framer-motion
 * dependency). Reduced-motion users see a static `#334155` block per
 * UX U10.5 / DESIGN_TOKENS_AUDIT motion table.
 */

const c = tokens.color;
const s = tokens.spacing;
const r = tokens.radius;

const KEYFRAMES = `
@keyframes insightShimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.insight-shimmer-line {
  background: ${tokens.motion.skeletonGradient};
  background-size: 200% 100%;
  animation: ${tokens.motion.skeletonAnimation};
  border-radius: 4px;
}
.insight-shimmer-frame {
  background: ${tokens.motion.skeletonGradient};
  background-size: 200% 100%;
  animation: ${tokens.motion.skeletonAnimation};
  border-radius: ${r.lg}px;
}
@media (prefers-reduced-motion: reduce) {
  .insight-shimmer-line, .insight-shimmer-frame {
    background: ${c.border.default} !important;
    animation: none !important;
  }
}
`;

export interface SkeletonStackProps {
  count?: number;
  /** Optional starting card index for the "Insight N of …" label. */
  startIndex?: number;
  /** Total expected, drives the "of N" label. */
  total?: number;
}

export default function SkeletonStack({ count = 3, startIndex = 0, total }: SkeletonStackProps) {
  const items = Array.from({ length: count }, (_, i) => i + startIndex);
  return (
    <>
      <style>{KEYFRAMES}</style>
      <div style={{ display: "flex", flexDirection: "column", gap: s.s6 }} aria-hidden="true">
        {items.map((i) => (
          <SkeletonCard key={i} index={i} total={total} />
        ))}
      </div>
    </>
  );
}

function SkeletonCard({ index, total }: { index: number; total?: number }) {
  return (
    <div
      style={{
        background: c.bg.card,
        border: `1px dashed ${c.border.strong}`,
        borderRadius: r.xl,
        padding: s.s5,
        display: "flex",
        flexDirection: "column",
        gap: s.s3,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          color: c.text.faint,
          fontSize: tokens.typography.meta.fontSize,
        }}
      >
        <span>Insight {index + 1}{total ? ` of ${total}` : ""}</span>
        <span>drafting…</span>
      </div>
      <div className="insight-shimmer-line" style={{ height: 18, width: "80%" }} />
      <div className="insight-shimmer-line" style={{ height: 12, width: "60%" }} />
      <div className="insight-shimmer-frame" style={{ height: 220, width: "100%" }} />
      <div className="insight-shimmer-line" style={{ height: 10, width: "40%" }} />
      <div style={{ display: "flex", gap: 8 }}>
        <div className="insight-shimmer-line" style={{ height: 12, width: 80 }} />
        <div className="insight-shimmer-line" style={{ height: 12, width: 60 }} />
        <div className="insight-shimmer-line" style={{ height: 12, width: 70 }} />
      </div>
    </div>
  );
}
