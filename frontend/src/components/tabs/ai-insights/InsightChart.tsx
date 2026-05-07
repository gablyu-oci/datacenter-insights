import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Pie,
  PieChart,
  Radar,
  RadarChart,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { ChartSpec, Encoding, Annotation, YUnit } from "../../../types/chartSpec";
import { tokens } from "../../../styles/insightTokens";

/**
 * InsightChart — Recharts adapter for ChartSpec v1.
 *
 *  - Renders strictly from `spec.data` (no fetching, no remote refs;
 *    PRD §5.2 "no re-fetch" contract).
 *  - Switches on `chart_type` to pick the right Recharts primitive.
 *  - Applies `styling.y_unit` + `styling.y_precision` to the axis tick
 *    formatter and tooltip values.
 *  - Renders annotations as ReferenceLine / ReferenceArea / ReferenceDot.
 *  - Empty data renders the U4.5 "no data" frame instead of an empty axis.
 */

const c = tokens.color;
const t = tokens.typography;

const TOOLTIP_STYLES = {
  contentStyle: {
    background: c.chart.tooltipBg,
    border: `1px solid ${c.chart.tooltipBorder}`,
    borderRadius: tokens.radius.lg,
  },
  labelStyle: { color: c.text.primary },
  itemStyle: { color: c.text.caption },
};

const PIE_TRUNCATE_AT = 8;
const SERIES_TRUNCATE_AT = 8;

function makeFormatter(yUnit: YUnit | null | undefined, precision: number | null | undefined) {
  const digits =
    typeof precision === "number" && precision >= 0 && precision <= 6 ? precision : null;
  return (value: unknown): string => {
    if (value === null || value === undefined) return "";
    const num = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(num)) return String(value);
    let formatted: string;
    if (digits !== null) {
      formatted = num.toFixed(digits);
    } else if (Math.abs(num) >= 100) {
      formatted = Math.round(num).toLocaleString();
    } else {
      formatted = (Math.round(num * 10) / 10).toString();
    }
    if (yUnit && yUnit !== "count") {
      return yUnit === "%" || yUnit === "USD" ? `${formatted}${yUnit === "%" ? "%" : ""}` : `${formatted} ${yUnit}`;
    }
    return formatted;
  };
}

function pickColor(idx: number): string {
  return c.chart.categorical[idx % c.chart.categorical.length];
}

function distinctValues(data: Array<Record<string, unknown>>, field: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const row of data) {
    const v = row[field];
    const key = v === null || v === undefined ? "" : String(v);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(key);
    }
  }
  return out;
}

/**
 * Pivot rows from long form (one row per series-value) to wide form
 * (one row per x with one column per series). Recharts stacked / grouped
 * primitives all read wide-form.
 */
function pivotToWide(
  data: Array<Record<string, unknown>>,
  xField: string,
  yField: string,
  seriesField: string,
): { rows: Array<Record<string, unknown>>; series: string[] } {
  const seriesAll = distinctValues(data, seriesField);
  const series = seriesAll.slice(0, SERIES_TRUNCATE_AT);
  const seriesSet = new Set(series);
  const byX = new Map<string, Record<string, unknown>>();
  for (const row of data) {
    const xVal = row[xField];
    const sVal = row[seriesField];
    const xKey = xVal === null || xVal === undefined ? "" : String(xVal);
    const sKey = sVal === null || sVal === undefined ? "" : String(sVal);
    if (!seriesSet.has(sKey)) continue;
    let bucket = byX.get(xKey);
    if (!bucket) {
      bucket = { [xField]: xVal };
      byX.set(xKey, bucket);
    }
    bucket[sKey] = row[yField];
  }
  return { rows: Array.from(byX.values()), series };
}

