import { useState, useRef, useEffect } from "react";
import type { KeyboardEvent } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell, LabelList,
  LineChart, Line,
  ScatterChart, Scatter, ZAxis,
} from "recharts";
import {
  MessageSquare, Send, Square, Trash2, ExternalLink, ChevronDown, ChevronUp,
  X, Maximize2, Minimize2,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { useQA } from "../hooks/useQA";
import type { ChartSpec, Citation, QAMessage } from "../types";

// react-markdown component overrides — keep markdown looking like prose,
// not a stylesheet, while parsing **bold**, *italic*, `code`, lists, links.
const MD_COMPONENTS = {
  p: (props: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p {...props} style={{ margin: "0 0 8px", lineHeight: 1.55 }} />
  ),
  strong: (props: React.HTMLAttributes<HTMLElement>) => (
    <strong {...props} style={{ color: "white", fontWeight: 600 }} />
  ),
  em: (props: React.HTMLAttributes<HTMLElement>) => (
    <em {...props} style={{ color: "#cbd5e1", fontStyle: "italic" }} />
  ),
  code: (props: React.HTMLAttributes<HTMLElement>) => (
    <code {...props} style={{ background: "#0f172a", padding: "1px 5px", borderRadius: 3, fontSize: "0.92em" }} />
  ),
  a: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noreferrer" style={{ color: "#60a5fa", textDecoration: "underline" }} />
  ),
  ul: (props: React.HTMLAttributes<HTMLUListElement>) => (
    <ul {...props} style={{ margin: "4px 0 8px", paddingLeft: 20 }} />
  ),
  ol: (props: React.OlHTMLAttributes<HTMLOListElement>) => (
    <ol {...props} style={{ margin: "4px 0 8px", paddingLeft: 20 }} />
  ),
  li: (props: React.LiHTMLAttributes<HTMLLIElement>) => (
    <li {...props} style={{ margin: "2px 0" }} />
  ),
};

// ── Inline chart renderer for streamed chart_spec events ────────────────────

const TOOLTIP_STYLES = {
  contentStyle: { background: "#0f172a", border: "1px solid #334155", borderRadius: 8 },
  labelStyle: { color: "white" },
  itemStyle: { color: "#94a3b8" },
};

const PIE_COLORS = ["#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6","#06b6d4","#ec4899","#a855f7"];

// Round to nearest 0.1 for small values, integers (with comma sep) above 100.
function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  if (Math.abs(v) >= 100) return Math.round(v).toLocaleString();
  return (Math.round(v * 10) / 10).toString();
}

