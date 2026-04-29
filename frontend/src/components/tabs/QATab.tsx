import { useState, useRef, useEffect } from "react";
import type { KeyboardEvent } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
  LineChart, Line,
  ScatterChart, Scatter, ZAxis,
} from "recharts";
import { MessageSquare, Send, Square, Trash2, ExternalLink, ChevronDown, ChevronUp } from "lucide-react";
import { useQA } from "../../hooks/useQA";
import type { ChartSpec, Citation, QAMessage } from "../../types";

const CARD_STYLE = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: "12px",
  padding: "20px",
};

const TOOLTIP_STYLES = {
  contentStyle: { background: "#0f172a", border: "1px solid #334155", borderRadius: 8 },
  labelStyle: { color: "white" },
  itemStyle: { color: "#94a3b8" },
};

const PIE_COLORS = ["#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6","#06b6d4","#ec4899","#a855f7"];

const SUGGESTED = [
  "How much MW does Microsoft have in Virginia?",
  "Show me total MW by provider for top 5 hyperscalers",
  "Which states have the most generator permits?",
  "Compare AWS vs Microsoft datacenter announcements 2024-2026",
  "What's our generator-permit coverage by state?",
];

function ChartRenderer({ spec }: { spec: ChartSpec }) {
  const data = (spec.series || []).map((s) => ({ x: String(s.x), y: Number(s.y) }));
  if (spec.chart_type === "table") {
    return (
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155" }}>
              <th style={{ color: "#94a3b8", textAlign: "left", padding: "6px 8px" }}>{spec.x}</th>
              <th style={{ color: "#94a3b8", textAlign: "right", padding: "6px 8px" }}>{spec.y}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                <td style={{ color: "white", padding: "6px 8px" }}>{r.x}</td>
                <td style={{ color: "white", padding: "6px 8px", textAlign: "right" }}>{r.y.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (spec.chart_type === "pie") {
    return (
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={data} dataKey="y" nameKey="x" outerRadius={90} label={({ x }) => x}>
            {data.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
          </Pie>
          <Tooltip {...TOOLTIP_STYLES} />
        </PieChart>
      </ResponsiveContainer>
    );
  }
  if (spec.chart_type === "line") {
    return (
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="x" tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <Tooltip {...TOOLTIP_STYLES} />
          <Line type="monotone" dataKey="y" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
        </LineChart>
      </ResponsiveContainer>
    );
  }
  if (spec.chart_type === "scatter") {
    const scatterData = (spec.series || []).map((s) => ({
      x: Number(s.x),
      y: Number(s.y),
    }));
    return (
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis type="number" dataKey="x" name={spec.x} tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <YAxis type="number" dataKey="y" name={String(spec.y)} tick={{ fill: "#94a3b8", fontSize: 11 }} />
          <ZAxis range={[60, 60]} />
          <Tooltip {...TOOLTIP_STYLES} cursor={{ strokeDasharray: "3 3" }} />
          <Scatter data={scatterData} fill="#3b82f6" />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }
  // default: bar
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="x" tick={{ fill: "#94a3b8", fontSize: 11 }} />
        <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
        <Tooltip {...TOOLTIP_STYLES} cursor={{ fill: "#ffffff10" }} />
        <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
        <Bar dataKey="y" fill="#3b82f6" name={spec.y} radius={[4,4,0,0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function ToolTrace({ calls }: { calls: NonNullable<QAMessage["toolCalls"]> }) {
  const [open, setOpen] = useState(false);
  if (!calls || calls.length === 0) return null;
  return (
    <div style={{ marginTop: 8, fontSize: 11, color: "#64748b" }}>
      <button onClick={() => setOpen(o => !o)} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 4, padding: 0, fontSize: 11 }}>
        {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        {calls.length} tool call{calls.length === 1 ? "" : "s"}
      </button>
      {open && (
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          {calls.map((c, i) => (
            <li key={i} style={{ marginBottom: 2 }}>
              <code style={{ color: "#94a3b8" }}>{c.tool_name}</code>
              {typeof c.row_count === "number" && <span> -- {c.row_count} rows</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CitationList({ items }: { items: Citation[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid #334155" }}>
      <div style={{ color: "#475569", fontSize: 10, fontWeight: 600, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 4 }}>Sources</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {items.map((c, i) => (
          <div key={i} style={{ fontSize: 11, color: "#94a3b8" }}>
            <span style={{ color: "#64748b" }}>[{c.table}#{c.row_id ?? "?"}]</span>{" "}
            <span style={{ color: "#cbd5e1" }}>{c.label}</span>{" "}
            {c.source_url && (
              <a href={c.source_url} target="_blank" rel="noreferrer" style={{ color: "#60a5fa", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 3 }}>
                <ExternalLink size={9} /> link
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function QATab() {
  const { messages, ask, stop, clear, streaming } = useQA();
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, streaming]);

  const handleSubmit = () => {
    const q = input.trim();
    if (!q || streaming) return;
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
    ask(q);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 110px)", padding: "20px 24px 16px", gap: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <MessageSquare size={20} color="#3b82f6" />
          <div>
            <h2 style={{ color: "white", fontSize: 18, fontWeight: 600, margin: 0 }}>Datacenter Q&amp;A</h2>
            <div style={{ color: "#64748b", fontSize: 12 }}>Ask questions about the live datacenter, power, permit, and EDGAR data</div>
          </div>
        </div>
        <button onClick={clear} disabled={streaming || messages.length === 0} style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          background: "#0f172a", border: "1px solid #334155", borderRadius: 6, color: "#94a3b8",
          padding: "6px 12px", fontSize: 12, cursor: streaming || messages.length === 0 ? "not-allowed" : "pointer",
        }}>
          <Trash2 size={12} /> Clear
        </button>
      </div>

      {/* Messages */}
      <div ref={listRef} style={{ ...CARD_STYLE, flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 14 }}>
        {messages.length === 0 ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "40px 16px", gap: 16 }}>
            <div style={{ color: "#64748b", fontSize: 14, textAlign: "center" }}>Ask a question to get started.</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%", maxWidth: 600 }}>
              {SUGGESTED.map(q => (
                <button key={q} onClick={() => ask(q)} style={{
                  textAlign: "left", padding: "10px 14px", background: "#0f172a",
                  border: "1px solid #334155", borderRadius: 8, color: "#cbd5e1",
                  fontSize: 12, cursor: "pointer",
                }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => {
            if (m.role === "user") {
              return (
                <div key={i} style={{ display: "flex", justifyContent: "flex-end" }}>
                  <div style={{
                    maxWidth: "75%", background: "#1e3a5f", border: "1px solid #2563eb",
                    borderRadius: 10, padding: "8px 12px", color: "white", fontSize: 13, whiteSpace: "pre-wrap",
                  }}>
                    {m.content}
                  </div>
                </div>
              );
            }
            return (
              <div key={i} style={{ display: "flex", justifyContent: "flex-start" }}>
                <div style={{
                  maxWidth: "92%", background: "#0f172a", border: "1px solid #334155",
                  borderRadius: 10, padding: "12px 14px", width: "100%",
                }}>
                  <div style={{ color: "#475569", fontSize: 10, fontWeight: 600, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 6 }}>Analyst</div>
                  <div style={{ color: "#e2e8f0", fontSize: 13, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
                    {m.content || (streaming && i === messages.length - 1 ? <span style={{ color: "#64748b" }}>...</span> : null)}
                  </div>
                  {m.charts?.map((c, j) => (
                    <div key={j} style={{ marginTop: 12, padding: "10px 0", borderTop: "1px solid #1e293b" }}>
                      <div style={{ color: "white", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{c.title}</div>
                      <ChartRenderer spec={c} />
                      <div style={{ color: "#475569", fontSize: 10, marginTop: 4 }}>
                        Source table: {c.source_table}
                        {c.breakdown_by ? ` · breakdown by ${c.breakdown_by}` : null}
                      </div>
                      {c.reasoning ? (
                        <div style={{ color: "#64748b", fontSize: 11, marginTop: 4, fontStyle: "italic" }}>
                          {c.reasoning}
                        </div>
                      ) : null}
                    </div>
                  ))}
                  {m.toolCalls && <ToolTrace calls={m.toolCalls} />}
                  {m.citations && <CitationList items={m.citations} />}
                  {m.error && (
                    <div style={{ marginTop: 8, color: "#ef4444", fontSize: 12, fontStyle: "italic" }}>
                      {m.error}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Input */}
      <div style={{ ...CARD_STYLE, padding: 12, display: "flex", gap: 10, alignItems: "flex-end" }}>
        <textarea
          ref={taRef}
          rows={1}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            const ta = e.target;
            ta.style.height = "auto";
            ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
          }}
          onKeyDown={handleKeyDown}
          placeholder="Ask about MW, sites, permits, providers..."
          disabled={streaming}
          style={{
            flex: 1, resize: "none", minHeight: 38, maxHeight: 120,
            background: "#0f172a", border: "1px solid #334155", borderRadius: 6,
            color: "white", fontSize: 13, padding: "9px 12px", fontFamily: "inherit", outline: "none", lineHeight: "20px",
          }}
        />
        {streaming ? (
          <button onClick={stop} style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            background: "#ef4444", border: "none", borderRadius: 6, color: "white",
            padding: "9px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer", height: 38,
          }}>
            <Square size={12} /> Stop
          </button>
        ) : (
          <button onClick={handleSubmit} disabled={!input.trim()} style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            background: input.trim() ? "#3b82f6" : "#334155", border: "none", borderRadius: 6, color: "white",
            padding: "9px 16px", fontSize: 13, fontWeight: 600,
            cursor: input.trim() ? "pointer" : "not-allowed", height: 38,
          }}>
            <Send size={12} /> Ask
          </button>
        )}
      </div>
    </div>
  );
}
