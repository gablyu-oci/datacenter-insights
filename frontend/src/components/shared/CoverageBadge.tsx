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
  full: { bg: "#052e16", border: "#16a34a", text: "#4ade80" },
  partial: { bg: "#451a03", border: "#d97706", text: "#fbbf24" },
  none: { bg: "#450a0a", border: "#dc2626", text: "#f87171" },
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
  const [status, setStatus] = useState<string>("none");
  const [lastIngested, setLastIngested] = useState<string | null>(null);
  const [showTooltip, setShowTooltip] = useState(false);

  useEffect(() => {
    fetchCoverage().then((rows) => {
      // Find rows matching this pillar (case-insensitive partial match)
      const pillarLower = pillar.toLowerCase();
      const matching = rows.filter((r) =>
        r.pillar?.toLowerCase().includes(pillarLower) ||
        pillarLower.includes(r.pillar?.toLowerCase() ?? "")
      );
      if (matching.length === 0) {
        setStatus("none");
        return;
      }
      // Determine overall status
      const statuses = matching.map((r) => r.coverage_status?.toLowerCase() ?? "none");
      if (statuses.every((s) => s === "full" || s === "complete")) {
        setStatus("full");
      } else if (statuses.some((s) => s !== "none" && s !== "empty" && s !== "")) {
        setStatus("partial");
      } else {
        setStatus("none");
      }
      // Get most recent ingestion
      const dates = matching
        .map((r) => r.last_ingested_at)
        .filter(Boolean)
        .sort()
        .reverse();
      if (dates.length > 0) setLastIngested(dates[0] ?? null);
    });
  }, [pillar]);

  const colors = STATUS_COLORS[status] ?? STATUS_COLORS.none;
  const label = status === "full" ? "Full Coverage" : status === "partial" ? "Partial" : "No Data";

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
