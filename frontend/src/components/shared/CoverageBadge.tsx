import { useState, useEffect } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

interface CoverageRow {
  pillar: string;
  coverage_status: string;
  last_ingested_at?: string;
  states_covered?: number;
  total_states?: number;
}

interface CoverageBadgeProps {
  pillar: string;
}

const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  partial: { bg: "#451a03", border: "#d97706", text: "#fbbf24" },
};

// Simple global cache for coverage data
const coverageCache: { data: CoverageRow[] | null; fetching: boolean; listeners: Array<() => void> } = {
  data: null,
  fetching: false,
  listeners: [],
};

function fetchCoverage(): Promise<CoverageRow[]> {
  if (coverageCache.data) return Promise.resolve(coverageCache.data);
  if (coverageCache.fetching) {
    return new Promise((resolve) => {
      coverageCache.listeners.push(() => resolve(coverageCache.data ?? []));
    });
  }
  coverageCache.fetching = true;
  return fetch(`${API_BASE}/api/coverage/`)
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then((json) => {
      // Unwrap envelope
      const rows: CoverageRow[] = json && json.data ? (Array.isArray(json.data) ? json.data : []) : (Array.isArray(json) ? json : []);
      coverageCache.data = rows;
      coverageCache.fetching = false;
      coverageCache.listeners.forEach((fn) => fn());
      coverageCache.listeners = [];
      return rows;
    })
    .catch(() => {
      coverageCache.fetching = false;
      return [];
    });
}

export default function CoverageBadge({ pillar }: CoverageBadgeProps) {
  const [status, setStatus] = useState<string>("hidden");
  const [lastIngested, setLastIngested] = useState<string | null>(null);
  const [showTooltip, setShowTooltip] = useState(false);

  useEffect(() => {
    fetchCoverage().then((rows) => {
      const pillarLower = pillar.toLowerCase();
      const matching = rows.filter((r) =>
        r.pillar?.toLowerCase().includes(pillarLower) ||
        pillarLower.includes(r.pillar?.toLowerCase() ?? "")
      );
      // No matching coverage rows → don't show a badge (avoid misleading "No Data" on tabs that do have data)
      if (matching.length === 0) {
        setStatus("hidden");
        return;
      }
      const statuses = matching.map((r) => r.coverage_status?.toLowerCase() ?? "none");
      // Only flag genuinely partial coverage. Full = no badge (default expectation).
      // Empty across the board = no badge either; the page itself will show its own empty state.
      const isFull = statuses.every((s) => s === "full" || s === "complete");
      const hasAny = statuses.some((s) => s !== "none" && s !== "empty" && s !== "");
      if (!isFull && hasAny) {
        setStatus("partial");
      } else {
        setStatus("hidden");
      }
      const dates = matching
        .map((r) => r.last_ingested_at)
        .filter(Boolean)
        .sort()
        .reverse();
      if (dates.length > 0) setLastIngested(dates[0] ?? null);
    });
  }, [pillar]);

  if (status !== "partial") return null;
  const colors = STATUS_COLORS.partial;
  const label = "Partial";

  return (
    <div
      style={{ position: "relative", display: "inline-flex" }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "4px",
          padding: "2px 8px",
          borderRadius: "12px",
          background: colors.bg,
          border: `1px solid ${colors.border}`,
          color: colors.text,
          fontSize: "10px",
          fontWeight: 600,
          letterSpacing: "0.03em",
          cursor: "default",
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: colors.text,
            flexShrink: 0,
          }}
        />
        {label}
      </span>
      {showTooltip && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 50,
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: "6px",
            padding: "8px 12px",
            whiteSpace: "nowrap",
            boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
          }}
        >
          <div style={{ color: "#94a3b8", fontSize: "10px", marginBottom: "2px" }}>
            Pillar: {pillar}
          </div>
          <div style={{ color: "#e2e8f0", fontSize: "11px" }}>
            {lastIngested
              ? `Last ingested: ${lastIngested.split("T")[0]}`
              : "No ingestion data"}
          </div>
        </div>
      )}
    </div>
  );
}
