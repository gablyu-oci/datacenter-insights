# DESIGN_TOKENS_AUDIT — AI Insights Tab

**Owner:** Product Designer
**Date:** 2026-05-04
**Scope:** OCI tokens audit & mapping for AI Insights tab (W0.8 deliverable)
**Cross-refs:** [`./UX.md`](./UX.md) §U10–U11 · [`./TASKS.md`](./TASKS.md) W0.8 / W7.8 · [`./ARCHITECTURE.md`](./ARCHITECTURE.md) A12 / A15.1
**Audited surfaces:** `frontend/src/index.css`, `frontend/src/App.css`, `frontend/src/components/ChatPanel.tsx` (586 L), `frontend/src/components/layout/{Header,TabNav}.tsx`, `frontend/src/components/shared/{CoverageBadge,ErrorPanel,CitationFooter}.tsx`, `frontend/src/components/tabs/PowerTab.tsx` (header)

> Mapping doc only. No new design proposals beyond the minimum needed to render UX.md elements that have no existing equivalent. Per UX U11 the AI Insights tab **reuses the existing token system desktop-first**; per U11.7 the consolidation lives at `frontend/src/styles/insightTokens.ts` (W7.8). Implementation reads this audit + UX U11 verbatim — no further visual decisions required.

---

## 1. Inventory of existing tokens

The platform has **no centralized token file**. Tokens are inlined hex literals per component. The "system" is the convention that appears across `ChatPanel.tsx`, `PowerTab.tsx`, `Header.tsx`, `TabNav.tsx`, `ErrorPanel.tsx`, `CitationFooter.tsx`. CSS vars in `App.css` (`--accent`, `--border`, etc.) are dead Vite-template artefacts and **not used by any tab** — ignored by this audit.

### 1.1 Color (background / surface)

| Token name (proposed) | Hex | Category | Sample usage location | Reuse for AI Insights? |
|---|---|---|---|---|
| `color.bg.page` | `#0f172a` | color/bg | `index.css` body; `TabNav.tsx` nav bg; `ChatPanel.tsx` panel bg | yes |
| `color.bg.card` | `#1e293b` | color/bg | `PowerTab.tsx::CARD_STYLE.background`; `ErrorPanel.tsx` container; citation pill bg in UX U5.1 | yes |
| `color.bg.surface` | `#0f172a` | color/bg | `ChatPanel.tsx::TOOLTIP_STYLES.contentStyle.background`; tooltip in `CoverageBadge.tsx`; chart frame fill in UX U3.3 | yes (alias of `bg.page`) |
| `color.bg.surfaceAlt` | `#162032` | color/bg | `ChatPanel.tsx` panel header bg | yes |
| `color.bg.gradientHeader` | `linear-gradient(135deg,#0f172a 0%,#1e293b 100%)` | color/bg | `Header.tsx` site header | yes (page header decoration only — not used inside cards) |
| `color.bg.brandGradient` | `linear-gradient(135deg,#3b82f6 0%,#1d4ed8 100%)` | color/bg | `Header.tsx` logo tile | needs-alias (use only on the AI Insights logo glyph if any; not on cards) |

### 1.2 Color (border)

| Token name | Hex | Category | Sample usage | Reuse? |
|---|---|---|---|---|
| `color.border.weak` | `#1e293b` | color/border | `TabNav.tsx` nav bottom; `ChatPanel.tsx` MD `td` border | yes |
| `color.border.default` | `#334155` | color/border | `PowerTab.tsx::CARD_STYLE.border`; `ChatPanel.tsx` panel border, scrollbar-thumb | yes |
| `color.border.strong` | `#475569` | color/border | (used in MD divider patterns; popover border per UX U11.5) | yes |

### 1.3 Color (text)

