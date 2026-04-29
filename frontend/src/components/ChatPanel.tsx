import { useState, useRef, useEffect, KeyboardEvent } from "react";

type Role = "user" | "assistant";
interface Message {
  role: Role;
  content: string;
}

const PANEL_BG = "#1e293b";
const PANEL_BORDER = "#334155";

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, streaming]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || streaming) return;

    setError(null);
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";

    const userMsg: Message = { role: "user", content: trimmed };
    // Append user message + a placeholder assistant message we will fill via stream.
    setMessages((prev) => [...prev, userMsg, { role: "assistant", content: "" }]);
    setStreaming(true);

    try {
      const response = await fetch("/api/agent/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`Request failed (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;

      while (!done) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;
        if (value) {
          buffer += decoder.decode(value, { stream: !done });
          // Split on newlines; SSE frames are line-based.
          let newlineIdx = buffer.indexOf("\n");
          while (newlineIdx !== -1) {
            const line = buffer.slice(0, newlineIdx).trimEnd();
            buffer = buffer.slice(newlineIdx + 1);
            if (line.startsWith("data: ")) {
              const payload = line.slice(6);
              if (payload === "[DONE]") {
                done = true;
                break;
              }
              const decoded = payload.replace(/\\n/g, "\n");
              setMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last && last.role === "assistant") {
                  next[next.length - 1] = { role: "assistant", content: last.content + decoded };
                }
                return next;
              });
            }
            newlineIdx = buffer.indexOf("\n");
          }
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      // Remove the empty assistant placeholder if it never received content.
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "assistant" && last.content === "") {
          next.pop();
        }
        return next;
      });
    } finally {
      setStreaming(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    const lineHeight = 20;
    const maxHeight = lineHeight * 3 + 16;
    ta.style.height = Math.min(ta.scrollHeight, maxHeight) + "px";
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        aria-label="Ask analyst"
        style={{
          position: "fixed",
          right: 24,
          bottom: 24,
          zIndex: 1000,
          background: "#3b82f6",
          color: "white",
          border: "none",
          borderRadius: 999,
          padding: "12px 18px",
          fontSize: 14,
          fontWeight: 600,
          cursor: "pointer",
          boxShadow: "0 6px 24px rgba(0,0,0,0.4)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span aria-hidden="true">{"\u{1F4AC}"}</span>
        <span>Ask analyst</span>
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="Datacenter Q&A"
      style={{
        position: "fixed",
        right: 24,
        bottom: 24,
        zIndex: 1000,
        width: 380,
        height: 520,
        background: PANEL_BG,
        border: `1px solid ${PANEL_BORDER}`,
        borderRadius: 12,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 14px",
          borderBottom: `1px solid ${PANEL_BORDER}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "#0f172a",
        }}
      >
        <div style={{ color: "white", fontWeight: 600, fontSize: 14 }}>Datacenter Q&amp;A</div>
        <button
          onClick={() => setOpen(false)}
          aria-label="Close chat"
          style={{
            background: "transparent",
            border: "none",
            color: "#94a3b8",
            fontSize: 20,
            cursor: "pointer",
            lineHeight: 1,
            padding: "0 4px",
          }}
        >
          {"\u00D7"}
        </button>
      </div>

      {/* Message list */}
      <div
        ref={listRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 14px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {messages.length === 0 && (
          <div style={{ color: "#64748b", fontSize: 12, textAlign: "center", marginTop: 30 }}>
            Ask about contracted GW, GPU deployments, permits, or cross-pillar signals.
          </div>
        )}
        {messages.map((m, i) => {
          const isAssistant = m.role === "assistant";
          const isLast = i === messages.length - 1;
          const showTyping = isAssistant && isLast && streaming && m.content === "";
          return (
            <div
              key={i}
              style={{
                color: isAssistant ? "white" : "#38bdf8",
                fontSize: 13,
                lineHeight: 1.5,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              <div
                style={{
                  color: "#64748b",
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  marginBottom: 2,
                  letterSpacing: 0.5,
                }}
              >
                {isAssistant ? "Analyst" : "You"}
              </div>
              {showTyping ? <span style={{ color: "#94a3b8" }}>...</span> : m.content}
            </div>
          );
        })}
        {error && (
          <div
            style={{
              color: "#ef4444",
              fontStyle: "italic",
              fontSize: 12,
            }}
          >
            {error}
          </div>
        )}
      </div>

      {/* Input row */}
      <div
        style={{
          padding: 10,
          borderTop: `1px solid ${PANEL_BORDER}`,
          display: "flex",
          gap: 8,
          alignItems: "flex-end",
          background: "#0f172a",
        }}
      >
        <textarea
          ref={taRef}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder="Ask a question..."
          aria-label="Question"
          disabled={streaming}
          style={{
            flex: 1,
            resize: "none",
            background: "#1e293b",
            border: `1px solid ${PANEL_BORDER}`,
            borderRadius: 6,
            color: "white",
            fontSize: 13,
            padding: "8px 10px",
            fontFamily: "inherit",
            outline: "none",
            lineHeight: "20px",
            maxHeight: 76,
          }}
        />
        <button
          onClick={handleSend}
          disabled={streaming || !input.trim()}
          aria-label="Send message"
          style={{
            background: streaming || !input.trim() ? "#334155" : "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "8px 14px",
            fontSize: 13,
            fontWeight: 600,
            cursor: streaming || !input.trim() ? "not-allowed" : "pointer",
            height: 36,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
