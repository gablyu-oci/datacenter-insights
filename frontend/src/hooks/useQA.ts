import { useCallback, useRef, useState } from "react";
import type { QAEvent, QAMessage } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

/**
 * useQA — drives the /api/qa/ask streaming endpoint.
 *
 * The backend emits SSE-style frames: `data: <json>\n\n` where the JSON has a
 * discriminator `type` field. We accumulate text into the trailing assistant
 * message and append charts / citations / tool-call traces as they arrive.
 */
export function useQA() {
  const [messages, setMessages] = useState<QAMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const updateLastAssistant = useCallback(
    (mutator: (m: QAMessage) => QAMessage) => {
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.slice();
        for (let i = next.length - 1; i >= 0; i--) {
          if (next[i].role === "assistant") {
            next[i] = mutator(next[i]);
            return next;
          }
        }
        return next;
      });
    },
    [],
  );

  const dispatch = useCallback(
    (evt: QAEvent) => {
      switch (evt.type) {
        case "text_chunk": {
          updateLastAssistant((m) => ({
            ...m,
            content: (m.content || "") + (evt.content ?? ""),
          }));
          break;
        }
        case "tool_call": {
          updateLastAssistant((m) => ({
            ...m,
            toolCalls: [
              ...(m.toolCalls || []),
              { tool_name: evt.tool_name, args: evt.args },
            ],
          }));
          break;
        }
        case "tool_result": {
          updateLastAssistant((m) => {
            const calls = [...(m.toolCalls || [])];
            // Find the most recent matching tool_call without a row_count yet.
            for (let i = calls.length - 1; i >= 0; i--) {
              if (
                calls[i].tool_name === evt.tool_name &&
                calls[i].row_count === undefined
              ) {
                calls[i] = { ...calls[i], row_count: evt.row_count };
                return { ...m, toolCalls: calls };
              }
            }
            // No pending call to enrich — push a synthetic entry.
            calls.push({
              tool_name: evt.tool_name,
              args: {},
              row_count: evt.row_count,
            });
            return { ...m, toolCalls: calls };
          });
          break;
        }
        case "chart_spec": {
          updateLastAssistant((m) => ({
            ...m,
            charts: [
              ...(m.charts || []),
              {
                chart_type: evt.chart_type,
                x: evt.x,
                y: evt.y,
                series: evt.series,
                title: evt.title,
                source_table: evt.source_table,
                breakdown_by: evt.breakdown_by ?? null,
                reasoning: evt.reasoning ?? null,
              },
            ],
          }));
          break;
        }
        case "citation": {
          updateLastAssistant((m) => ({
            ...m,
            citations: [
              ...(m.citations || []),
              {
                table: evt.table,
                row_id: evt.row_id,
                source_url: evt.source_url,
                label: evt.label,
              },
            ],
          }));
          break;
        }
        case "error": {
          updateLastAssistant((m) => ({ ...m, error: evt.message }));
          break;
        }
        case "done":
        default:
          break;
      }
    },
    [updateLastAssistant],
  );

  const ask = useCallback(
    async (q: string) => {
      const question = q.trim();
      if (!question) return;

      // Snapshot prior turns for the request body — the agent uses history
      // to resolve follow-up questions like "show me the company distribution"
      // that depend on the previous turn's scope.
      const historySnapshot = messages
        .filter((m) => m.content && m.content.trim().length > 0)
        .slice(-8)  // cap to last 8 turns to keep payload reasonable
        .map((m) => ({ role: m.role, content: m.content }));

      // Push user message + empty assistant stub.
      setMessages((prev) => [
        ...prev,
        { role: "user", content: question },
        {
          role: "assistant",
          content: "",
          charts: [],
          citations: [],
          toolCalls: [],
        },
      ]);

      setStreaming(true);
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        const resp = await fetch(`${API_BASE}/api/qa/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, history: historySnapshot }),
          signal: ctrl.signal,
        });

        if (!resp.ok || !resp.body) {
          throw new Error(`Request failed (${resp.status})`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let finished = false;

        while (!finished) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let nl = buffer.indexOf("\n");
          while (nl !== -1) {
            const line = buffer.slice(0, nl).trimEnd();
            buffer = buffer.slice(nl + 1);
            if (line.startsWith("data: ")) {
              const payload = line.slice(6);
              if (payload === "[DONE]") {
                finished = true;
                break;
              }
              try {
                const evt = JSON.parse(payload) as QAEvent;
                dispatch(evt);
                if (evt.type === "done") {
                  finished = true;
                  break;
                }
              } catch {
                // ignore unparseable frames
              }
            }
            nl = buffer.indexOf("\n");
          }
        }
      } catch (e) {
        if ((e as { name?: string })?.name === "AbortError") {
          // user-initiated stop — leave existing assistant content as-is
        } else {
          const msg = e instanceof Error ? e.message : String(e);
          updateLastAssistant((m) => ({ ...m, error: msg }));
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [dispatch, updateLastAssistant, messages],
  );

  const stop = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setStreaming(false);
  }, []);

  const clear = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setMessages([]);
    setStreaming(false);
  }, []);

  return { messages, ask, stop, clear, streaming };
}
