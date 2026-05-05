/**
 * ChartSpec v1 — TypeScript mirror of
 * `backend/agents/insights/specs/chart_spec.schema.json`.
 *
 * Hand-written (no codegen) per the W7.3 brief. Keep these types in lockstep
 * with the JSON schema; if the schema changes, update here in the same PR.
 *
 * Renderer contract (PRD §5.2):
 *   - `data` is inline and <=500 rows. Frontend never re-fetches.
 *   - `data_source.row_hash` is server-validated; the frontend treats it as
 *     opaque provenance.
 */

export type ChartType =
  | "line"
  | "bar"
  | "stacked_bar"
  | "grouped_bar"
  | "area"
  | "stacked_area"
  | "scatter"
  | "pie"
  | "sparkline"
  | "kpi_tile";

export type DataSourceKind = "db_query" | "router_call" | "chart_data";

export interface DataSource {
  kind: DataSourceKind;
  /** Free-form spec block — shape depends on `kind`. */
  spec: Record<string, unknown>;
  rows: number;
  /** ISO8601 datetime. */
  fetched_at: string;
  /** sha256(canonical_sort(rows)); 64 hex chars. */
  row_hash: string;
}

export interface XEncoding {
  field: string;
  type: "category" | "time" | "quantitative";
  label?: string | null;
  tick_format?: string | null;
}

export interface YEncoding {
  field: string;
  /** Schema fixes y to "quantitative". */
  type?: "quantitative";
  label?: string | null;
  tick_format?: string | null;
}

export interface SeriesEncoding {
  field: string;
}

export interface ColorEncoding {
  field?: string | null;
  scheme?: "categorical" | "sequential" | null;
}

export interface SizeEncoding {
  field: string;
}

export interface Encoding {
  x: XEncoding;
  y: YEncoding;
  series?: SeriesEncoding | null;
  color?: ColorEncoding | null;
  /** Scatter-only. */
  size?: SizeEncoding | null;
}

export interface Annotation {
  type: "line" | "band" | "point";
  value: string | number;
  label: string;
}

export type YUnit = "GW" | "MW" | "USD" | "count" | "%";

export interface Styling {
  palette?: "oci_brand";
  y_unit?: YUnit | null;
  /** 0..6 inclusive. */
  y_precision?: number | null;
}

export interface ChartSpec {
  /** Pattern: ^c_[0-9a-f]{8}$ */
  chart_id: string;
  chart_type: ChartType;
  title: string;
  subtitle?: string | null;
  data_source: DataSource;
  /** Inline rows; <=500. */
  data: Array<Record<string, unknown>>;
  encoding: Encoding;
  annotations?: Annotation[] | null;
  styling?: Styling | null;
}
