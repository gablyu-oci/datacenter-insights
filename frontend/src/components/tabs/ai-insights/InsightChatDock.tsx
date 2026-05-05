import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import { Send, Square, X } from "lucide-react";
import { tokens } from "../../../styles/insightTokens";
import {
  MessageList,
  MessageBubble,
  MarkdownRenderer,
  StreamingCaret,
  ToolCallChip,
} from "../../agentchat";
import type {
  AssistantMessageTokenEventData,
  CitationPayload,
  ChartPayload,
  ErrorPayload,
  MessageCompleteEventData,
  ToolCallStartedEventData,
  ToolCallCompleteEventData,
  WebCitation,
  WebSearchUnavailableEventData,
} from "../../../types/sseEvents";
import type { ChartSpec } from "../../../types/chartSpec";
import InsightChart from "./InsightChart";
import CitationPill from "./CitationPill";

/**
 * InsightChatDock — UX §U6. Per-insight slide-down chat dock embedded
 * INSIDE an InsightCard (NOT a separate panel/modal).
 *
 * Streaming contract (per ARCH A5 + §U6.4):
 *   GET  /api/insights/insights/{id}/chat                   → existing thread
 *   POST /api/insights/insights/{id}/chat (SSE response)    → new turn
 *
 * SSE events consumed (V2 chat surface):
 *   - assistant_message_token  → append delta to in-flight bubble body
 *   - tool_call_started        → show ToolCallChip in collapsed state
 *   - tool_call_complete       → update chip with ok/latency
 *   - chart                    → mount inline <InsightChart>
 *   - citation                 → append CitationPill
 *   - message_complete         → finalize bubble; re-enable input
 *   - error                    → render inline error block
 *   - web_search_unavailable   → yellow banner (no API key — citations missing)
 */

const c = tokens.color;
const t = tokens.typography;
const r = tokens.radius;
const s = tokens.spacing;

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const HEADLINE_MAX = 80;
const CONTEXT_TRUNCATE_SUFFIX = "\u2026";
const HISTORY_LIMIT = 50;

const LATENCY_THINKING_MS = 5000;
const LATENCY_LONG_RUN_MS = 30_000;
const LATENCY_TIMEOUT_MS = 45_000;

const SLIDE_MAX_HEIGHT = 720;
const SLIDE_DURATION_MS = 240;

// ── Domain types (UI-only) ──────────────────────────────────────────────────

interface InflightToolCall {
  tool_call_id: string;
  tool_name: string;
  args_truncated: string;
  ok?: boolean;
  latency_ms?: number;
  error_code?: string;
}

interface ChatTurn {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  body: string;
  /** True while assistant tokens are still streaming. */
  streaming: boolean;
  /** True if this turn ended in an error frame. */
  errored: boolean;
  errorMessage?: string;
  toolCalls: InflightToolCall[];
  charts: ChartSpec[];
  citations: WebCitation[];
  startedAt: number;
  /** Set when message_complete fires. */
  finishedAt?: number;
  finishReason?: MessageCompleteEventData["finish_reason"];
}

interface ApiThreadMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  body: string;
  created_at?: string;
  tool_calls?: Array<{
    tool_call_id: string;
    tool_name: string;
    args_truncated: string;
    ok?: boolean;
    latency_ms?: number;
    error_code?: string;
  }>;
  charts?: ChartSpec[];
  citations?: WebCitation[];
}

interface ApiThreadResponse {
  thread_id?: string;
  messages?: ApiThreadMessage[];
}

export interface InsightChatDockProps {
  insightId: string;
  insightHeadline: string;
  isOpen: boolean;
  onClose: () => void;
}

// ── Reduced-motion media-query hook ─────────────────────────────────────────

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    if (mql.addEventListener) mql.addEventListener("change", handler);
    else mql.addListener(handler);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", handler);
      else mql.removeListener(handler);
    };
  }, []);
  return reduced;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function truncateHeadline(s: string): string {
  if (s.length <= HEADLINE_MAX) return s;
  return s.slice(0, HEADLINE_MAX - 1) + CONTEXT_TRUNCATE_SUFFIX;
}

function makeId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

// ── Pulser (3 dots) honoring reduced-motion ────────────────────────────────