| Token name | Hex | Category | Sample usage | Reuse? |
|---|---|---|---|---|
| `color.text.primary` | `#ffffff` | color/text | `ChatPanel.tsx` MD strong, send-button text; `Header.tsx` title | yes |
| `color.text.body` | `#e2e8f0` | color/text | `ChatPanel.tsx` MD `td` color | yes |
| `color.text.muted` | `#cbd5e1` | color/text | `ChatPanel.tsx` MD em, legend; `CitationFooter.tsx` source text | yes |
| `color.text.caption` | `#94a3b8` | color/text | `ChatPanel.tsx` axis ticks; `Header.tsx` status; `ErrorPanel.tsx` message | yes |
| `color.text.faint` | `#64748b` | color/text | `ChatPanel.tsx` axis label, ToolTrace; `Header.tsx` subtitle; `CitationFooter.tsx` body | yes — **with U10.3 caveat: ≥12px only** |
| `color.text.deepest` | `#475569` | color/text | `ChatPanel.tsx` Sources eyebrow | yes |

### 1.4 Color (brand / semantic)

| Token name | Hex | Category | Sample usage | Reuse? |
|---|---|---|---|---|
| `color.brand.primary` | `#3b82f6` | color/brand | `TabNav.tsx` active tab; `ChatPanel.tsx` send btn, FAB; `ErrorPanel.tsx` retry btn | yes |
| `color.brand.primaryHover` | `#60a5fa` | color/brand | `TabNav.tsx` dropdown active text; `ChatPanel.tsx` MD `a` | yes |
| `color.brand.primaryDeep` | `#1d4ed8` | color/brand | `Header.tsx` logo gradient tail | yes (decorative only) |
| `color.semantic.success` | `#22c55e` | color/semantic | `Header.tsx` Activity icon | yes |
| `color.semantic.warning` | `#f59e0b` | color/semantic | UX U3.4 conf chips, U8 cancel banner border | yes |
| `color.semantic.danger` | `#ef4444` | color/semantic | `ErrorPanel.tsx` border + icon; `ChatPanel.tsx` Stop btn | yes |
| `color.semantic.info` | `#06b6d4` | color/semantic | `PowerTab.tsx::STATUS_COLOR.Planned`; `chart.categorical[5]` | yes (rare in cards; chart use only) |

### 1.5 Color (chart)

| Token name | Hex | Category | Sample usage | Reuse? |
|---|---|---|---|---|
| `color.chart.brand.microsoft` | `#38BDF8` | color/chart | `PowerTab.tsx::COMPANY_COLORS.Microsoft` | yes |
| `color.chart.brand.amazon` | `#F97316` | color/chart | `PowerTab.tsx::COMPANY_COLORS.Amazon` | yes |
| `color.chart.brand.google` | `#22C55E` | color/chart | `PowerTab.tsx::COMPANY_COLORS.Google` | yes (note: same hex family as `semantic.success` but distinct usage) |
| `color.chart.brand.meta` | `#A78BFA` | color/chart | `PowerTab.tsx::COMPANY_COLORS.Meta` | yes |
| `color.chart.brand.oracle` | `#EF4444` | color/chart | `PowerTab.tsx::COMPANY_COLORS.Oracle` | yes (same hex as `semantic.danger`; legible in chart context) |
| `color.chart.categorical[0..7]` | `#3b82f6,#22c55e,#f59e0b,#ef4444,#8b5cf6,#06b6d4,#ec4899,#a855f7` | color/chart | `ChatPanel.tsx::PIE_COLORS` | yes |
| `color.chart.grid` | `#1e293b` | color/chart | `ChatPanel.tsx::CartesianGrid stroke` | yes |
| `color.chart.axis.tick` | `#94a3b8` | color/chart | `ChatPanel.tsx` XAxis/YAxis tick fill | yes |
| `color.chart.axis.label` | `#64748b` | color/chart | `ChatPanel.tsx` axis labels | yes |
| `color.chart.tooltip.bg` | `#0f172a` | color/chart | `ChatPanel.tsx::TOOLTIP_STYLES` | yes |
| `color.chart.tooltip.border` | `#334155` | color/chart | `ChatPanel.tsx::TOOLTIP_STYLES` | yes |

