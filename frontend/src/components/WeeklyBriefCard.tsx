import { useEffect, useState, useCallback, ReactNode } from "react";

interface BriefResponse {
  markdown: string | null;
  generated_at: string | null;
}

const CARD_STYLE: React.CSSProperties = {
  background: "#1e293b",
  border: "1px solid #334155",
  borderRadius: 8,
  padding: 20,
  maxWidth: 800,
  margin: "24px auto",
  color: "white",
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
};

// Render a single line of inline content (bold + URLs + plain text).
function renderInline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  // First split on bold markers.
  const boldRe = /\*\*(.+?)\*\*/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  let idx = 0;
  const segments: Array<{ kind: "text" | "bold"; value: string }> = [];
  while ((match = boldRe.exec(text)) !== null) {
    if (match.index > lastIdx) {
      segments.push({ kind: "text", value: text.slice(lastIdx, match.index) });
    }
    segments.push({ kind: "bold", value: match[1] });
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) {
    segments.push({ kind: "text", value: text.slice(lastIdx) });
  }

  // For each text segment, also linkify bare URLs.
  const urlRe = /(https?:\/\/[^\s)]+)/g;
  for (const seg of segments) {
    if (seg.kind === "bold") {
      out.push(
        <strong key={`${keyBase}-b-${idx++}`} style={{ color: "white" }}>
          {seg.value}
        </strong>
      );
      continue;
    }
    let l = 0;
    let m: RegExpExecArray | null;
    const local = seg.value;
    const urlRe2 = new RegExp(urlRe.source, "g");
    while ((m = urlRe2.exec(local)) !== null) {
      if (m.index > l) {
        out.push(<span key={`${keyBase}-t-${idx++}`}>{local.slice(l, m.index)}</span>);
      }
      out.push(
        <a
          key={`${keyBase}-u-${idx++}`}
          href={m[1]}
          target="_blank"
          rel="noreferrer"
          style={{ color: "#38bdf8", wordBreak: "break-all" }}
        >
          {m[1]}
        </a>
      );
      l = m.index + m[1].length;
    }
    if (l < local.length) {
      out.push(<span key={`${keyBase}-t-${idx++}`}>{local.slice(l)}</span>);
    }
  }
  return out;
}

function renderMarkdown(md: string): ReactNode {
  const lines = md.split(/\r?\n/);
  const out: ReactNode[] = [];
  let paraBuf: string[] = [];
  let listBuf: string[] = [];
  let key = 0;

  const flushPara = () => {
    if (paraBuf.length === 0) return;
    const text = paraBuf.join(" ");
    out.push(
      <p key={`p-${key++}`} style={{ margin: "0 0 12px", color: "#e2e8f0", fontSize: 13, lineHeight: 1.6 }}>
        {renderInline(text, `p${key}`)}
      </p>
    );
    paraBuf = [];
  };

  const flushList = () => {
    if (listBuf.length === 0) return;
    const items = listBuf;
    out.push(
      <ul
        key={`ul-${key++}`}
        style={{ margin: "0 0 12px", paddingLeft: 22, color: "#e2e8f0", fontSize: 13, lineHeight: 1.6 }}
      >
        {items.map((li, i) => (
          <li key={`li-${key}-${i}`} style={{ marginBottom: 4 }}>
            {renderInline(li, `li${key}${i}`)}
          </li>
        ))}
      </ul>
    );
    listBuf = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith("## ")) {
      flushPara();
      flushList();
      out.push(
        <h2
          key={`h2-${key++}`}
          style={{ color: "white", fontSize: 16, fontWeight: 600, margin: "16px 0 8px" }}
        >
          {renderInline(line.slice(3), `h2${key}`)}
        </h2>
      );
    } else if (line.startsWith("# ")) {
      flushPara();
      flushList();
      out.push(
        <h1
          key={`h1-${key++}`}
          style={{ color: "white", fontSize: 20, fontWeight: 700, margin: "8px 0 12px" }}
        >
          {renderInline(line.slice(2), `h1${key}`)}
        </h1>
      );
    } else if (line.startsWith("- ")) {
      flushPara();
      listBuf.push(line.slice(2));
    } else if (line.trim() === "") {
      flushPara();
      flushList();
    } else {
      flushList();
      paraBuf.push(line);
    }
  }
  flushPara();
  flushList();

  return <>{out}</>;
}

export default function WeeklyBriefCard() {
  const [brief, setBrief] = useState<BriefResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBrief = useCallback(async () => {
    try {
      const res = await fetch("/api/brief/latest");
      if (!res.ok) throw new Error(`Failed to load brief (${res.status})`);
      const json = (await res.json()) as BriefResponse;
      setBrief(json);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBrief();
  }, [fetchBrief]);

  const handleRegenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const res = await fetch("/api/brief/run", { method: "POST" });
      if (!res.ok) throw new Error(`Generation failed (${res.status})`);
      await fetchBrief();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setGenerating(false);
    }
  };

  const generatedLabel = brief?.generated_at
    ? `Generated: ${new Date(brief.generated_at).toLocaleString()}`
    : "No brief generated yet";

  return (
    <div style={CARD_STYLE}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 12,
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "white" }}>
            <span aria-hidden="true" style={{ marginRight: 8 }}>{"\u{1F4F0}"}</span>
            Weekly Brief
          </h2>
          <div style={{ color: "#94a3b8", fontSize: 12, marginTop: 4 }}>{generatedLabel}</div>
        </div>
        <button
          onClick={handleRegenerate}
          disabled={generating}
          style={{
            background: generating ? "#334155" : "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: 6,
            padding: "8px 14px",
            fontSize: 12,
            fontWeight: 600,
            cursor: generating ? "not-allowed" : "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {generating ? "Generating..." : "Regenerate"}
        </button>
      </div>

      {error && (
        <div
          style={{
            color: "#ef4444",
            fontSize: 12,
            margin: "8px 0 12px",
            background: "#7f1d1d22",
            border: "1px solid #ef444444",
            borderRadius: 6,
            padding: "8px 10px",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ borderTop: "1px solid #334155", paddingTop: 14 }}>
        {loading ? (
          <div style={{ color: "#3b82f6", fontSize: 13 }}>Loading brief...</div>
        ) : brief?.markdown ? (
          renderMarkdown(brief.markdown)
        ) : (
          <div style={{ color: "#64748b", fontSize: 13, fontStyle: "italic" }}>
            No brief content available. Click Regenerate to create one.
          </div>
        )}
      </div>
    </div>
  );
}