function renderAnnotations(annotations: Annotation[] | null | undefined) {
  if (!annotations || annotations.length === 0) return null;
  return annotations.map((a, idx) => {
    if (a.type === "line") {
      const isNumeric = typeof a.value === "number";
      return (
        <ReferenceLine
          key={`ann-${idx}`}
          {...(isNumeric ? { y: a.value as number } : { x: a.value as string })}
          stroke={c.semantic.warning}
          strokeDasharray="4 2"
          label={{ value: a.label, fill: c.text.caption, fontSize: 10 }}
        />
      );
    }
    if (a.type === "band") {
      // Treat band value as a numeric +/- 5% band on Y.
      const v = typeof a.value === "number" ? a.value : Number(a.value);
      if (!Number.isFinite(v)) return null;
      return (
        <ReferenceArea
          key={`ann-${idx}`}
          y1={v * 0.95}
          y2={v * 1.05}
          fill={c.semantic.warning}
          fillOpacity={0.08}
          label={{ value: a.label, fill: c.text.caption, fontSize: 10 }}
        />
      );
    }
    return (
      <ReferenceDot
        key={`ann-${idx}`}
        x={typeof a.value === "number" ? undefined : (a.value as string)}
        y={typeof a.value === "number" ? a.value : undefined}
        r={4}
        fill={c.semantic.warning}
        stroke={c.text.caption}
        label={{ value: a.label, fill: c.text.caption, fontSize: 10 }}
      />
    );
  });
}

interface CommonAxisProps {
  encoding: Encoding;
  yFormat: (v: unknown) => string;
}

function XAxisFor({ encoding, yFormat: _y }: CommonAxisProps) {
  void _y;
  const x = encoding.x;
  return (
    <XAxis
      dataKey={x.field}
      tick={{ fill: c.chart.axisTick, fontSize: 11 }}
      label={
        x.label
          ? {
              value: x.label,
              position: "insideBottom",
              offset: -4,
              fill: c.chart.axisLabel,
              fontSize: 10,
            }
          : undefined
      }
    />
  );
}

function YAxisFor({ encoding, yFormat }: CommonAxisProps) {
  const y = encoding.y;
  return (
    <YAxis
      tick={{ fill: c.chart.axisTick, fontSize: 11 }}
      tickFormatter={yFormat}
      label={
        y.label
          ? {
              value: y.label,
              angle: -90,
              position: "insideLeft",
              fill: c.chart.axisLabel,
              fontSize: 10,
            }
          : undefined
      }
    />
  );
}

export interface InsightChartProps {
  spec: ChartSpec;
  height?: number;
}

