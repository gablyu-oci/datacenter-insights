/**
 * Shared types for the AI Insights tab Phase D additions.
 *
 * `OpenQuestion` is the wire shape returned by GET /api/insights/open-questions.
 * The route reads `.openclaw/workspace/MEMORY.md` and emits one item per
 * tracked-question bullet, see backend/routers/insights.py and
 * docs/ai_insights_v2_spec.md §4.4.
 */

export type OpenQuestionStatus =
  | "watching"
  | "confirmed"
  | "disproved"
  | "stale";

export type OpenQuestionMateriality = "low" | "medium" | "high";

export interface OpenQuestion {
  id: string;
  status: OpenQuestionStatus;
  materiality: OpenQuestionMateriality;
  latest_note: string;
  last_seen_iso: string;
}
