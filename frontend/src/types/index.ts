export interface PowerRecord {
  company: string;
  region: string;
  state: string;
  lat: number;
  lon: number;
  gw_total: number;
  gw_contracted: number;
  gw_operational: number;
  year: number;
  source: string;
  source_url: string;
  confidence: number;
}

export interface PowerCapacityResponse {
  data: PowerRecord[];
  colors: Record<string, string>;
}

export interface TimeseriesPoint {
  quarter: string;
  gw: number;
}

export interface PowerTimeseriesResponse {
  data: Record<string, TimeseriesPoint[]>;
  colors: Record<string, string>;
}

// Vendor-supply row decoded from the JSON-packed `excerpt` column
// (written by backend/agents/vendor_supply_extractor.py).
export interface VendorSupplyRow {
  company: string;
  filing_date: string | null;
  form_type: string | null;
  accession_number: string | null;
  edgar_url: string | null;
  headline: string | null;
  segment_name: string | null;
  period_end: string | null;
  revenue_usd: number | null;
  inventory_usd: number | null;
  purchase_commitments_usd: number | null;
  customer_concentration_pct: number | null;
  narrative_excerpt: string | null;
  confidence: number | null;
}

export interface VendorTimeseriesPoint {
  period_end: string | null;
  filing_date: string | null;
  segment_name: string | null;
  revenue_usd: number | null;
  headline: string | null;
}

// Legacy shape (still used by mock data); kept for backwards-compat.
export interface GPUPoint { quarter: string; units: number; }
export interface RevenuePoint { quarter: string; revenue_b: number; units_implied: number; }

export interface GPUSupplyResponse {
  // Legacy fields (mock + still emitted as empty arrays in real-data branch)
  shipped?: GPUPoint[];
  deployed?: GPUPoint[];
  inventory?: GPUPoint[] | VendorSupplyRow[];
  revenue_estimates?: RevenuePoint[] | VendorSupplyRow[];
  // New vendor-supply fields
  timeseries?: Record<string, VendorTimeseriesPoint[]>;
  vendors_audited?: string[];
  filings_audited?: number;
}

export interface NICsOpticsResponse {
  nic_shipments?: VendorSupplyRow[];
  optics_shipments?: VendorSupplyRow[];
  correlation_score?: number | null;
  timeseries?: Record<string, VendorTimeseriesPoint[]>;
  vendors_audited?: string[];
  filings_audited?: number;
}

export interface TSMCResponse {
  // Sub-buckets: foundry / OSAT / equipment vendors
  capacity?: VendorSupplyRow[];
  packaging?: VendorSupplyRow[];
  equipment?: VendorSupplyRow[];
  disclosures?: VendorSupplyRow[];
  timeseries?: Record<string, VendorTimeseriesPoint[]>;
  vendors_audited?: string[];
  filings_audited?: number;
}

export interface PermitRecord {
  county: string;
  state: string;
  lat: number;
  lon: number;
  company: string;
  permit_type: string;
  filed_date: string;
  status: string;
  estimated_sqft: number;
  estimated_mw: number;
  source: string;
  source_url: string;
}

// Phase 1.5: Real generator-permit row shape returned by /api/permits/?fuel_type=...
// Mirrors backend `GeneratorPermit` ORM columns plus joined `resolved_company_name`
// and a router-injected `source_url` lifted out of `raw_payload`.
export interface GeneratorPermitDto {
  id: number;
  source: string | null;                 // 'epa_echo', 'pjm', 'tceq', 'va_open_data', 'socrata_ny'
  source_permit_id: string | null;
  facility_name: string | null;
  permittee_raw_name: string | null;     // raw LLC / operator name as filed
  resolved_company_id: number | null;
  resolved_company_name: string | null;  // joined from companies.canonical_name
  site_id: number | null;
  state_code: string | null;
  county_fips: string | null;
  latitude: number | null;
  longitude: number | null;
  rated_mw_total: number | null;         // nameplate MW (canonical column)
  num_units: number | null;
  fuel_type: string | null;              // raw upstream value; may be mixed-case / semicolon-joined
  permit_status: string | null;
  issued_date: string | null;            // ISO date
  expiry_date: string | null;
  frs_id: string | null;
  naics_code: string | null;
  raw_payload: Record<string, unknown> | null;
  confidence: number | null;
  source_url: string | null;             // injected by the API from raw_payload
  created_at: string | null;
  updated_at: string | null;
}

export interface GeneratorPermitsResponse {
  data: GeneratorPermitDto[];
  total: number;
  page: number;
  page_size: number;
  fuel_types_requested: string[] | null;
  sources_included: string[];
}

export interface SiteMilestone {
  date: string;
  label: string;
  pct: number;
  type: "announcement" | "permit" | "construction" | "milestone" | "projected";
}

export interface SatelliteSite {
  name: string;
  company: string;
  lat: number;
  lon: number;
  address: string;
  status: string;
  size_acres: number;
  construction_pct: number;
  announced?: string;
  source?: string;
  source_url?: string;
  milestones?: SiteMilestone[];
  aterio_dc_uid?: string;
  power_capacity_mw?: number;
  state_code?: string;
  county_name?: string;
}

export interface TriangulationRecord {
  region: string;
  contracted_power_gw: number;
  deployed_gpus_k: number;
  gpu_power_demand_gw: number;
  power_gap_gw: number;
  status: "Overbuild" | "Constrained" | "Balanced";
  nic_validation_score: number;
  permit_signal_count: number;
  confidence: number;
}

export interface SourceRecord {
  id: number;
  name: string;
  type: string;
  url: string;
  last_ingested: string;
  records: number;
  pillar: string;
  description: string;
  confidence: number;
}

export interface AgentStatus {
  agent: string;
  status: string;
  last_run: string;
  records_processed: number;
}

// ---------------------------------------------------------------------------
// Q&A streaming events / message shapes
// ---------------------------------------------------------------------------
export type QAEvent =
  | { type: "text_chunk"; content: string }
  | { type: "tool_call"; tool_name: string; args: Record<string, unknown> }
  | { type: "tool_result"; tool_name: string; summary: string; row_count: number }
  | {
      type: "chart_spec";
      chart_type: "bar" | "pie" | "line" | "scatter" | "table";
      x: string;
      y: string;
      series: Array<Record<string, unknown>>;
      title: string;
      source_table: string;
      breakdown_by?: string | null;
      reasoning?: string | null;
    }
  | {
      type: "citation";
      table: string;
      row_id: string | null;
      source_url: string | null;
      label: string;
    }
  | { type: "done" }
  | { type: "error"; message: string };

export interface ChartSpec {
  chart_type: "bar" | "pie" | "line" | "scatter" | "table";
  x: string;
  y: string;
  series: Array<Record<string, unknown>>;
  title: string;
  source_table: string;
  breakdown_by?: string | null;
  reasoning?: string | null;
}

export interface Citation {
  table: string;
  row_id: string | null;
  source_url: string | null;
  label: string;
}

export interface QAMessage {
  role: "user" | "assistant";
  content: string;
  charts?: ChartSpec[];
  citations?: Citation[];
  toolCalls?: Array<{
    tool_name: string;
    args: Record<string, unknown>;
    row_count?: number;
  }>;
  error?: string | null;
}