### 1.6 Spacing / radius / shadow / typography

| Token name | Value | Category | Sample usage | Reuse? |
|---|---|---|---|---|
| `s.0..s.8` | `0,4,8,12,16,20,24,32,48` px | spacing | inline literals across `PowerTab.tsx` (20 padding), `ChatPanel.tsx` (10/14, 16/24 margins), `TabNav.tsx` (12/16) | yes — codify in `insightTokens.ts` |
| `r.sm` | `4` | radius | `Header.tsx` lvl-1 small; not heavily used | yes |
| `r.md` | `6` | radius | `ErrorPanel.tsx` retry btn; `CoverageBadge.tsx` tooltip | yes |
| `r.lg` | `8` | radius | `ChatPanel.tsx::TOOLTIP_STYLES.borderRadius`; `ErrorPanel.tsx` container; `Header.tsx` logo tile | yes |
| `r.xl` | `12` | radius | `PowerTab.tsx::CARD_STYLE.borderRadius`; `ChatPanel.tsx` panel | yes |
| `r.pill` | `999` (or `14` half-height) | radius | `CoverageBadge.tsx` 12px; UX U5.1 specifies 14px full pill | yes |
| `shadow.none` | `none` | shadow | cards (no elevation today) | yes |
| `shadow.fab` | `0 8px 24px rgba(59,130,246,0.4)` | shadow | `ChatPanel.tsx` FAB | yes (FAB only) |
| `shadow.modal` | `0 24px 64px rgba(0,0,0,0.6)` | shadow | `ChatPanel.tsx` expanded panel; `TabNav.tsx` dropdown | yes |
| `shadow.popover` | `0 16px 40px rgba(0,0,0,0.5)` | shadow | `ChatPanel.tsx` floating panel; `CoverageBadge.tsx` tooltip | yes |
| `t.title` | `18 / 600` | typography | UX U3.2 E6 headline (no existing 18-weight-600 today; closest = `Header.tsx` `16/700`) | yes (new size point) |
| `t.subtitle` | `14 / 500` | typography | (gap — none used in cards today) | needs-alias |
| `t.body` | `13 / 400` | typography | `TabNav.tsx` tab label; `ChatPanel.tsx` panel title | yes |
| `t.caption` | `12 / 400` | typography | `Header.tsx` subtitle; `CoverageBadge.tsx` tooltip body | yes |
| `t.meta` | `11 / 400` | typography | `Header.tsx` status; `ErrorPanel.tsx` last-attempt; `CitationFooter.tsx` rows | yes |
| `t.micro` | `10 / 600 uppercase` | typography | `ChatPanel.tsx` Sources eyebrow (`#475569`, ls 0.5, uppercase) | yes |
| `t.mono` | `12 / 400 monospace` | typography | (gap — UX uses for session IDs; today only `<code>` tag in MD) | needs-alias |

### 1.7 Animation

| Token name | Value | Category | Sample usage | Reuse? |
|---|---|---|---|---|
| `motion.transition.color` | `color 0.15s` | motion | `TabNav.tsx` tab transition | yes |
| `motion.transition.bg` | `background 0.1s` | motion | `TabNav.tsx` dropdown row | yes |
| `motion.transition.shadow` | `box-shadow 0.3s` | motion | `App.css` `#next-steps a` | yes |

---

## 2. Gaps — tokens UX.md needs that don't exist today

Audited every UX.md visual element against the inventory. Five gaps. For each, the resolution is either an alias to an existing token or a minimum-viable new token.

