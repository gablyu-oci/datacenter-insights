import type { CSSProperties } from "react";
import { tokens } from "../../styles/insightTokens";

/**
 * StreamingCaret — blinking caret rendered while a token stream is in
 * flight. Uses a pure CSS `steps()` animation so we don't pull in
 * framer-motion or any other animation lib.
 *
 * The keyframe (`insightCaretBlink`) is registered once via an inline
 * `<style>` tag the first time the component mounts. Reduced-motion users
 * see a static (always-visible) caret per UX U10.5.
 */

const c = tokens.color;

const KEYFRAME_STYLE = `
@keyframes insightCaretBlink {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .insight-caret { animation: none !important; opacity: 1 !important; }
}
`;

export interface StreamingCaretProps {
  /** Render-or-not toggle, controlled by the stream state. */
  active?: boolean;
  /** Override default color (`color.text.caption`). */
  color?: string;
  /** Caret height in px; defaults to 1em-ish via `currentSize`. */
  height?: number;
  style?: CSSProperties;
  ariaLabel?: string;
}

export default function StreamingCaret({
  active = true,
  color,
  height,
  style,
  ariaLabel = "streaming",
}: StreamingCaretProps) {
  if (!active) return null;
  const caretColor = color ?? c.text.caption;
  return (
    <>
      <style>{KEYFRAME_STYLE}</style>
      <span
        className="insight-caret"
        aria-label={ariaLabel}
        role="status"
        style={{
          display: "inline-block",
          width: 2,
          height: height ?? "1em",
          background: caretColor,
          marginLeft: 2,
          verticalAlign: "text-bottom",
          animation: tokens.motion.caretBlink,
          ...style,
        }}
      />
    </>
  );
}