function ThreeDotPulser({ reducedMotion }: { reducedMotion: boolean }) {
  const dotStyle: CSSProperties = {
    display: "inline-block",
    width: 4,
    height: 4,
    background: c.text.caption,
    borderRadius: 999,
    marginRight: 3,
  };
  if (reducedMotion) {
    return (
      <span aria-label="generating response" style={{ color: c.text.caption }}>
        <span style={dotStyle} />
        <span style={dotStyle} />
        <span style={dotStyle} />
      </span>
    );
  }
  return (
    <span aria-label="generating response" style={{ color: c.text.caption }}>
      <span
        style={{
          ...dotStyle,
          animation: "insightPulserDot 1.2s ease-in-out infinite",
        }}
      />
      <span
        style={{
          ...dotStyle,
          animation: "insightPulserDot 1.2s ease-in-out 0.2s infinite",
        }}
      />
      <span
        style={{
          ...dotStyle,
          animation: "insightPulserDot 1.2s ease-in-out 0.4s infinite",
        }}
      />
      <style>{`
        @keyframes insightPulserDot {
          0%, 80%, 100% { opacity: 0.25; }
          40% { opacity: 1; }
        }
      `}</style>
    </span>
  );
}

// ── Latency helper text ────────────────────────────────────────────────────

interface LatencyHintProps {
  startedAt: number;
  reducedMotion: boolean;
}

function LatencyHint({ startedAt, reducedMotion }: LatencyHintProps) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const elapsed = now - startedAt;
  if (elapsed < LATENCY_THINKING_MS) return null;

  let text: string;
  if (elapsed >= LATENCY_TIMEOUT_MS) {
    text = "Timed out. Try a more specific follow-up.";
  } else if (elapsed >= LATENCY_LONG_RUN_MS) {
    text = "Still working — long-running tool call";
  } else {
    text = "Thinking";
  }

  const isError = elapsed >= LATENCY_TIMEOUT_MS;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        marginTop: 6,
        color: isError ? c.semantic.danger : c.text.caption,
        fontSize: t.meta.fontSize,
        fontStyle: "italic",
      }}
    >
      {text}
      {!isError && !reducedMotion ? (
        <span aria-hidden="true">
          <DotsAnimated />
        </span>
      ) : !isError ? (
        <span aria-hidden="true">…</span>
      ) : null}
    </div>
  );
}

function DotsAnimated() {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((v) => (v + 1) % 4), 500);
    return () => clearInterval(id);
  }, []);
  return <span>{".".repeat(n)}</span>;
}

// ── SSE parser (POST + ReadableStream) ─────────────────────────────────────

interface ParsedSSEFrame {
  event: string;
  data: string;
  id?: string;
}

function* parseSSEChunks(buffer: string): Generator<ParsedSSEFrame> {
  // SSE frames separated by blank lines. This is a generator over already
  // delimited frames; the caller is responsible for buffering until a
  // double-newline delimiter arrives.
  const frames = buffer.split("\n\n");
  for (const frame of frames) {
    if (!frame.trim()) continue;
    const lines = frame.split("\n");
    let event = "message";
    const dataLines: string[] = [];
    let id: string | undefined;
    for (const ln of lines) {
      if (ln.startsWith("event:")) event = ln.slice(6).trim();
      else if (ln.startsWith("data:")) dataLines.push(ln.slice(5).replace(/^ /, ""));
      else if (ln.startsWith("id:")) id = ln.slice(3).trim();
    }
    yield { event, data: dataLines.join("\n"), id };
  }
}

// ── Component ──────────────────────────────────────────────────────────────

