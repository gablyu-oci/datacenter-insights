/**
 * insightTokens.ts — minimal token reuse module per DESIGN_TOKENS_AUDIT.md.
 *
 * Centralises every hex/value referenced by the new agentchat/* and AI
 * Insights tab components. Anything not present here is either a deliberate
 * deviation (with a `// TODO design-token` comment near the call site) or a
 * gap to be filed back in the audit.
 *
 * The values are mirror copies of inlined literals already used across
 * `ChatPanel.tsx`, `PowerTab.tsx`, `Header.tsx`, `TabNav.tsx`,
 * `ErrorPanel.tsx`, `CitationFooter.tsx` (per the audit, §1).
 *
 * Five new tokens (audit §2) — `bg.warningSubtle`, `brand.tintDark`,
 * `motion.skeleton.gradient`, `motion.skeleton.animation`,
 * `motion.caret.blink` — exist only here.
 */

export const tokens = {
  color: {
    bg: {
      page: "#0f172a",
      card: "#1e293b",
      surface: "#0f172a",
      surfaceAlt: "#162032",
      warningSubtle: "#1e1b14", // NEW per audit DV-4
    },
    border: {
      weak: "#1e293b",
      default: "#334155",
      strong: "#475569",
    },
    text: {
      primary: "#ffffff",
      body: "#e2e8f0",
      muted: "#cbd5e1",
      caption: "#94a3b8",
      faint: "#64748b",
      deepest: "#475569",
    },
    brand: {
      primary: "#3b82f6",
      primaryHover: "#60a5fa",
      primaryDeep: "#1d4ed8",
      tintDark: "#1e3a5f", // NEW per audit DV-2
    },
    semantic: {
      success: "#22c55e",
      warning: "#f59e0b",
      danger: "#ef4444",
      info: "#06b6d4",
    },
    chart: {
      grid: "#1e293b",
      axisTick: "#94a3b8",
      axisLabel: "#64748b",
      tooltipBg: "#0f172a",
      tooltipBorder: "#334155",
      categorical: [
        "#3b82f6",
        "#22c55e",
        "#f59e0b",
        "#ef4444",
        "#8b5cf6",
        "#06b6d4",
        "#ec4899",
        "#a855f7",
      ],
      brandHyperscaler: {
        microsoft: "#38BDF8",
        amazon: "#F97316",
        google: "#22C55E",
        meta: "#A78BFA",
        oracle: "#EF4444",
      },
    },
  },
  radius: {
    sm: 4,
    md: 6,
    lg: 8,
    xl: 12,
    pill: 999,
  },
  spacing: {
    s0: 0,
    s1: 4,
    s2: 8,
    s3: 12,
    s4: 16,
    s5: 20,
    s6: 24,
    s7: 32,
    s8: 48,
  },
  typography: {
    title: { fontSize: 18, fontWeight: 600, lineHeight: 1.35 },
    subtitle: { fontSize: 14, fontWeight: 500, lineHeight: 1.5 },
    body: { fontSize: 13, fontWeight: 400, lineHeight: 1.55 },
    caption: { fontSize: 12, fontWeight: 400 },
    meta: { fontSize: 11, fontWeight: 400 },
    micro: { fontSize: 10, fontWeight: 600, letterSpacing: 0.5, textTransform: "uppercase" as const },
    mono: { fontSize: 12, fontWeight: 400, fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace" },
  },
  shadow: {
    none: "none",
    fab: "0 8px 24px rgba(59,130,246,0.4)",
    modal: "0 24px 64px rgba(0,0,0,0.6)",
    popover: "0 16px 40px rgba(0,0,0,0.5)",
  },
  motion: {
    transitionColor: "color 0.15s",
    transitionBg: "background 0.1s",
    transitionShadow: "box-shadow 0.3s",
    skeletonGradient:
      "linear-gradient(90deg, #1e293b 0%, #334155 50%, #1e293b 100%)",
    skeletonAnimation: "insightShimmer 1.6s ease-in-out infinite",
    caretBlink: "insightCaretBlink 1s steps(2, start) infinite",
  },
} as const;

export type InsightTokens = typeof tokens;
