/**
 * SSE event taxonomy — frontend mirror of ARCHITECTURE.md A5.
 *
 * Each entry represents a single typed `event:` frame the backend emits over
 * `text/event-stream`. The `event` discriminator matches the SSE event-name
 * line; the `data` field carries the JSON payload (already parsed).
 *
 * The wire frame `id: <monotonic>` is captured at the transport layer (see
 * `useInsightStream.ts`); it is not part of the JSON payload itself but is
 * propagated as `event_id` on every dispatched event.
 */

import type { ChartSpec } from "./chartSpec";

export type SSEEventName =
  | "session_started"
  | "surveying"
  | "insight_started"
  | "token"
  | "reasoning_step"
  | "tool_call"
  | "tool_result"
  | "chart"
  | "citation"
  | "insight_complete"
  | "session_complete"
  | "error"
  | "ping"
  // V2 (chat dock + web search instrumentation)
  | "assistant_message_token"
  | "tool_call_started"
  | "tool_call_complete"
  | "message_complete"
  | "web_search_unavailable";

interface BaseEvent<E extends SSEEventName, P> {
  /** SSE event-name line. */
  event: E;
  /** Monotonic id from the `id:` line; used as Last-Event-ID. */
  event_id: string;
  /** Parsed JSON `data:` payload. */
  data: P;
}

export interface SessionStartedPayload {
  session_id: string;
  model: string;
  started_at: string; // ISO8601
  max_insights: number;
}

export interface SurveyingPayload {
  session_id: string;
  candidates_seen: number;
  message: string;
}

export interface InsightStartedPayload {
  insight_id: string;
  session_id: string;
  index: number;
  headline_draft?: string;
}

export interface TokenPayload {
  insight_id: string;
  field: "body" | "headline";
  delta: string;
}

export interface ReasoningStepPayload {
  insight_id: string;
  step: "EDA" | "hypothesize" | "verify" | "emit";
}

export interface ToolCallPayload {
  insight_id: string;
  tool_call_id: string;
  tool_name: string;
  /** <=200 chars, args truncated server-side. */
  args_truncated: string;
  started_at: string;
}

export interface ToolResultPayload {
  tool_call_id: string;
  ok: boolean;
  row_count?: number;
  latency_ms: number;
  error_code?: string;
}

export interface ChartPayload {
  insight_id: string;
  chart: ChartSpec;
}

export interface CitationPayload {
  insight_id: string;
  citation: WebCitation;
}

/** V2 citation shape (matches ARCH A6.7 emit_citation contract). */
export interface WebCitation {
  url: string;
  title: string;
  snippet: string;
  agree_or_disagree: "agree" | "disagree" | "context";
  rationale: string;
  search_query: string;
  retrieved_at?: string;
  provider?: string;
}

export type Confidence = "low" | "medium" | "high";
export type Materiality = "S" | "M" | "L";

export interface InsightCompletePayload {
  insight_id: string;
  headline: string;
  confidence: Confidence;
  materiality: Materiality;
  skills_run: string[];
  low_external_support?: boolean;
}

export interface SessionCompletePayload {
  session_id: string;
  insights_emitted: number;
  duration_ms: number;
  budget_status: "ok" | "clipped";
}

export interface ErrorPayload {
  insight_id?: string;
  code: string;
  message: string;
  retryable: boolean;
}

export type PingPayload = Record<string, never>;

// ── V2 chat-dock event payloads ─────────────────────────────────────────────

export interface AssistantMessageTokenEventData {
  thread_id: string;
  message_id: string;
  delta: string;
}

export interface ToolCallStartedEventData {
  thread_id: string;
  tool_call_id: string;
  tool_name: string;
  /** ≤200 chars, args truncated server-side (mirrors A5 contract). */
  args_truncated: string;
}

export interface ToolCallCompleteEventData {
  thread_id: string;
  tool_call_id: string;
  ok: boolean;
  latency_ms: number;
  error_code?: string;
}

export type ChatFinishReason = "stop" | "length" | "tool_cap" | "error";

export interface MessageCompleteEventData {
  thread_id: string;
  message_id: string;
  finish_reason: ChatFinishReason;
}

export interface WebSearchUnavailableEventData {
  reason: "no_api_key" | "circuit_open" | "rate_limited";
  session_id?: string;
  insight_id?: string;
}

export type InsightSSEEvent =
  | BaseEvent<"session_started", SessionStartedPayload>
  | BaseEvent<"surveying", SurveyingPayload>
  | BaseEvent<"insight_started", InsightStartedPayload>
  | BaseEvent<"token", TokenPayload>
  | BaseEvent<"reasoning_step", ReasoningStepPayload>
  | BaseEvent<"tool_call", ToolCallPayload>
  | BaseEvent<"tool_result", ToolResultPayload>
  | BaseEvent<"chart", ChartPayload>
  | BaseEvent<"citation", CitationPayload>
  | BaseEvent<"insight_complete", InsightCompletePayload>
  | BaseEvent<"session_complete", SessionCompletePayload>
  | BaseEvent<"error", ErrorPayload>
  | BaseEvent<"ping", PingPayload>
  | BaseEvent<"assistant_message_token", AssistantMessageTokenEventData>
  | BaseEvent<"tool_call_started", ToolCallStartedEventData>
  | BaseEvent<"tool_call_complete", ToolCallCompleteEventData>
  | BaseEvent<"message_complete", MessageCompleteEventData>
  | BaseEvent<"web_search_unavailable", WebSearchUnavailableEventData>;

/** Stream-level lifecycle status surfaced to the UI. */
export type StreamStatus =
  | "idle"
  | "connecting"
  | "running"
  | "reconnecting"
  | "complete"
  | "cancelled"
  | "error";