export default function InsightChatDock({
  insightId,
  insightHeadline,
  isOpen,
  onClose,
}: InsightChatDockProps) {
  const reducedMotion = usePrefersReducedMotion();

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [webSearchUnavailable, setWebSearchUnavailable] =
    useState<WebSearchUnavailableEventData | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const dockBodyRef = useRef<HTMLDivElement>(null);

  // 1. Load existing thread when dock first opens.
  useEffect(() => {
    if (!isOpen || historyLoaded) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/insights/insights/${encodeURIComponent(insightId)}/chat`,
          { method: "GET" },
        );
        if (!res.ok) {
          // 404 = no thread yet, that's fine.
          if (res.status !== 404) {
            throw new Error(`GET chat history: ${res.status}`);
          }
          if (!cancelled) {
            setTurns([]);
            setHistoryLoaded(true);
          }
          return;
        }
        const body = (await res.json()) as ApiThreadResponse;
        if (cancelled) return;
        const messages = (body.messages || []).slice(-HISTORY_LIMIT);
        const mapped: ChatTurn[] = messages.map((m) => ({
          id: m.id,
          role: m.role,
          body: m.body,
          streaming: false,
          errored: false,
          toolCalls: (m.tool_calls || []).map((tc) => ({
            tool_call_id: tc.tool_call_id,
            tool_name: tc.tool_name,
            args_truncated: tc.args_truncated,
            ok: tc.ok,
            latency_ms: tc.latency_ms,
            error_code: tc.error_code,
          })),
          charts: m.charts || [],
          citations: m.citations || [],
          startedAt: 0,
          finishedAt: 0,
          finishReason: "stop",
        }));
        setTurns(mapped);
        setHistoryLoaded(true);
      } catch (e) {
        if (cancelled) return;
        setHistoryError(e instanceof Error ? e.message : String(e));
        setHistoryLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isOpen, insightId, historyLoaded]);

  // 2. Stop in-flight stream when the dock unmounts or closes.
  useEffect(() => {
    if (!isOpen && abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setStreaming(false);
    }
  }, [isOpen]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // 3. Esc to close (when dock has focus).
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  // ── Mutators (kept stable across renders) ────────────────────────────────

  const updateAssistantTurn = useCallback(
    (turnId: string, mut: (t: ChatTurn) => ChatTurn) => {
      setTurns((prev) =>
        prev.map((t0) => (t0.id === turnId ? mut(t0) : t0)),
      );
    },
    [],
  );

  // ── Send a message (POST + SSE stream) ───────────────────────────────────

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || streaming) return;

    const userTurn: ChatTurn = {
      id: makeId("user"),
      role: "user",
      body: text,
      streaming: false,
      errored: false,
      toolCalls: [],
      charts: [],
      citations: [],
      startedAt: Date.now(),
    };
    const assistantTurn: ChatTurn = {
      id: makeId("asst"),
      role: "assistant",
      body: "",
      streaming: true,
      errored: false,
      toolCalls: [],
      charts: [],
      citations: [],
      startedAt: Date.now(),
    };
    setTurns((prev) => [...prev, userTurn, assistantTurn]);
    setDraft("");
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    // 45s hard timeout per UX §U6.5.
    const timeoutId = setTimeout(() => {
      controller.abort();
    }, LATENCY_TIMEOUT_MS);

    try {
      const res = await fetch(
        `${API_BASE}/api/insights/insights/${encodeURIComponent(insightId)}/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({ message: text }),
          signal: controller.signal,
        },
      );
      if (!res.ok || !res.body) {
        throw new Error(
          `POST chat failed: ${res.status} ${res.statusText || ""}`.trim(),
        );
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Pull complete frames out of the buffer; keep tail for next read.
        const lastSep = buffer.lastIndexOf("\n\n");
        if (lastSep === -1) continue;
        const ready = buffer.slice(0, lastSep + 2);
        buffer = buffer.slice(lastSep + 2);
        for (const frame of parseSSEChunks(ready)) {
          handleFrame(frame, assistantTurn.id);
        }
      }
      // Flush any trailing frame.
      if (buffer.trim().length > 0) {
        for (const frame of parseSSEChunks(buffer + "\n\n")) {
          handleFrame(frame, assistantTurn.id);
        }
      }
    } catch (e) {
      const aborted =
        e instanceof DOMException && e.name === "AbortError";
      const msg = aborted
        ? "Request cancelled."
        : e instanceof Error
          ? e.message
          : String(e);
      updateAssistantTurn(assistantTurn.id, (t0) => ({
        ...t0,
        streaming: false,
        errored: !aborted,
        errorMessage: aborted ? undefined : msg,
        finishedAt: Date.now(),
        finishReason: "error",
      }));
    } finally {
      clearTimeout(timeoutId);
      abortRef.current = null;
      setStreaming(false);
    }

    function handleFrame(frame: ParsedSSEFrame, turnId: string) {
      let parsed: unknown;
      try {
        parsed = frame.data ? JSON.parse(frame.data) : {};
      } catch {
        return;
      }

      switch (frame.event) {
        case "assistant_message_token": {
          const p = parsed as AssistantMessageTokenEventData;
          updateAssistantTurn(turnId, (t0) => ({
            ...t0,
            body: t0.body + (p.delta || ""),
          }));
          break;
        }
        case "tool_call_started": {
          const p = parsed as ToolCallStartedEventData;
          updateAssistantTurn(turnId, (t0) => ({
            ...t0,
            toolCalls: [
              ...t0.toolCalls,
              {
                tool_call_id: p.tool_call_id,
                tool_name: p.tool_name,
                args_truncated: p.args_truncated,
              },
            ],
          }));
          break;
        }
        case "tool_call_complete": {
          const p = parsed as ToolCallCompleteEventData;
          updateAssistantTurn(turnId, (t0) => ({
            ...t0,
            toolCalls: t0.toolCalls.map((tc) =>
              tc.tool_call_id === p.tool_call_id
                ? {
                    ...tc,
                    ok: p.ok,
                    latency_ms: p.latency_ms,
                    error_code: p.error_code,
                  }
                : tc,
            ),
          }));
          break;
        }
        case "chart": {
          const p = parsed as ChartPayload;
          if (p.chart) {
            updateAssistantTurn(turnId, (t0) => ({
              ...t0,
              charts: [...t0.charts, p.chart],
            }));
          }
          break;
        }
        case "citation": {
          const p = parsed as CitationPayload;
          if (p.citation) {
            updateAssistantTurn(turnId, (t0) => ({
              ...t0,
              citations: [...t0.citations, p.citation],
            }));
          }
          break;
        }
        case "message_complete": {
          const p = parsed as MessageCompleteEventData;
          updateAssistantTurn(turnId, (t0) => ({
            ...t0,
            streaming: false,
            finishedAt: Date.now(),
            finishReason: p.finish_reason,
          }));
          break;
        }
        case "error": {
          const p = parsed as ErrorPayload;
          updateAssistantTurn(turnId, (t0) => ({
            ...t0,
            errored: true,
            errorMessage: p.message || p.code || "Unknown error",
            streaming: false,
            finishedAt: Date.now(),
            finishReason: "error",
          }));
          break;
        }
        case "web_search_unavailable": {
          const p = parsed as WebSearchUnavailableEventData;
          setWebSearchUnavailable(p);
          break;
        }
        case "ping":
        default:
          break;
      }
    }
  }, [draft, streaming, insightId, updateAssistantTurn]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
  }, []);

  const onSubmit = useCallback(
    (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      void send();
    },
    [send],
  );

  // ── Slide-down container styling ─────────────────────────────────────────

  const containerStyle: CSSProperties = useMemo(
    () => ({
      overflow: "hidden",
      maxHeight: isOpen ? SLIDE_MAX_HEIGHT : 0,
      transition: reducedMotion
        ? "none"
        : `max-height ${SLIDE_DURATION_MS}ms ease-out`,
      borderTop: isOpen ? `1px solid ${c.border.default}` : "none",
      marginTop: isOpen ? s.s4 : 0,
    }),
    [isOpen, reducedMotion],
  );

  // Push autoscroll on new messages — pass turns.length+streaming token tick.
  const scrollKey = useMemo(() => {
    let body = 0;
    for (const t0 of turns) body += t0.body.length;
    return `${turns.length}-${body}`;
  }, [turns]);

  // For the latency hint we need the in-flight assistant turn (if any).
  const inflight = streaming
    ? turns.find((t0) => t0.role === "assistant" && t0.streaming) || null
    : null;

  return (
    <section
      ref={dockBodyRef}
      aria-label="discuss this insight"
      aria-hidden={!isOpen}
      style={containerStyle}
    >
      {isOpen ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: s.s3,
            paddingTop: s.s4,
          }}
        >
          <DockHeader onClose={onClose} />
          <PinnedContextChip headline={insightHeadline} />

          {webSearchUnavailable ? (
            <WebSearchBanner data={webSearchUnavailable} />
          ) : null}

          {historyError ? (
            <div
              role="alert"
              style={{
                background: c.bg.warningSubtle,
                border: `1px solid ${c.semantic.warning}`,
                borderRadius: r.md,
                padding: "8px 12px",
                color: c.semantic.warning,
                fontSize: t.meta.fontSize,
              }}
            >
              Couldn&apos;t load thread history: {historyError}
            </div>
          ) : null}

          <div
            style={{
              maxHeight: 400,
              minHeight: 120,
              display: "flex",
              flexDirection: "column",
              background: c.bg.surface,
              border: `1px solid ${c.border.default}`,
              borderRadius: r.lg,
              overflow: "hidden",
            }}
          >
            <MessageList
              scrollKey={scrollKey}
              padding={`${s.s3}px ${s.s3}px`}
              ariaLabel="insight chat messages"
            >
              {turns.length === 0 && historyLoaded ? (
                <EmptyChatHint />
              ) : null}
              {turns.map((turn) => (
                <ChatTurnView
                  key={turn.id}
                  turn={turn}
                  reducedMotion={reducedMotion}
                />
              ))}
              {inflight ? (
                <LatencyHint
                  startedAt={inflight.startedAt}
                  reducedMotion={reducedMotion}
                />
              ) : null}
            </MessageList>
          </div>

          <ChatInput
            value={draft}
            onChange={setDraft}
            streaming={streaming}
            onSubmit={onSubmit}
            onStop={stop}
          />
        </div>
      ) : null}
    </section>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