| UX.md need | Gap? | Resolution |
|---|---|---|
| Skeleton shimmer (U7.2) | yes | **NEW**: `motion.skeleton.gradient = linear-gradient(90deg,#1e293b 0%,#334155 50%,#1e293b 100%)` + `motion.skeleton.animation = pulse 1.6s ease-in-out infinite`. Reduced-motion fallback = static `#334155`. Uses only existing colors. |
| Streaming caret blink (U7.5, U10.5) | yes | **NEW**: `motion.caret.blink = blink 1s steps(2,start) infinite` (1-bit step animation; no new color — caret uses `color.text.caption` `#94a3b8` "drafting"). Reduced-motion → caret hidden. |
| Cancel-banner warm-amber bg (U8.2) | yes | **NEW**: `color.bg.warningSubtle = #1e1b14`. Single new hex. Used only by the cancel banner; no other surface needs it. (Border + icon reuse `color.semantic.warning #f59e0b`.) |
| Provenance footer divider | no | Map to existing `color.border.weak #1e293b` — same hex `CitationFooter.tsx` already uses for its top divider. |
| Provenance footer subtle bg (skill chip) | no | Map to existing `color.bg.surface #0f172a`. |
| Surveying-banner bg (U7.4) | no | Map to existing `color.bg.surfaceAlt #162032` — same hex `ChatPanel.tsx` header uses. |
| Card focus ring (U3.3) | no | Map to `color.brand.primary #3b82f6` 2px outset + 2px outline-offset. Standard browser pattern; no new token. |
| Streaming-card dashed border (U3.3) | no | Map to existing `color.border.strong #475569`, dashed style. |
| Materiality `[L]` bg (U3.4) | no | Map to existing `#1e3a5f` (ChatPanel discuss-button bg / token form `color.brand.tintDark`). **Note:** `#1e3a5f` is referenced in UX U3.4 but not yet inlined in any code file — it's a derived token; **alias to a new sub-token `color.brand.tintDark = #1e3a5f`** (a single existing-design tint between `#1e293b` and `#1d4ed8`). Treat as one of the five new entries. |
| Confidence-chip translucent border (U3.4) | no | UX specifies `#22c55e44`, `#f59e0b44`, `#94a3b844` — these are existing hex + `0x44` alpha. Pure derivation; no new token. |
| Coverage-badge "full/partial/none" hex set | (deviation) | `CoverageBadge.tsx` uses a saturated palette (`#4ade80 / #fbbf24 / #f87171` on `#052e16 / #451a03 / #450a0a`) **not used in UX.md**. AI Insights does NOT need this badge — it has its own confidence chip palette in U3.4. Out of scope; do not align. |

**Net new tokens for AI Insights:** **3 colors** (`color.bg.warningSubtle`, `color.brand.tintDark`, plus the alpha-44 derivations are not new tokens) + **2 motion** (`motion.skeleton.*`, `motion.caret.blink`). All five fall inside the existing palette family — no new hue introduced.

---

## 3. Mapping table — UX.md element → token

Resolves every UX color reference explicitly. Read top-to-bottom; this is the implementer checklist for "what hex goes where".