function ChartRenderer({ spec, height = 240 }: { spec: ChartSpec; height?: number }) {
  const data = (spec.series || []).map((s) => ({
    x: String(s.x),
    y: Number(((Number(s.y) ?? 0) * 10).toFixed(0)) / 10, // round to 0.1
  }));
  const ySeriesLabel = (spec.y as string) || "value";
  const xLabel = spec.x || "Category";

  if (spec.chart_type === "table") {
    return (
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155" }}>
              <th style={{ color: "#94a3b8", textAlign: "left", padding: "6px 8px" }}>{xLabel}</th>
              <th style={{ color: "#94a3b8", textAlign: "right", padding: "6px 8px" }}>{ySeriesLabel}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                <td style={{ color: "white", padding: "6px 8px" }}>{r.x}</td>
                <td style={{ color: "white", padding: "6px 8px", textAlign: "right" }}>{fmt(r.y)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (spec.chart_type === "pie") {
    // Pie label: "<name> NN%". Hide labels for tiny slices (<3%) to avoid
    // overlap. Recharts passes (cx, cy, midAngle, outerRadius, name, value,
    // percent, payload, index) to the label renderer.
    const total = data.reduce((s, d) => s + d.y, 0) || 1;
    interface PieLabelProps {
      cx: number; cy: number; midAngle: number; outerRadius: number;
      payload: { x: string; y: number };
    }
    const renderLabel = (props: unknown) => {
      const p = props as PieLabelProps;
      const pct = (p.payload.y / total) * 100;
      if (pct < 3) return null;
      const RAD = Math.PI / 180;
      const r = p.outerRadius + 16;
      const x = p.cx + r * Math.cos(-p.midAngle * RAD);
      const y = p.cy + r * Math.sin(-p.midAngle * RAD);
      return (
        <text
          x={x} y={y}
          fill="#cbd5e1" fontSize={11}
          textAnchor={x > p.cx ? "start" : "end"}
          dominantBaseline="central"
        >
          {p.payload.x} {pct.toFixed(0)}%
        </text>
      );
    };
    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={data}
            dataKey="y"
            nameKey="x"
            outerRadius={Math.min(height * 0.32, 86)}
            label={renderLabel}
            labelLine={false}
          >
            {data.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
          </Pie>
          <Tooltip
            {...TOOLTIP_STYLES}
            formatter={(v: number, _n, props) => {
              const x = (props as { payload?: { x?: string } })?.payload?.x ?? "";
              return [`${fmt(v)} ${ySeriesLabel}`, x];
            }}
          />
          <Legend
            verticalAlign="bottom" align="center"
            wrapperStyle={{ fontSize: 11, color: "#cbd5e1" }}
            formatter={(value: string) => {
              const row = data.find(d => d.x === value);
              return row ? `${value} — ${fmt(row.y)}` : value;
            }}
          />
        </PieChart>
      </ResponsiveContainer>
    );
  }
  if (spec.chart_type === "line") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 16, right: 24, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="x" tick={{ fill: "#94a3b8", fontSize: 11 }} label={{ value: xLabel, position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 10 }} />
          <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={fmt} label={{ value: ySeriesLabel, angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 10 }} />
          <Tooltip {...TOOLTIP_STYLES} formatter={(v: number) => [fmt(v), ySeriesLabel]} />
          <Legend wrapperStyle={{ fontSize: 11, color: "#cbd5e1" }} />
          <Line type="monotone" dataKey="y" name={ySeriesLabel} stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }}>
            <LabelList dataKey="y" position="top" formatter={fmt} fill="#cbd5e1" fontSize={10} />
          </Line>
        </LineChart>
      </ResponsiveContainer>
    );
  }
  if (spec.chart_type === "scatter") {
    const sd = (spec.series || []).map((s) => ({ x: Number(s.x), y: Number(s.y) }));
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 16, right: 24, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis type="number" dataKey="x" name={xLabel} tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={fmt} label={{ value: xLabel, position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 10 }} />
          <YAxis type="number" dataKey="y" name={ySeriesLabel} tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={fmt} label={{ value: ySeriesLabel, angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 10 }} />
          <ZAxis range={[60, 60]} />
          <Tooltip {...TOOLTIP_STYLES} cursor={{ strokeDasharray: "3 3" }} formatter={(v: number) => fmt(v)} />
          <Legend wrapperStyle={{ fontSize: 11, color: "#cbd5e1" }} />
          <Scatter data={sd} name={ySeriesLabel} fill="#3b82f6" />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 16, right: 24, left: 4, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="x" tick={{ fill: "#94a3b8", fontSize: 11 }} interval={0} angle={data.length > 6 ? -25 : 0} textAnchor={data.length > 6 ? "end" : "middle"} height={data.length > 6 ? 50 : 30} label={data.length > 6 ? undefined : { value: xLabel, position: "insideBottom", offset: -2, fill: "#64748b", fontSize: 10 }} />
        <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={fmt} label={{ value: ySeriesLabel, angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 10 }} />
        <Tooltip {...TOOLTIP_STYLES} cursor={{ fill: "#ffffff10" }} formatter={(v: number) => [fmt(v), ySeriesLabel]} />
        <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
        <Bar dataKey="y" fill="#3b82f6" name={ySeriesLabel} radius={[4,4,0,0]}>
          <LabelList dataKey="y" position="top" formatter={fmt} fill="#cbd5e1" fontSize={10} />
        </Bar>
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

const SUGGESTED = [
  "How much MW does Microsoft have in Virginia?",
  "Show me total MW by provider for top 5 hyperscalers",
  "Which states have the most generator permits?",
  "Compare AWS vs Microsoft datacenter announcements 2024-2026",
  "What's our generator-permit coverage by state?",
];

// ── ChatPanel ───────────────────────────────────────────────────────────────
//
// Floating chat that takes over the responsibilities of the old separate Q&A
// tab. Three layout modes:
//   - "closed":    a single FAB in the bottom-right (open the panel)
//   - "open":      floating panel docked bottom-right (~420×600)
//   - "expanded":  large modal overlay covering most of the viewport
// Minimize collapses back to FAB; expand toggles between panel <-> modal.

type Mode = "closed" | "open" | "expanded";

export default function ChatPanel() {
  const [mode, setMode] = useState<Mode>("closed");
  const [input, setInput] = useState("");
  const { messages, ask, stop, clear, streaming } = useQA();
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

  if (mode === "closed") {
    return (
      <button
        onClick={() => setMode("open")}
        title="Ask the analyst"
        style={{
          position: "fixed", bottom: 22, right: 22, zIndex: 1200,
          width: 56, height: 56, borderRadius: "50%",
          background: "#3b82f6", border: "none", color: "white",
          boxShadow: "0 8px 24px rgba(59,130,246,0.4)",
          cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        <MessageSquare size={22} />
      </button>
    );
  }

  const isExpanded = mode === "expanded";
  const outerStyle: React.CSSProperties = isExpanded
    ? {
        position: "fixed", inset: 0, margin: "auto",
        width: "min(1200px, 92vw)", height: "min(820px, 88vh)",
        background: "#0f172a", border: "1px solid #334155", borderRadius: 12,
        boxShadow: "0 24px 64px rgba(0,0,0,0.6)",
        zIndex: 1300, display: "flex", flexDirection: "column",
      }
    : {
        position: "fixed", bottom: 22, right: 22,
        width: 420, height: 600, maxHeight: "calc(100vh - 44px)",
        background: "#0f172a", border: "1px solid #334155", borderRadius: 12,
        boxShadow: "0 16px 40px rgba(0,0,0,0.5)",
        zIndex: 1200, display: "flex", flexDirection: "column",
      };

  const backdrop = isExpanded ? (
    <div
      onClick={() => setMode("open")}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1290,
      }}
    />
  ) : null;

  return (
    <>
      {backdrop}
      <div style={outerStyle}>
        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "10px 14px", borderBottom: "1px solid #1e293b",
          background: "#162032", borderRadius: "12px 12px 0 0",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <MessageSquare size={16} color="#3b82f6" />
            <div>
              <div style={{ color: "white", fontSize: 13, fontWeight: 600 }}>Ask the Analyst</div>
              <div style={{ color: "#64748b", fontSize: 10 }}>
                Live data over sites, permits, EDGAR, and energy projects
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button
              onClick={clear}
              disabled={streaming || messages.length === 0}
              title="Clear conversation"
              style={{
                background: "none", border: "none", color: "#64748b",
                cursor: streaming || messages.length === 0 ? "not-allowed" : "pointer",
                padding: 6, display: "flex", borderRadius: 4,
              }}
            >
              <Trash2 size={14} />
            </button>
            <button
              onClick={() => setMode(isExpanded ? "open" : "expanded")}
              title={isExpanded ? "Shrink" : "Expand"}
              style={{
                background: "none", border: "none", color: "#94a3b8",
                cursor: "pointer", padding: 6, display: "flex", borderRadius: 4,
              }}
            >
              {isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <button
              onClick={() => setMode("closed")}
              title="Minimize"
              style={{
                background: "none", border: "none", color: "#94a3b8",
                cursor: "pointer", padding: 6, display: "flex", borderRadius: 4,
              }}
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div
          ref={listRef}
          style={{
            flex: 1, overflowY: "auto",
            padding: "14px 16px",
            display: "flex", flexDirection: "column", gap: 12,
          }}
        >
          {messages.length === 0 ? (
            <div style={{
              display: "flex", flexDirection: "column",
              alignItems: "center", gap: 12, padding: "20px 8px",
            }}>
              <div style={{ color: "#64748b", fontSize: 12, textAlign: "center" }}>
                Ask anything about the live data — agent picks the right tables and chart type.
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, width: "100%", maxWidth: 700 }}>
                {SUGGESTED.map(q => (
                  <button
                    key={q}
                    onClick={() => ask(q)}
                    style={{
                      textAlign: "left", padding: "8px 12px", background: "#1e293b",
                      border: "1px solid #334155", borderRadius: 8, color: "#cbd5e1",
                      fontSize: 12, cursor: "pointer",
                    }}
                  >
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
                      maxWidth: "85%", background: "#1e3a5f", border: "1px solid #2563eb",
                      borderRadius: 10, padding: "8px 12px", color: "white",
                      fontSize: 13, whiteSpace: "pre-wrap",
                    }}>
                      {m.content}
                    </div>
                  </div>
                );
              }
              return (
                <div key={i} style={{ display: "flex", justifyContent: "flex-start" }}>
                  <div style={{
                    maxWidth: "95%", width: "100%",
                    background: "#1e293b", border: "1px solid #334155",
                    borderRadius: 10, padding: "10px 12px",
                  }}>
                    <div style={{ color: "#475569", fontSize: 10, fontWeight: 600, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 6 }}>
                      Analyst
                    </div>
                    <div style={{ color: "#e2e8f0", fontSize: 13, lineHeight: 1.55 }}>
                      {m.content
                        ? <ReactMarkdown components={MD_COMPONENTS}>{m.content}</ReactMarkdown>
                        : streaming && i === messages.length - 1 ? <span style={{ color: "#64748b" }}>...</span> : null}
                    </div>
                    {m.charts?.map((c, j) => (
                      <div key={j} style={{ marginTop: 12, padding: "10px 0", borderTop: "1px solid #334155" }}>
                        <div style={{ color: "white", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{c.title}</div>
                        <ChartRenderer spec={c} height={isExpanded ? 280 : 200} />
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
        <div style={{
          borderTop: "1px solid #1e293b", padding: 10,
          display: "flex", gap: 8, alignItems: "flex-end",
          background: "#162032", borderRadius: "0 0 12px 12px",
        }}>
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
              flex: 1, resize: "none", minHeight: 36, maxHeight: 120,
              background: "#0f172a", border: "1px solid #334155", borderRadius: 6,
              color: "white", fontSize: 13, padding: "8px 10px",
              fontFamily: "inherit", outline: "none", lineHeight: "20px",
            }}
          />
          {streaming ? (
            <button onClick={stop} title="Stop" style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              background: "#ef4444", border: "none", borderRadius: 6,
              color: "white", padding: "8px 14px", fontSize: 12,
              fontWeight: 600, cursor: "pointer", height: 36,
            }}>
              <Square size={11} /> Stop
            </button>
          ) : (
            <button onClick={handleSubmit} disabled={!input.trim()} title="Ask" style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              background: input.trim() ? "#3b82f6" : "#334155", border: "none", borderRadius: 6,
              color: "white", padding: "8px 14px", fontSize: 12,
              fontWeight: 600, cursor: input.trim() ? "pointer" : "not-allowed", height: 36,
            }}>
              <Send size={11} /> Ask
            </button>
          )}
        </div>
      </div>
    </>
  );
}