function DockHeader({ onClose }: { onClose: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            color: c.text.primary,
            fontSize: t.body.fontSize,
            fontWeight: 600,
          }}
        >
          Discuss this insight
        </span>
        <span
          aria-label="scoped to this insight"
          style={{
            display: "inline-flex",
            alignItems: "center",
            height: 20,
            padding: "0 8px",
            background: c.brand.tintDark,
            border: `1px solid ${c.brand.primaryDeep}`,
            color: c.brand.primaryHover,
            borderRadius: r.pill,
            fontSize: 10,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          scoped to this insight
        </span>
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="close discussion"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          background: "transparent",
          border: `1px solid ${c.border.default}`,
          borderRadius: tokens.radius.md,
          color: c.text.muted,
          fontSize: t.meta.fontSize,
          padding: "4px 8px",
          cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        <X size={12} aria-hidden="true" />
        Close
      </button>
    </div>
  );
}

function PinnedContextChip({ headline }: { headline: string }) {
  return (
    <div
      role="note"
      aria-label="pinned insight context"
      style={{
        background: c.bg.surface,
        borderLeft: `3px solid ${c.border.strong}`,
        borderRadius: r.md,
        padding: "8px 12px",
        color: c.text.muted,
        fontSize: 12,
        fontStyle: "italic",
        lineHeight: 1.5,
      }}
    >
      &ldquo;{truncateHeadline(headline)}&rdquo;
    </div>
  );
}