| UX element | UX.md ref | Token to use | Hex |
|---|---|---|---|
| Page background | U2.6 implicit | `color.bg.page` | `#0f172a` |
| Insight card background | U3.3 | `color.bg.card` | `#1e293b` |
| Insight card border (default) | U3.3 | `color.border.default` | `#334155` |
| Insight card border (focus) | U3.3 | `color.brand.primary` (2px outset) | `#3b82f6` |
| Insight card border (streaming) | U3.3 | `color.border.strong` (dashed) | `#475569` |
| Insight card radius | U3.3 | `r.xl` | `12px` |
| Card padding | U3.3 | `s.5` | `20px` |
| Card → next-card gap | U3.3 | `s.6` | `24px` |
| Headline color (final) | U3.2 E6 | `color.text.primary` | `#ffffff` |
| Headline color (drafting) | U7.5 | `color.text.caption` | `#94a3b8` |
| Headline type | U3.2 E6 | `t.title` | `18 / 600` |
| Subtitle color | U3.2 E7 | `color.text.muted` | `#cbd5e1` |
| Subtitle type | U3.2 E7 | `t.body` | `13 / 400`, line-height 1.5 |
| Materiality `[L]` bg / border / text | U3.4 | `color.brand.tintDark` / `color.brand.primary` / `color.brand.primaryHover` | `#1e3a5f` / `#3b82f6` / `#60a5fa` |
| Materiality `[M]` bg / border / text | U3.4 | `color.bg.card` / `color.border.strong` / `color.text.muted` | `#1e293b` / `#475569` / `#cbd5e1` |
| Materiality `[S]` bg / border / text | U3.4 | transparent / `color.border.default` / `color.text.caption` | t / `#334155` / `#94a3b8` |
| Confidence `high` (border 44α / text) | U3.4 | `color.semantic.success` (alpha 44) / `color.semantic.success` | `#22c55e44` / `#22c55e` |
| Confidence `med` | U3.4 | `color.semantic.warning` (alpha 44) / `color.semantic.warning` | `#f59e0b44` / `#f59e0b` |
| Confidence `low` | U3.4 | `color.text.caption` (alpha 44) / `color.text.caption` | `#94a3b844` / `#94a3b8` |
| Chart frame bg / border / radius / pad | U3.2 E8 | `color.bg.surface` / `color.border.default` / `r.lg` / `s.3` | `#0f172a` / `#334155` / `8px` / `12px` |
| Chart grid stroke | U4.1 | `color.chart.grid` | `#1e293b` |
| Chart axis tick / axis label | U4.1 | `color.chart.axis.tick` / `color.chart.axis.label` | `#94a3b8` / `#64748b` |
| Chart tooltip bg / border | U4.1 / U4.3 | `color.chart.tooltip.bg` / `color.chart.tooltip.border` | `#0f172a` / `#334155` |
| Chart categorical fill | U4.1 | `color.chart.categorical[i]` | (8-tone array) |
| Chart hyperscaler brand fill | U4.1 | `color.chart.brand.{microsoft,amazon,google,meta,oracle}` | `#38BDF8 / #F97316 / #22C55E / #A78BFA / #EF4444` |
| Figure caption | U3.2 E9 / U4.4 | `color.text.faint` / `t.meta` (≥12px enforce → use `color.text.caption`) | `#94a3b8` / `11 / 400` (per U10.3 caveat: bump faint→caption when <12px) |
| Underlying-data link | U4.4 | `color.brand.primaryHover` | `#60a5fa` |
| Empty/zero-data chart text | U4.5 | `color.text.caption` | `#94a3b8` |
| Provenance footer divider | U3.5 | `color.border.weak` | `#1e293b` |
| Provenance footer collapsed text | U3.5 | `color.text.caption` / `t.meta` | `#94a3b8` / `11 / 400` |
| Skill chip bg / border / text | U3.5 | `color.bg.surface` / `color.border.default` / `color.text.caption` | `#0f172a` / `#334155` / `#94a3b8` |
| Surveying banner bg / border | U7.4 | `color.bg.surfaceAlt` / `color.border.weak` | `#162032` / `#1e293b` |
| Skeleton shimmer | U7.2 | `motion.skeleton.gradient` (NEW) | `linear-gradient(90deg,#1e293b 0%,#334155 50%,#1e293b 100%)` |
| Skeleton reduced-motion | U10.5 | `color.border.default` (static) | `#334155` |
| Streaming caret | U7.5 | `motion.caret.blink` (NEW) on `color.text.caption` | — / `#94a3b8` |
| Error banner (EE2-style) | U8.1 | reuse `ErrorPanel.tsx`: `color.bg.card` + 1px `color.semantic.danger` + 3px left-border `color.semantic.danger` | `#1e293b` + `#ef4444` |
| Cancel banner (EE7) | U8.2 | `color.bg.warningSubtle` (NEW) / `color.semantic.warning` border + icon / `color.text.muted` text | `#1e1b14` / `#f59e0b` / `#cbd5e1` |
| Empty state hero (S1) | U7.3 | `color.bg.card` container, `color.text.primary` heading, `color.text.caption` body, `color.brand.primary` CTA | `#1e293b / #ffffff / #94a3b8 / #3b82f6` |
| Reconnecting toast | U7.1 S7 | `color.bg.card` / `color.text.caption` / `t.meta` | `#1e293b / #94a3b8 / 11 / 400` |
| `[drafting…]` chip | U7.5 | `color.text.caption` italic | `#94a3b8` |
| Hover-card popover | U5.2 | `color.bg.surface` / `color.border.default` / `shadow.popover` / `r.lg` | `#0f172a / #334155 / shadow.popover / 8px` |
| Discuss button (V2) | U3.2 E13 | `color.brand.tintDark` / `color.brand.primaryHover` text | `#1e3a5f / #60a5fa` |
| Stop button | U6.3 | `color.semantic.danger` | `#ef4444` |
| Cursor blink color | U6.5 | inherit current text color (no token) | — |

