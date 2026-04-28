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

export interface GPUPoint { quarter: string; units: number; }
export interface RevenuePoint { quarter: string; revenue_b: number; units_implied: number; }

export interface GPUSupplyResponse {
  shipped: GPUPoint[];
  deployed: GPUPoint[];
  inventory: GPUPoint[];
  revenue_estimates: RevenuePoint[];
}

export interface NICShipment { quarter: string; infiniband: number; ethernet: number; }
export interface OpticsShipment { quarter: string; "400g": number; "800g": number; }
export interface NICsOpticsResponse {
  nic_shipments: NICShipment[];
  optics_shipments: OpticsShipment[];
  correlation_score: number;
}

export interface TSMCCapacity {
  quarter: string;
  node_3nm_wafers: number;
  node_5nm_wafers: number;
  utilization_pct: number;
}
export interface TSMCPackaging {
  quarter: string;
  cowos_capacity: number;
  constraint_flag: boolean;
}
export interface TSMCResponse {
  capacity: TSMCCapacity[];
  packaging: TSMCPackaging[];
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