function WebSearchBanner({ data }: { data: WebSearchUnavailableEventData }) {
  const reasonText =
    data.reason === "no_api_key"
      ? "No API key"
      : data.reason === "circuit_open"
        ? "Service circuit open"
        : "Rate limited";
  return (
    <div
      role="status"
      style={{
        background: c.bg.warningSubtle,
        border: `1px solid ${c.semantic.warning}`,
        borderRadius: r.md,
        padding: "8px 12px",
        color: c.semantic.warning,
        fontSize: t.meta.fontSize,
      }}
    >
      {reasonText} — citations may be missing.
    </div>
  );
}

function EmptyChatHint() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        color: c.text.faint,
        fontSize: t.meta.fontSize,
        padding: "8px 4px",
      }}
    >
      <div>No discussion yet for this insight.</div>
      <div style={{ color: c.text.caption }}>
        Try: <em>&ldquo;Why is this divergence emerging now?&rdquo;</em>
      </div>
    </div>
  );
}

function ChatTurnView({
  turn,
  reducedMotion,
}: {
  turn: ChatTurn;
  reducedMotion: boolean;
}) {
  if (turn.role === "user") {
    return (
      <MessageBubble role="user">
        {turn.body}
      </MessageBubble>
    );
  }

  const showPulser = turn.streaming && turn.body.length === 0;
  return (
    <MessageBubble role={turn.role}>
      {turn.toolCalls.length > 0 ? (
        <details
          style={{
            background: "transparent",
            border: "none",
            margin: "0 0 8px 0",
          }}
        >
          <summary
            style={{
              cursor: "pointer",
              fontSize: t.meta.fontSize,
              color: c.text.caption,
              userSelect: "none",
            }}
          >
            Show reasoning ({turn.toolCalls.length}{" "}
            tool call{turn.toolCalls.length === 1 ? "" : "s"})
          </summary>
          <div
            style={{
              marginTop: 6,
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}
          >
            {turn.toolCalls.map((tc) => (
              <ToolCallChip
                key={tc.tool_call_id}
                toolName={tc.tool_name}
                argsPreview={tc.args_truncated}
                resultPreview={tc.error_code ? `error_code: ${tc.error_code}` : undefined}
                latencyMs={tc.latency_ms}
                ok={tc.ok ?? true}
              />
            ))}
          </div>
        </details>
      ) : null}

      {showPulser ? (
        <ThreeDotPulser reducedMotion={reducedMotion} />
      ) : turn.body.length > 0 ? (
        <span>
          <MarkdownRenderer
            content={turn.body}
            style={{ color: c.text.body, fontSize: t.body.fontSize }}
          />
          {turn.streaming ? <StreamingCaret active /> : null}
        </span>
      ) : null}

      {turn.charts.length > 0 ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            marginTop: 8,
          }}
        >
          {turn.charts.map((spec, i) => (
            <div
              key={`${turn.id}-chart-${i}`}
              style={{
                background: c.bg.surface,
                border: `1px solid ${c.border.default}`,
                borderRadius: r.lg,
                padding: s.s3,
              }}
            >
              {spec.title ? (
                <div
                  style={{
                    color: c.text.primary,
                    fontSize: t.caption.fontSize,
                    fontWeight: 600,
                    marginBottom: 4,
                  }}
                >
                  {spec.title}
                </div>
              ) : null}
              <InsightChart spec={spec} />
            </div>
          ))}
        </div>
      ) : null}

      {turn.citations.length > 0 ? (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            marginTop: 8,
          }}
        >
          {turn.citations.map((cit, i) => (
            <CitationPill
              key={`${turn.id}-cit-${i}-${cit.url}`}
              citation={cit}
            />
          ))}
        </div>
      ) : null}

      {turn.errored ? (
        <div
          role="alert"
          style={{
            marginTop: 8,
            color: c.semantic.danger,
            fontSize: t.meta.fontSize,
            background: "transparent",
            border: `1px solid ${c.semantic.danger}`,
            borderRadius: r.md,
            padding: "6px 10px",
          }}
        >
          {turn.errorMessage || "Something went wrong."}
        </div>
      ) : null}
    </MessageBubble>
  );
}

