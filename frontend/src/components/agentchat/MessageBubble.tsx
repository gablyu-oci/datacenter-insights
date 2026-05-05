import type { ReactNode, CSSProperties } from "react";
import { tokens } from "../../styles/insightTokens";

/**
 * MessageBubble — single chat-message bubble with role-based styling.
 *
 * Roles:
 *   - "user"      — right-aligned, brand-tinted bubble.
 *   - "assistant" — left-aligned, card-bg with eyebrow label.
 *   - "tool"      — left-aligned, dimmer text, mono font; raw tool transcript.
 *   - "system"    — full-width amber-bordered banner.
 *
 * The bubble is presentation-only — content (markdown, charts, citations)
 * is composed by the caller as `children`. This keeps the primitive
 * standalone (no dep on ChatPanel-internal state, per W7.1 brief).
 */

const c = tokens.color;
const r = tokens.radius;
const t = tokens.typography;

export type MessageRole = "user" | "assistant" | "tool" | "system";

export interface MessageBubbleProps {
  role: MessageRole;
  children: ReactNode;
  /** Eyebrow label (e.g. "Analyst", "tool"). Auto-derived from role if absent. */
  eyebrow?: string;
  /** Footer slot, e.g. timestamps. */
  footer?: ReactNode;
  /** Override bubble width. Default: 95% of parent. */
  maxWidth?: string | number;
  style?: CSSProperties;
}

function roleEyebrow(role: MessageRole): string | null {
  switch (role) {
    case "assistant":
      return "Analyst";
    case "tool":
      return "Tool";
    case "system":
      return "System";
    default:
      return null;
  }
}

export default function MessageBubble({
  role,
  children,
  eyebrow,
  footer,
  maxWidth,
  style,
}: MessageBubbleProps) {
  const computedEyebrow = eyebrow ?? roleEyebrow(role);

  if (role === "user") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", ...style }}>
        <div
          style={{
            maxWidth: maxWidth ?? "85%",
            background: c.brand.tintDark,
            border: `1px solid ${c.brand.primaryDeep}`,
            borderRadius: r.lg,
            padding: "8px 12px",
            color: c.text.primary,
            fontSize: t.body.fontSize,
            whiteSpace: "pre-wrap",
            lineHeight: 1.5,
          }}
        >
          {children}
        </div>
      </div>
    );
  }

  if (role === "system") {
    return (
      <div
        role="status"
        style={{
          width: "100%",
          background: c.bg.warningSubtle,
          border: `1px solid ${c.semantic.warning}`,
          borderRadius: r.lg,
          padding: "10px 14px",
          color: c.text.muted,
          fontSize: t.body.fontSize,
          ...style,
        }}
      >
        {children}
      </div>
    );
  }

  const isTool = role === "tool";
  return (
    <div style={{ display: "flex", justifyContent: "flex-start", ...style }}>
      <div
        style={{
          maxWidth: maxWidth ?? "95%",
          width: "100%",
          background: c.bg.card,
          border: `1px solid ${c.border.default}`,
          borderRadius: r.lg,
          padding: "10px 12px",
          fontFamily: isTool ? t.mono.fontFamily : undefined,
        }}
      >
        {computedEyebrow ? (
          <div
            style={{
              color: c.text.deepest,
              fontSize: t.micro.fontSize,
              fontWeight: t.micro.fontWeight,
              letterSpacing: t.micro.letterSpacing,
              textTransform: t.micro.textTransform,
              marginBottom: 6,
            }}
          >
            {computedEyebrow}
          </div>
        ) : null}
        <div
          style={{
            color: isTool ? c.text.caption : c.text.body,
            fontSize: t.body.fontSize,
            lineHeight: 1.55,
          }}
        >
          {children}
        </div>
        {footer ? <div style={{ marginTop: 8 }}>{footer}</div> : null}
      </div>
    </div>
  );
}