---

## 4. Component → token-set checklist

For each agentchat primitive (W7.1–W7.4) and each new AIInsightsTab component (W8.x). The list is the exact `insightTokens` import set the file needs. This becomes the frontend implementation checklist (W7.8 / W8 PR review).

### 4.1 agentchat primitives (extracted from `ChatPanel.tsx`)

| Component | Required tokens |
|---|---|
| `agentchat/MarkdownMessage.tsx` | `color.text.primary`, `color.text.muted`, `color.text.caption`, `color.text.body`, `color.bg.surface` (code bg), `color.border.default` (th border), `color.border.weak` (td border), `color.brand.primaryHover` (links), `t.body`, `t.caption`, `t.meta` |
| `agentchat/InsightChart.tsx` | all `color.chart.*` (grid, axis.tick, axis.label, tooltip.bg, tooltip.border, categorical[0..7], brand.{microsoft,amazon,google,meta,oracle}), `r.lg`, `t.meta`, `color.text.muted` (legend), `color.text.caption` (truncation note), `color.brand.primary` (default series fill) |
| `agentchat/ToolTrace.tsx` | `color.text.faint`, `color.text.caption`, `t.meta` |
| `agentchat/CitationList.tsx` | `color.bg.card`, `color.border.default`, `color.text.muted`, `color.text.caption`, `color.text.faint`, `color.text.deepest`, `color.brand.primaryHover`, `t.meta`, `t.micro`, `r.pill` (V2 only) |
| `agentchat/AgentMessage.tsx` | `color.bg.card`, `color.border.default`, `color.text.primary`, `color.text.muted`, `r.lg`, `s.4`, `t.body` |
| `agentchat/chartTheme.ts` | re-exports of all `color.chart.*` only (zero JSX) |

### 4.2 AIInsightsTab components