interface ChatInputProps {
  value: string;
  onChange: (v: string) => void;
  streaming: boolean;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onStop: () => void;
}

function ChatInput({
  value,
  onChange,
  streaming,
  onSubmit,
  onStop,
}: ChatInputProps) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  // Auto-resize textarea (cap at ~120px).
  useLayoutEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(120, el.scrollHeight)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !streaming;
  return (
    <form
      onSubmit={onSubmit}
      style={{
        display: "flex",
        alignItems: "flex-end",
        gap: 8,
        background: c.bg.card,
        border: `1px solid ${c.border.default}`,
        borderRadius: r.lg,
        padding: 8,
      }}
    >
      <label htmlFor="insight-chat-input" style={{ position: "absolute", left: -9999 }}>
        Ask a follow-up about this insight
      </label>
      <textarea
        id="insight-chat-input"
        ref={taRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (canSend) {
              const form = (e.target as HTMLTextAreaElement).form;
              if (form) form.requestSubmit();
            }
          }
        }}
        placeholder="Ask a follow-up about this insight…"
        rows={1}
        style={{
          flex: 1,
          background: "transparent",
          border: "none",
          outline: "none",
          resize: "none",
          color: c.text.primary,
          fontFamily: "inherit",
          fontSize: t.body.fontSize,
          lineHeight: 1.5,
          padding: "4px 6px",
          maxHeight: 120,
        }}
      />
      {streaming ? (
        <button
          type="button"
          onClick={onStop}
          aria-label="stop streaming"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            height: 32,
            padding: "0 12px",
            background: c.semantic.danger,
            color: c.text.primary,
            border: "none",
            borderRadius: r.md,
            fontSize: t.body.fontSize,
            fontWeight: 600,
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          <Square size={12} aria-hidden="true" />
          Stop
        </button>
      ) : (
        <button
          type="submit"
          disabled={!canSend}
          aria-label="send message"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            height: 32,
            padding: "0 12px",
            background: canSend ? c.brand.primary : c.border.default,
            color: c.text.primary,
            border: "none",
            borderRadius: r.md,
            fontSize: t.body.fontSize,
            fontWeight: 600,
            cursor: canSend ? "pointer" : "not-allowed",
            fontFamily: "inherit",
          }}
        >
          <Send size={12} aria-hidden="true" />
          Send
        </button>
      )}
    </form>
  );
}
