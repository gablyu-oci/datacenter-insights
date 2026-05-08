import { useState } from "react";
import { Pie, PieChart, Cell, Tooltip, ResponsiveContainer } from "recharts";

// ── Types ────────────────────────────────────────────────────────────────────

export interface CounterpartySitesEntry {
  company_id: number;
  canonical_name: string;
  count: number;
}

export interface CounterpartyMwEntry {
  company_id: number;
  canonical_name: string;
  mw: number;
}

interface CounterpartyPieCardProps {
  title: string;
  subtitle: string;
  sitesData: CounterpartySitesEntry[];
  mwData: CounterpartyMwEntry[];
  otherSites: number;
  otherMw: number;
  companyName: string;
}

// ── Tokens ──────────────────────────────────────────────────────────────────

const COLOR_PALETTE = [
  "#3b82f6",
  "#22c55e",
  "#f59e0b",
  "#8b5cf6",
  "#06b6d4",
  "#ec4899",
  "#f97316",
];
const OTHER_COLOR = "#64748b";

const TOOLTIP_STYLES = {
  contentStyle: {
    background: "#0f172a",
    border: "1px solid #334155",
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: "#e2e8f0" },
  itemStyle: { color: "#94a3b8" },
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function truncateName(name: string): string {
  if (name.length <= 18) return name;
  return name.slice(0, 17) + "...";
}

interface SliceRow {
  name: string;
  value: number;
  color: string;
  isOther?: boolean;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function CounterpartyPieCard({
  title,
  subtitle,
  sitesData,
  mwData,
  otherSites,
  otherMw,
  companyName,
}: CounterpartyPieCardProps) {
  const [metric, setMetric] = useState<"sites" | "mw">("sites");

  // Build slice rows from the active metric. Top-7 in palette order, then "Other".
  const activeRows: SliceRow[] = (() => {
    const out: SliceRow[] = [];
    if (metric === "sites") {
      sitesData.slice(0, 7).forEach((r, i) => {
        out.push({
          name: r.canonical_name,
          value: r.count,
          color: COLOR_PALETTE[i % COLOR_PALETTE.length],
        });
      });
      if (otherSites > 0) {
        out.push({ name: "Other", value: otherSites, color: OTHER_COLOR, isOther: true });
      }
    } else {
      mwData.slice(0, 7).forEach((r, i) => {
        out.push({
          name: r.canonical_name,
          value: r.mw,
          color: COLOR_PALETTE[i % COLOR_PALETTE.length],
        });
      });
      if (otherMw > 0) {
        out.push({ name: "Other", value: otherMw, color: OTHER_COLOR, isOther: true });
      }
    }
    return out;
  })();

  const sitesEmpty = sitesData.length === 0 && otherSites === 0;
  const mwEmpty = mwData.length === 0 && otherMw === 0;
  const isCardEmpty = metric === "sites" ? sitesEmpty : mwEmpty;
  // The toggle is fully disabled only when both metrics are empty.
  const toggleDisabled = sitesEmpty && mwEmpty;

  // Empty-state copy is keyed off the side title (Buyers vs Sellers).
  const emptyMessage = title === "Buyers" ? "No buyers known" : "No sellers known";

  const formatValue = (v: number): string => {
    if (metric === "mw") return `${Math.round(v)} MW`;
    return String(Math.round(v));
  };

  return (
    <div
      style={{
        flex: "1 1 280px",
        minWidth: 0,
        background: "#1e293b",
        border: "1px solid #334155",
        borderRadius: 12,
        padding: 16,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Title + subtitle */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 700 }}>{title}</div>
        <div style={{ color: "#64748b", fontSize: 11, marginTop: 2 }}>{subtitle}</div>
      </div>

      {/* Segmented toggle */}
      <div
        role="group"
        aria-label="Metric"
        style={{
          display: "inline-flex",
          background: "#0f172a",
          border: "1px solid #334155",
          borderRadius: 6,
          padding: 2,
          marginBottom: 10,
          alignSelf: "flex-start",
          opacity: toggleDisabled ? 0.4 : 1,
        }}
      >
        {(["sites", "mw"] as const).map((m) => {
          const active = metric === m;
          return (
            <button
              key={m}
              type="button"
              aria-pressed={active}
              aria-disabled={toggleDisabled || undefined}
              disabled={toggleDisabled}
              onClick={() => {
                if (!toggleDisabled) setMetric(m);
              }}
              style={{
                padding: "4px 10px",
                fontSize: 11,
                fontWeight: 600,
                borderRadius: 4,
                border: "none",
                cursor: toggleDisabled ? "not-allowed" : "pointer",
                transition: "none",
                background: active ? "#3b82f6" : "transparent",
                color: active ? "#ffffff" : "#64748b",
              }}
              onMouseOver={(e) => {
                if (!active && !toggleDisabled) e.currentTarget.style.color = "#94a3b8";
              }}
              onMouseOut={(e) => {
                if (!active && !toggleDisabled) e.currentTarget.style.color = "#64748b";
              }}
            >
              {m === "sites" ? "Sites" : "MW"}
            </button>
          );
        })}
      </div>

      {/* Donut OR empty-state */}
      {isCardEmpty ? (
        <div
          style={{
            height: 120,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#64748b",
            fontSize: 12,
          }}
        >
          {emptyMessage}
        </div>
      ) : (
        <>
          <div
            role="img"
            aria-label={`${title} distribution by ${metric === "sites" ? "sites" : "MW"} for ${companyName}`}
          >
            <ResponsiveContainer width="100%" height={116}>
              <PieChart>
                <Pie
                  data={activeRows}
                  dataKey="value"
                  nameKey="name"
                  outerRadius={48}
                  innerRadius={26}
                  labelLine={false}
                  sortValues={false}
                  isAnimationActive={false}
                >
                  {activeRows.map((row, i) => (
                    <Cell key={`${row.name}-${i}`} fill={row.color} />
                  ))}
                </Pie>
                <Tooltip
                  {...TOOLTIP_STYLES}
                  formatter={(v: unknown, n: unknown) => [formatValue(Number(v)), String(n)]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Custom 2-column legend */}
          <div
            role="list"
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              columnGap: 8,
              rowGap: 4,
              marginTop: 8,
            }}
          >
            {activeRows.map((row, i) => (
              <LegendRow
                key={`${row.name}-${i}`}
                name={row.name}
                value={formatValue(row.value)}
                color={row.color}
                isOther={!!row.isOther}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function LegendRow({
  name,
  value,
  color,
  isOther,
}: {
  name: string;
  value: string;
  color: string;
  isOther: boolean;
}) {
  return (
    <>
      <div
        role="listitem"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
          color: isOther ? "#64748b" : "#cbd5e1",
          minWidth: 0,
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 8,
            height: 8,
            borderRadius: 2,
            background: color,
            flexShrink: 0,
            display: "inline-block",
          }}
        />
        <span
          style={{
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={name}
        >
          {truncateName(name)}
        </span>
      </div>
      <div
        style={{
          fontSize: 11,
          color: "#94a3b8",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </>
  );
}