| Component | Required tokens |
|---|---|
| `tabs/AIInsightsTab.tsx` | `color.bg.page`, `s.6`, `s.7`, `bp.desktop` |
| `insights/InsightCard.tsx` | `color.bg.card`, `color.border.default`, `color.border.strong` (streaming dashed), `color.brand.primary` (focus ring), `r.xl`, `s.3..s.6`, `color.text.primary` (headline), `color.text.muted` (subtitle), `color.text.caption` (drafting headline / index), `t.title`, `t.body`, `t.meta`, `motion.caret.blink` |
| `insights/MaterialityChip.tsx` | `color.brand.tintDark`, `color.brand.primary`, `color.brand.primaryHover`, `color.bg.card`, `color.border.default`, `color.border.strong`, `color.text.muted`, `color.text.caption`, `t.meta`, `r.sm` |
| `insights/ConfidenceChip.tsx` | `color.semantic.success`, `color.semantic.warning`, `color.text.caption` (low) — each used both as full-alpha text and `+44` alpha border, `t.meta`, `r.sm` |
| `insights/InsightChartFrame.tsx` | `color.bg.surface`, `color.border.default`, `r.lg`, `s.3`, `color.text.caption` (caption + empty state), `color.brand.primaryHover` (underlying-data link), `t.meta` |
| `insights/InsightProvenanceFooter.tsx` | `color.border.weak`, `color.text.caption`, `color.text.faint` (collapsed), `color.bg.surface` (skill chip bg), `color.border.default` (skill chip border), `t.meta`, `s.2`, `s.3` |
| `insights/SurveyingBanner.tsx` | `color.bg.surfaceAlt`, `color.border.weak`, `color.text.muted`, `color.text.caption`, `color.brand.primary` (progress bar fill), `r.lg`, `s.4`, `t.body`, `t.meta`, `motion.transition.color` |
| `insights/SkeletonStack.tsx` | `motion.skeleton.gradient`, `motion.skeleton.animation`, `color.border.default` (reduced-motion static), `r.xl` (card), `r.lg` (chart frame), `s.5`, `s.6` |
| `insights/EmptyState.tsx` | `color.bg.card`, `color.border.default`, `color.text.primary`, `color.text.caption`, `color.brand.primary` (CTA bg), `r.xl`, `s.6`, `s.7`, `t.title`, `t.body` |
| `insights/ErrorState.tsx` | reuse existing `shared/ErrorPanel.tsx` directly; **no new tokens consumed** |
| `insights/CancelBanner.tsx` | `color.bg.warningSubtle`, `color.semantic.warning`, `color.text.muted`, `r.lg`, `s.4`, `t.body` |
| `insights/SessionRunner.tsx` | `color.brand.primary` (primary CTA), `color.semantic.danger` (Cancel), `color.text.primary`, `r.md`, `s.3`, `s.4`, `t.body` |
| `insights/ReconnectingToast.tsx` | `color.bg.card`, `color.text.caption`, `r.md`, `shadow.popover`, `t.meta` |
| `insights/InsightCitationsModal.tsx` (V2) | `shadow.modal`, `color.bg.surface`, `color.border.default`, `r.xl`, all `t.*` |

---

## 5. Desktop-first viewport rules (UX U11.6)

Today the platform is **de-facto desktop-only**. Confirmed:

| Source | Breakpoint behaviour |
|---|---|
| `index.css` | No media queries. |
| `App.css` (Vite-template residue) | `@media (max-width: 1024px)` for hero/next-steps only — **not used by any tab**. |
| `Header.tsx` / `TabNav.tsx` / `PowerTab.tsx` / `ChatPanel.tsx` | Zero media queries. Layouts are fixed-pixel: nav uses `padding: 0 24px`, ChatPanel is `width: 420 / height: 600` panel or `min(1200px, 92vw) / min(820px, 88vh)` modal. |
| `ChatPanel.tsx` panel | The `92vw / 88vh` clamp is the only viewport-aware dimension in the app. |

AI Insights match (per U2.3 + U11.6):

| Token | Px | Apply at | AI Insights match |
|---|---|---|---|
| `bp.mobile` | `<900` | best-effort only | does not break layout; no tested mocks |
| `bp.tablet` | `≥900` | best-effort only | does not break layout; no tested mocks |
| `bp.desktop` | `≥1280` | **primary target** | content column max-width `1080`, page max-width `1280`, gutter `s.6` (24px) |
| `bp.wide` | `≥1480` | V2 right rail (not V1) | V1 ignores |

**Resolution: AI Insights V1 ships desktop-first at `≥1280`. Tablet/mobile = best-effort, untested.** Matches U11.6 and ARCH A15.1 D10. No new breakpoint needed.

---

## 6. Deviations from UX.md

