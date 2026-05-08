import type {
  OpenQuestion,
  OpenQuestionMateriality,
  OpenQuestionStatus,
} from "../types";

/**
 * Constants and pure helpers for the tracked-questions sidebar.
 *
 * Lifted out of the component files so each `*.tsx` exports only React
 * components (satisfies `react-refresh/only-export-components`) and so
 * the rank tables / Tailwind class map can be shared without circular
 * imports.
 */

/** Tailwind-class map per docs/ai_insights_v2_sidebar_design.md §6.3. */
export const STATUS_CLASS: Record<OpenQuestionStatus, string> = {
  watching: "text-blue-700 bg-blue-50 border-blue-200",
  confirmed: "text-emerald-700 bg-emerald-50 border-emerald-200",
  disproved: "text-slate-600 bg-slate-100 border-slate-200",
  stale: "text-amber-700 bg-amber-50 border-amber-200",
};

/** Sort rank: watching > confirmed > stale > disproved (§9.1). */
export const STATUS_RANK: Record<OpenQuestionStatus, number> = {
  watching: 0,
  confirmed: 1,
  stale: 2,
  disproved: 3,
};

/** Sort rank: high > medium > low (§9.1). */
export const MATERIALITY_RANK: Record<OpenQuestionMateriality, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

/**
 * Multi-key comparator: status -> materiality -> last_seen_iso desc.
 */
export function compareQuestions(a: OpenQuestion, b: OpenQuestion): number {
  const sd = STATUS_RANK[a.status] - STATUS_RANK[b.status];
  if (sd !== 0) return sd;
  const md = MATERIALITY_RANK[a.materiality] - MATERIALITY_RANK[b.materiality];
  if (md !== 0) return md;
  return Date.parse(b.last_seen_iso) - Date.parse(a.last_seen_iso);
}

/**
 * Format an ISO8601 timestamp as a relative-time string per
 * docs/ai_insights_v2_sidebar_design.md §11.
 */
export function formatRelativeTime(
  iso: string,
  now: Date = new Date(),
): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const deltaSec = Math.max(0, Math.floor((now.getTime() - t) / 1000));
  if (deltaSec < 60) return "just now";
  const deltaMin = Math.floor(deltaSec / 60);
  if (deltaMin < 60) return `${deltaMin}m ago`;
  const deltaHr = Math.floor(deltaMin / 60);
  if (deltaHr < 24) return `${deltaHr}h ago`;
  const deltaDay = Math.floor(deltaHr / 24);
  if (deltaDay < 30) return `${deltaDay}d ago`;
  return iso.slice(0, 10);
}