export default function InsightChart({ spec, height = 220 }: InsightChartProps) {
  const yUnit = spec.styling?.y_unit ?? null;
  const yPrec = spec.styling?.y_precision ?? null;
  const fmt = makeFormatter(yUnit, yPrec);
  const data = spec.data ?? [];

  if (data.length === 0) {
    return (
      <div
        role="status"
        style={{
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "column",
          gap: 4,
          color: c.text.caption,
          fontSize: t.meta.fontSize,
          background: c.bg.surface,
          border: `1px solid ${c.border.default}`,
          borderRadius: tokens.radius.lg,
        }}
      >
        <div>No data for this slice — reasoning still applies.</div>
        <div style={{ color: c.text.faint }}>See provenance footer for the underlying query.</div>
      </div>
    );
  }

  const xField = spec.encoding.x.field;
  const yField = spec.encoding.y.field;
  const seriesField = spec.encoding.series?.field;
  const annotations = renderAnnotations(spec.annotations);

  if (spec.chart_type === "kpi_tile") {
    const value = data[0]?.[yField];
    return (
      <div
        style={{
          height,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 6,
          background: c.bg.surface,
          border: `1px solid ${c.border.default}`,
          borderRadius: tokens.radius.lg,
        }}
      >
        <div style={{ color: c.text.caption, fontSize: t.meta.fontSize }}>
          {spec.encoding.y.label || yField}
        </div>
        <div style={{ color: c.text.primary, fontSize: 28, fontWeight: 700 }}>{fmt(value)}</div>
        {spec.subtitle ? (
          <div style={{ color: c.text.muted, fontSize: t.caption.fontSize }}>{spec.subtitle}</div>
        ) : null}
      </div>
    );
  }

  if (spec.chart_type === "table") {
    const xLabel = spec.encoding.x.label || xField;
    const yLabel = spec.encoding.y.label || yField;
    return (
      <div
        style={{
          maxHeight: height,
          overflowY: "auto",
          background: c.bg.surface,
          border: `1px solid ${c.border.default}`,
          borderRadius: tokens.radius.lg,
        }}
      >
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${c.border.default}`, background: c.bg.surface }}>
              <th style={{ color: c.text.caption, textAlign: "left", padding: "8px 10px" }}>{xLabel}</th>
              <th style={{ color: c.text.caption, textAlign: "right", padding: "8px 10px" }}>{yLabel}</th>
            </tr>
          </thead>
          <tbody>
            {data.slice(0, 100).map((row, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${c.border.default}` }}>
                <td style={{ color: c.text.primary, padding: "6px 10px" }}>{String(row[xField] ?? "")}</td>
                <td style={{ color: c.text.primary, padding: "6px 10px", textAlign: "right" }}>{fmt(row[yField])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (spec.chart_type === "pie" || spec.chart_type === "donut") {
    const isDonut = spec.chart_type === "donut";
    const sorted = [...data].sort((a, b) => Number(b[yField] ?? 0) - Number(a[yField] ?? 0));
    const slices = sorted.slice(0, PIE_TRUNCATE_AT).map((row) => ({
      name: String(row[xField] ?? ""),
      value: Number(row[yField] ?? 0),
    }));
    const total = slices.reduce((acc, r) => acc + r.value, 0) || 1;
    const outerR = Math.min(height * 0.35, 90);
    const innerR = isDonut ? outerR * 0.6 : 0;
    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={slices}
            dataKey="value"
            nameKey="name"
            outerRadius={outerR}
            innerRadius={innerR}
            labelLine={false}
            label={(props: unknown) => {
              const p = props as {
                cx: number;
                cy: number;
                midAngle: number;
                outerRadius: number;
                payload: { name: string; value: number };
              };
              const pct = (p.payload.value / total) * 100;
              if (pct < 3) return null;
              const RAD = Math.PI / 180;
              const rad = p.outerRadius + 16;
              const px = p.cx + rad * Math.cos(-p.midAngle * RAD);
              const py = p.cy + rad * Math.sin(-p.midAngle * RAD);
              return (
                <text
                  x={px}
                  y={py}
                  fill={c.text.muted}
                  fontSize={11}
                  textAnchor={px > p.cx ? "start" : "end"}
                  dominantBaseline="central"
                >
                  {p.payload.name} {pct.toFixed(0)}%
                </text>
              );
            }}
          >
            {slices.map((_, i) => (
              <Cell key={i} fill={pickColor(i)} />
            ))}
          </Pie>
          <Tooltip
            {...TOOLTIP_STYLES}
            formatter={(v: unknown) => fmt(v)}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: c.text.muted }}
            formatter={(value: string) => value}
          />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (spec.chart_type === "scatter" || spec.chart_type === "bubble") {
    const sizeField = spec.encoding.size?.field;
    const points = data.map((row) => ({
      x: Number(row[xField] ?? 0),
      y: Number(row[yField] ?? 0),
      z: sizeField ? Number(row[sizeField] ?? 0) : 1,
      _row: row,
    }));
    // For bubble: scale point size by the size field; clamp the visual range.
    const isBubble = spec.chart_type === "bubble" && !!sizeField;
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 16, right: 24, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={c.chart.grid} />
          <XAxis
            type="number"
            dataKey="x"
            tick={{ fill: c.chart.axisTick, fontSize: 11 }}
            tickFormatter={(v) => String(v)}
            label={
              spec.encoding.x.label
                ? {
                    value: spec.encoding.x.label,
                    position: "insideBottom",
                    offset: -4,
                    fill: c.chart.axisLabel,
                    fontSize: 10,
                  }
                : undefined
            }
          />
          <YAxis
            type="number"
            dataKey="y"
            tick={{ fill: c.chart.axisTick, fontSize: 11 }}
            tickFormatter={fmt}
            label={
              spec.encoding.y.label
                ? {
                    value: spec.encoding.y.label,
                    angle: -90,
                    position: "insideLeft",
                    fill: c.chart.axisLabel,
                    fontSize: 10,
                  }
                : undefined
            }
          />
          <ZAxis
            type="number"
            dataKey="z"
            range={isBubble ? [60, 600] : [60, 60]}
            name={sizeField ?? ""}
          />
          <Tooltip {...TOOLTIP_STYLES} cursor={{ strokeDasharray: "3 3" }} formatter={fmt} />
          <Legend wrapperStyle={{ fontSize: 11, color: c.text.muted }} />
          <Scatter data={points} name={spec.encoding.y.label || yField} fill={c.brand.primary} />
          {annotations}
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  if (spec.chart_type === "treemap") {
    const items = data
      .map((row) => ({
        name: String(row[xField] ?? ""),
        size: Number(row[yField] ?? 0),
      }))
      .filter((it) => it.size > 0);
    return (
      <ResponsiveContainer width="100%" height={height}>
        <Treemap
          data={items}
          dataKey="size"
          stroke={c.chart.grid}
          fill={c.brand.primary}
          isAnimationActive={false}
          content={(props: unknown) => {
            const p = props as {
              x: number; y: number; width: number; height: number;
              index: number; name: string; value: number;
            };
            const colorIdx = p.index % 8;
            const showLabel = p.width > 60 && p.height > 22;
            return (
              <g>
                <rect
                  x={p.x}
                  y={p.y}
                  width={p.width}
                  height={p.height}
                  fill={pickColor(colorIdx)}
                  stroke={c.chart.grid}
                />
                {showLabel ? (
                  <text
                    x={p.x + 6}
                    y={p.y + 14}
                    fill={c.text.primary}
                    fontSize={11}
                  >
                    {p.name}
                  </text>
                ) : null}
                {showLabel && p.height > 36 ? (
                  <text
                    x={p.x + 6}
                    y={p.y + 28}
                    fill={c.text.muted}
                    fontSize={10}
                  >
                    {fmt(p.value)}
                  </text>
                ) : null}
              </g>
            );
          }}
        />
      </ResponsiveContainer>
    );
  }

  if (spec.chart_type === "radar") {
    // Radar shape: each row is one axis, optional series field gives multiple actors.
    const wide = seriesField ? pivotToWide(data, xField, yField, seriesField) : null;
    const radarData = wide
      ? wide.rows.map((r) => ({ ...r, _axis: r[xField] }))
      : data.map((r) => ({ _axis: String(r[xField] ?? ""), value: Number(r[yField] ?? 0) }));
    return (
      <ResponsiveContainer width="100%" height={height}>
        <RadarChart data={radarData} outerRadius={Math.min(height * 0.35, 90)}>
          <PolarGrid stroke={c.chart.grid} />
          <PolarAngleAxis dataKey="_axis" tick={{ fill: c.chart.axisTick, fontSize: 11 }} />
          <PolarRadiusAxis tick={{ fill: c.chart.axisTick, fontSize: 10 }} tickFormatter={fmt} />
          <Tooltip {...TOOLTIP_STYLES} formatter={fmt} />
          {wide ? <Legend wrapperStyle={{ fontSize: 11, color: c.text.muted }} /> : null}
          {wide ? (
            wide.series.map((sName, i) => (
              <Radar
                key={sName}
                name={sName}
                dataKey={sName}
                stroke={pickColor(i)}
                fill={pickColor(i)}
                fillOpacity={0.3}
                isAnimationActive={false}
              />
            ))
          ) : (
            <Radar
              name={spec.encoding.y.label || yField}
              dataKey="value"
              stroke={c.brand.primary}
              fill={c.brand.primary}
              fillOpacity={0.3}
              isAnimationActive={false}
            />
          )}
        </RadarChart>
      </ResponsiveContainer>
    );
  }

  if (spec.chart_type === "histogram") {
    // Histogram: bars with no spacing. Agent passes pre-binned (bin_label, count) pairs.
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 16, right: 24, left: 4, bottom: 4 }} barCategoryGap={0}>
          <CartesianGrid strokeDasharray="3 3" stroke={c.chart.grid} />
          <XAxisFor encoding={spec.encoding} yFormat={fmt} />
          <YAxisFor encoding={spec.encoding} yFormat={fmt} />
          <Tooltip {...TOOLTIP_STYLES} cursor={{ fill: "#ffffff10" }} formatter={fmt} />
          <Bar dataKey={yField} fill={c.brand.primary} isAnimationActive={false} />
          {annotations}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (
    spec.chart_type === "line" ||
    spec.chart_type === "area" ||
    spec.chart_type === "stacked_area" ||
    spec.chart_type === "sparkline"
  ) {
    const isStackedArea = spec.chart_type === "stacked_area";
    const isAnyArea = spec.chart_type === "area" || isStackedArea;
    const isSpark = spec.chart_type === "sparkline";
    const wide = seriesField ? pivotToWide(data, xField, yField, seriesField) : null;
    const sparkHeight = isSpark ? 60 : height;
    const Wrapper = isAnyArea ? AreaChart : LineChart;
    return (
      <ResponsiveContainer width="100%" height={sparkHeight}>
        <Wrapper data={wide ? wide.rows : data} margin={{ top: 16, right: 24, left: 4, bottom: 4 }}>
          {!isSpark ? <CartesianGrid strokeDasharray="3 3" stroke={c.chart.grid} /> : null}
          {!isSpark ? <XAxisFor encoding={spec.encoding} yFormat={fmt} /> : null}
          {!isSpark ? <YAxisFor encoding={spec.encoding} yFormat={fmt} /> : null}
          {!isSpark ? <Tooltip {...TOOLTIP_STYLES} formatter={fmt} /> : null}
          {!isSpark && wide ? <Legend wrapperStyle={{ fontSize: 11, color: c.text.muted }} /> : null}
          {wide
            ? wide.series.map((sName, i) =>
                isAnyArea ? (
                  <Area
                    key={sName}
                    type="monotone"
                    dataKey={sName}
                    stackId={isStackedArea ? "a" : undefined}
                    stroke={pickColor(i)}
                    fill={pickColor(i)}
                    fillOpacity={0.35}
                    isAnimationActive={false}
                  />
                ) : (
                  <Line
                    key={sName}
                    type="monotone"
                    dataKey={sName}
                    stroke={pickColor(i)}
                    strokeWidth={2}
                    dot={isSpark ? false : { r: 2 }}
                    isAnimationActive={false}
                  />
                ),
              )
            : isAnyArea ? (
                <Area
                  type="monotone"
                  dataKey={yField}
                  stroke={c.brand.primary}
                  fill={c.brand.primary}
                  fillOpacity={0.3}
                  isAnimationActive={false}
                />
              ) : (
                <Line
                  type="monotone"
                  dataKey={yField}
                  stroke={c.brand.primary}
                  strokeWidth={2}
                  dot={isSpark ? false : { r: 3 }}
                  isAnimationActive={false}
                />
              )}
          {annotations}
        </Wrapper>
      </ResponsiveContainer>
    );
  }

  // bar / stacked_bar / grouped_bar
  const isStacked = spec.chart_type === "stacked_bar";
  const wide = seriesField ? pivotToWide(data, xField, yField, seriesField) : null;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={wide ? wide.rows : data} margin={{ top: 16, right: 24, left: 4, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={c.chart.grid} />
        <XAxisFor encoding={spec.encoding} yFormat={fmt} />
        <YAxisFor encoding={spec.encoding} yFormat={fmt} />
        <Tooltip {...TOOLTIP_STYLES} cursor={{ fill: "#ffffff10" }} formatter={fmt} />
        {wide ? <Legend wrapperStyle={{ fontSize: 11, color: c.text.muted }} /> : null}
        {wide ? (
          wide.series.map((sName, i) => (
            <Bar
              key={sName}
              dataKey={sName}
              fill={pickColor(i)}
              stackId={isStacked ? "a" : undefined}
              radius={isStacked ? undefined : [4, 4, 0, 0]}
              isAnimationActive={false}
            />
          ))
        ) : (
          <Bar
            dataKey={yField}
            fill={c.brand.primary}
            radius={[4, 4, 0, 0]}
            name={spec.encoding.y.label || yField}
            isAnimationActive={false}
          />
        )}
        {annotations}
      </BarChart>
    </ResponsiveContainer>
  );
}