| # | Item | Resolution | Rationale |
|---|---|---|---|
| DV-1 | UX U11.5 lists `color.bg.page = #0a1220` as "implicit page bg from existing tabs" | **Audit overrides to `#0f172a`**. | Actual code (`index.css` line 2: `body { background: #0f172a; }`, `TabNav.tsx` nav bg, `ChatPanel.tsx` modal bg) all use `#0f172a`. `#0a1220` does not appear in any audited file. UX.md should be amended; until then this audit is canonical. |
| DV-2 | UX U3.4 references hex `#1e3a5f` for the Discuss button bg + `[L]` materiality bg | **Promote to a named token `color.brand.tintDark`** in `insightTokens.ts`. | The hex appears only in UX.md, not in any current file. It's the only "new" tint required and it sits naturally between `bg.card #1e293b` and `brand.primaryDeep #1d4ed8`. Codifying it once prevents copy-paste drift across MaterialityChip + Discuss + (V2) Subscribe. |
| DV-3 | UX U7.2 / U10.5 prescribes a CSS pulse animation on a 2-stop gradient; today no shimmer pattern exists | **Add `motion.skeleton.*` as new tokens.** | One CSS keyframe + one gradient. Pure additive. No existing component is affected. Reduced-motion fallback uses existing `color.border.default`. |
| DV-4 | UX U8.2 specifies `#1e1b14` warm-amber-tinted dark for the cancel banner | **Add `color.bg.warningSubtle = #1e1b14` as a new token.** | One new hex. Contained to a single component (`CancelBanner.tsx`). Could in theory be aliased to `bg.card` + an amber overlay, but UX explicitly chose a warm-tinted bg to make the banner feel different from a standard card; honour that. |
| DV-5 | UX U7.5 streaming caret animation has no existing equivalent | **Add `motion.caret.blink` as a new token.** | One CSS keyframe. Reduced-motion → token resolves to `none` (caret hidden). No new color. |
| DV-6 | UX U10.3 flags `#64748b` body text on `#1e293b` cards as 3.9:1 (WCAG fail at <18px) | **Document tab-local rule: never use `color.text.faint` for any text smaller than 12px on `bg.card`. Step up to `color.text.caption #94a3b8`.** | Already in UX U10.3. Inherited as a lint-style rule for AI Insights only; platform-wide migration is out of scope for V1 (ratified in TASKS U-tokens). |
| DV-7 | `CoverageBadge.tsx` uses a saturated semantic family (`#4ade80 / #fbbf24 / #f87171` on `#052e16 / #451a03 / #450a0a`) different from UX.md's `#22c55e / #f59e0b / #ef4444` | **AI Insights does NOT use the CoverageBadge palette.** Use the UX U3.4 / U11.5 family. | The badge is a freshness indicator; AI Insights has its own confidence chip semantics. Two palettes coexist; no reconciliation in V1. |
| DV-8 | UX U11.5 names `color.semantic.info = #06b6d4` as "rare, contextual" | No card surface in UX uses it. Reserved for `color.chart.categorical[5]` only. | Not a deviation per se — flagged so the token consumer doesn't try to invent a use. |

---

## Summary

- **File written:** `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/planning/ai-insights/DESIGN_TOKENS_AUDIT.md`
- **Existing tokens reused as-is:** **47** (6 bg, 3 border, 6 text, 4 brand, 4 semantic, 11 chart, 9 spacing, 5 radius, 4 shadow, 5 typography — all sourced from inline literals already in `ChatPanel.tsx`, `PowerTab.tsx`, `Header.tsx`, `TabNav.tsx`, `ErrorPanel.tsx`, `CitationFooter.tsx`, `CoverageBadge.tsx`, `index.css`).
- **New tokens proposed:** **5** — `color.bg.warningSubtle (#1e1b14)`, `color.brand.tintDark (#1e3a5f)`, `motion.skeleton.gradient`, `motion.skeleton.animation`, `motion.caret.blink`. All five are necessary to render UX.md elements that have no current equivalent. No new hue introduced.
- **Open questions:** **3** —
  1. UX U11.5 `#0a1220` vs audited `#0f172a` for `color.bg.page` — recommend amending UX.md to `#0f172a` (DV-1).
  2. Should the platform-wide migration (UX U11.7) ship inside V1 or as a follow-up? Ratified default in TASKS U-tokens = follow-up; confirm no late changes.
  3. Confirm `color.brand.tintDark = #1e3a5f` is the canonical name (DV-2) before W7.8 lands `insightTokens.ts`.
