"""
Database models for the Datacenter & Power Intelligence Platform.
Implements the canonical schema from 03-architecture-design.md section 3.

All tables use SQLModel. UUIDs for primary keys where specified.
Timestamps are UTC. Indexes per section 4.2 of pipeline architecture.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlmodel import (
    Column,
    Enum,
    Field,
    Index,
    Relationship,
    SQLModel,
    Text,
    UniqueConstraint,
)
from sqlalchemy import BigInteger, Boolean, Column as SAColumn, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CompanyRole(str, enum.Enum):
    """Role enum per 00-DECISIONS-AND-CONSTRAINTS.md section 5.1."""
    provider = "provider"
    provider_backer = "provider_backer"
    end_user = "end_user"
    financing = "financing"
    equipment = "equipment"
    utility = "utility"
    developer = "developer"
    customer = "customer"
    permittee_llc = "permittee_llc"
    permit_parent = "permit_parent"


class SiteStage(str, enum.Enum):
    announcement = "Announcement"
    construction = "Construction"
    activated = "Activated"
    cancelled = "Cancelled"
    withdrawn = "Withdrawn"


class EventType(str, enum.Enum):
    announcement = "announcement"
    permit_filed = "permit_filed"
    construction_start = "construction_start"
    activation = "activation"
    expansion = "expansion"
    cancellation = "cancellation"


class IngestionStatus(str, enum.Enum):
    running = "running"
    success = "success"
    partial_failure = "partial_failure"
    failure = "failure"


class CoverageStatus(str, enum.Enum):
    full = "full"
    partial = "partial"
    federal_baseline = "federal_baseline"
    pending = "pending"
    unavailable = "unavailable"


class LlmRunStatus(str, enum.Enum):
    success = "success"
    fallback = "fallback"
    error = "error"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    escalated = "escalated"


# ---------------------------------------------------------------------------
# Helper columns
# ---------------------------------------------------------------------------

def _ts_now():
    """Default factory for timestamp columns."""
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Sites (full 73-col mirror of Aterio CSV) — 03-architecture-design.md section 3
# ---------------------------------------------------------------------------

class Site(SQLModel, table=True):
    __tablename__ = "sites"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))

    # Identity
    aterio_dc_uid: Optional[str] = Field(default=None, max_length=255, index=True, unique=True)
    building_name: Optional[str] = Field(default=None)
    aterio_campus_uid: Optional[str] = Field(default=None, max_length=255, index=True)
    campus_name: Optional[str] = Field(default=None)

    # Status
    stage: Optional[str] = Field(default=None, max_length=50)
    pct_construction: Optional[float] = Field(default=None)

    # Provider (operator)
    provider_name: Optional[str] = Field(default=None, index=True)
    provider_ticker: Optional[str] = Field(default=None, max_length=50)
    provider_bloomberg_ticker: Optional[str] = Field(default=None, max_length=50)
    provider_public_private: Optional[str] = Field(default=None, max_length=100)
    provider_backed_by: Optional[str] = Field(default=None)
    provider_url: Optional[str] = Field(default=None)

    # End user
    end_user_companies: Optional[str] = Field(default=None)

    # Equipment & financing
    construction_equipment_provider_companies: Optional[str] = Field(default=None)
    project_financing_companies: Optional[str] = Field(default=None)

    # Geography
    full_address: Optional[str] = Field(default=None)
    zip_code: Optional[str] = Field(default=None, max_length=20)
    county_fips: Optional[str] = Field(default=None, max_length=10, index=True)
    county_name: Optional[str] = Field(default=None)
    city_name: Optional[str] = Field(default=None)
    place_fips_code: Optional[str] = Field(default=None, max_length=10)
    state_code: Optional[str] = Field(default=None, max_length=2, index=True)
    state_name: Optional[str] = Field(default=None)
    country_code: Optional[str] = Field(default=None, max_length=5)
    country_name: Optional[str] = Field(default=None)
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)

    # Physical
    site_acreage: Optional[float] = Field(default=None)
    tot_facility_space_sqft: Optional[float] = Field(default=None)
    tot_datacenter_space_sqft: Optional[float] = Field(default=None)

    # Power capacity (MW)
    prov_pub_tot_power_capacity_mw: Optional[float] = Field(default=None)
    aterio_est_mw: Optional[float] = Field(default=None)
    aterio_est_mw_lower: Optional[float] = Field(default=None)
    aterio_est_mw_upper: Optional[float] = Field(default=None)
    power_capacity_mw: Optional[float] = Field(default=None, index=True)  # SELECTED_POWER_CAPACITY_MW

    # Economics
    tot_project_cost: Optional[float] = Field(default=None)
    avg_market_power_cost: Optional[float] = Field(default=None)
    yearly_pue: Optional[float] = Field(default=None)
    tot_num_generators: Optional[int] = Field(default=None)

    # Timeline
    announced_date: Optional[str] = Field(default=None)
    construction_start_date: Optional[str] = Field(default=None)
    construction_finished_date: Optional[str] = Field(default=None)
    activation_date: Optional[str] = Field(default=None)
    estimated_active_date_by: Optional[str] = Field(default=None)
    cancelled_date: Optional[str] = Field(default=None)
    project_withdrawn_date: Optional[str] = Field(default=None)
    latest_satellite_picture_date: Optional[str] = Field(default=None)

    # Utility / grid
    utility_name: Optional[str] = Field(default=None)
    utility_public_private: Optional[str] = Field(default=None, max_length=100)
    utility_ticker: Optional[str] = Field(default=None, max_length=50)
    bal_auth_abbr: Optional[str] = Field(default=None, max_length=50)
    bal_auth_name: Optional[str] = Field(default=None)
    bal_auth_subregion_code: Optional[str] = Field(default=None, max_length=50)
    bal_auth_subregion_name: Optional[str] = Field(default=None)

    # Source links
    datasheet_url: Optional[str] = Field(default=None)
    map_url: Optional[str] = Field(default=None)
    permit_url: Optional[str] = Field(default=None)
    capex_url: Optional[str] = Field(default=None)

    # Confidence & flags
    project_execution_likelihood: Optional[str] = Field(default=None, max_length=50)  # "High"/"Medium"/"Low"
    is_ai_facility: Optional[bool] = Field(default=None)
    flg_btm_onsite_power_generation: Optional[bool] = Field(default=None)
    notes: Optional[str] = Field(default=None, sa_column=SAColumn(Text))

    # Lineage
    record_created_at: Optional[datetime] = Field(default=None)
    record_updated_at: Optional[datetime] = Field(default=None)
    updated_at_source: Optional[datetime] = Field(default=None)  # UPDATED_AT from Aterio

    # Internal timestamps
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Events (from Data Centers Events sheet, 957 rows x 48 cols)
# ---------------------------------------------------------------------------

class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    aterio_dc_uid: Optional[str] = Field(default=None, max_length=255, index=True)
    event_type: Optional[str] = Field(default=None, max_length=50)
    event_date: Optional[date] = Field(default=None, index=True)
    event_description: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    source_url: Optional[str] = Field(default=None)
    payload: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Energy Projects (from Energy Project Inventory, 1695 rows x 65 cols)
# ---------------------------------------------------------------------------

class EnergyProject(SQLModel, table=True):
    __tablename__ = "energy_projects"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    project_name: Optional[str] = Field(default=None)
    flg_btm_project: Optional[bool] = Field(default=None)
    developer_companies: Optional[str] = Field(default=None)
    developer_ticker: Optional[str] = Field(default=None, max_length=20)
    eia_entity_ids: Optional[list] = Field(default=None, sa_column=SAColumn(JSONB))
    eia_entity_names: Optional[str] = Field(default=None)
    construction_equipment_provider_companies: Optional[str] = Field(default=None)
    project_financing_companies: Optional[str] = Field(default=None)
    customer_companies: Optional[str] = Field(default=None)
    tot_contracted_power_mw: Optional[float] = Field(default=None)
    tot_project_cost: Optional[float] = Field(default=None)
    project_footprint_acreage: Optional[float] = Field(default=None)
    site_boundary_acreage: Optional[float] = Field(default=None)
    # Remaining 50+ columns stored as JSONB
    payload: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    state_code: Optional[str] = Field(default=None, max_length=2, index=True)
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Companies Canonical Table
# ---------------------------------------------------------------------------

class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    canonical_name: str = Field(index=True)
    short_name: Optional[str] = Field(default=None)
    ticker: Optional[str] = Field(default=None, max_length=20, index=True)
    cik: Optional[str] = Field(default=None, max_length=20, index=True)
    parent_company_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger))
    public_private: Optional[str] = Field(default=None, max_length=20)
    aliases: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Company Aliases Bridge — UNIQUE(source, raw_name)
# ---------------------------------------------------------------------------

class CompanyAlias(SQLModel, table=True):
    __tablename__ = "company_aliases"
    __table_args__ = (
        UniqueConstraint("source", "raw_name", name="uq_company_alias_source_rawname"),
    )

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    company_id: int = Field(sa_column=SAColumn(BigInteger, index=True))
    source: str = Field(max_length=100)
    raw_name: str
    match_method: Optional[str] = Field(default=None, max_length=50)
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    evidence: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Site Aliases Bridge — UNIQUE(source, source_record_id)
# ---------------------------------------------------------------------------

class SiteAlias(SQLModel, table=True):
    __tablename__ = "site_aliases"
    __table_args__ = (
        UniqueConstraint("source", "source_record_id", name="uq_site_alias_source_recid"),
    )

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    site_id: int = Field(sa_column=SAColumn(BigInteger, index=True))
    source: str = Field(max_length=100)
    source_record_id: str
    match_method: Optional[str] = Field(default=None, max_length=50)
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Site <-> Company Associations (Role Edges) — UNIQUE(site_id, company_id, role, source)
# ---------------------------------------------------------------------------

class SiteCompanyAssociation(SQLModel, table=True):
    __tablename__ = "site_company_associations"
    __table_args__ = (
        UniqueConstraint("site_id", "company_id", "role", "source", name="uq_site_company_role_source"),
    )

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    site_id: int = Field(sa_column=SAColumn(BigInteger, index=True))
    company_id: int = Field(sa_column=SAColumn(BigInteger, index=True))
    role: str = Field(max_length=30)  # CompanyRole enum value
    source: str = Field(max_length=100)
    source_record_id: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    mw_share: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric))
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Generator Permits — per pipeline architecture section 7.5.3
# ---------------------------------------------------------------------------

class GeneratorPermit(SQLModel, table=True):
    __tablename__ = "generator_permits"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    source: str = Field(max_length=100, index=True)  # epa_echo, tceq, etc.
    source_permit_id: Optional[str] = Field(default=None, max_length=255)
    facility_name: Optional[str] = Field(default=None)
    permittee_raw_name: Optional[str] = Field(default=None, index=True)
    resolved_company_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger))
    site_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, index=True))
    state_code: Optional[str] = Field(default=None, max_length=2, index=True)
    county_fips: Optional[str] = Field(default=None, max_length=10)
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)
    rated_mw_total: Optional[float] = Field(default=None)
    num_units: Optional[int] = Field(default=None)
    fuel_type: Optional[str] = Field(default=None, max_length=100)
    permit_status: Optional[str] = Field(default=None, max_length=100)
    issued_date: Optional[date] = Field(default=None)
    expiry_date: Optional[date] = Field(default=None)
    frs_id: Optional[str] = Field(default=None, max_length=100, index=True)
    naics_code: Optional[str] = Field(default=None, max_length=50)
    raw_payload: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Permit Parent Review Queue — per 03-architecture-design.md section 6.5.3
# ---------------------------------------------------------------------------

class PermitParentReviewQueue(SQLModel, table=True):
    __tablename__ = "permit_parent_review_queue"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    generator_permit_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger))
    permittee_raw_name: str
    candidate_parents: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    agent_run_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger))
    status: str = Field(default="pending", max_length=20)
    reviewer_id: Optional[str] = Field(default=None, max_length=100)
    reviewer_decision: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    created_at: datetime = Field(default_factory=_ts_now)
    decided_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# Ingestion Runs — audit trail for adapter runs
# ---------------------------------------------------------------------------

class IngestionRun(SQLModel, table=True):
    __tablename__ = "ingestion_runs"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    adapter_name: str = Field(max_length=100, index=True)
    adapter_version: Optional[str] = Field(default=None, max_length=50)
    started_at: datetime = Field(default_factory=_ts_now)
    completed_at: Optional[datetime] = Field(default=None)
    status: str = Field(default="running", max_length=50)
    records_fetched: int = Field(default=0)
    records_normalized: int = Field(default=0)
    records_stored: int = Field(default=0)
    records_skipped: int = Field(default=0)
    trigger: Optional[str] = Field(default=None, max_length=50)
    error_log: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    config_snapshot: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))


# ---------------------------------------------------------------------------
# Data Lineage — per-record audit trail
# ---------------------------------------------------------------------------

class DataLineage(SQLModel, table=True):
    __tablename__ = "data_lineage"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    table_name: str = Field(max_length=100, index=True)
    record_id: int = Field(sa_column=SAColumn(BigInteger))
    ingestion_run_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger))
    source_url: Optional[str] = Field(default=None)
    retrieved_at: Optional[datetime] = Field(default=None)
    parser_version: Optional[str] = Field(default=None, max_length=50)
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    raw_blob_ref: Optional[str] = Field(default=None)
    transformation: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Data Coverage — per-pillar per-state coverage tracking
# ---------------------------------------------------------------------------

class DataCoverage(SQLModel, table=True):
    __tablename__ = "data_coverage"
    __table_args__ = (
        UniqueConstraint("pillar", "state_code", "source", name="uq_coverage_pillar_state_source"),
    )

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    pillar: str = Field(max_length=50, index=True)
    state_code: str = Field(max_length=10, index=True)
    source: str = Field(max_length=100)
    coverage_status: str = Field(max_length=30)
    record_count: int = Field(default=0)
    last_ingested_at: Optional[datetime] = Field(default=None)
    freshness_sla_hours: Optional[int] = Field(default=None)
    notes: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    roadmap: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# LLM Extraction Runs — per 03-architecture-design.md section 6.5.3
# UNIQUE(agent_name, input_hash)
# ---------------------------------------------------------------------------

class LlmExtractionRun(SQLModel, table=True):
    __tablename__ = "llm_extraction_runs"
    __table_args__ = (
        UniqueConstraint("agent_name", "input_hash", name="uq_llm_run_agent_inputhash"),
        Index("idx_llm_runs_agent_created", "agent_name", "created_at"),
    )

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    agent_name: str = Field(max_length=100)
    model: str = Field(max_length=100)
    prompt_version: str = Field(max_length=100)
    input_hash: str = Field(max_length=100)
    input_excerpt: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    output: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    tool_calls: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    tokens_prompt: Optional[int] = Field(default=None)
    tokens_completion: Optional[int] = Field(default=None)
    latency_ms: Optional[int] = Field(default=None)
    status: str = Field(max_length=20)
    error_detail: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    fallback_path: Optional[str] = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Transcript Metrics — per pipeline architecture
# ---------------------------------------------------------------------------

class TranscriptMetric(SQLModel, table=True):
    __tablename__ = "transcript_metrics"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    company_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, index=True))
    ticker: Optional[str] = Field(default=None, max_length=20)
    period: Optional[str] = Field(default=None, max_length=20)
    period_type: Optional[str] = Field(default=None, max_length=20)
    metric_name: str = Field(max_length=100)
    metric_category: Optional[str] = Field(default=None, max_length=50)
    numeric_value: Optional[float] = Field(default=None)
    text_value: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    source_url: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    parser_version: Optional[str] = Field(default=None, max_length=50)
    retrieved_at: Optional[datetime] = Field(default=None)
    payload: Optional[dict] = Field(default=None, sa_column=SAColumn(JSONB))
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Curated Deals — migrate the existing curated_deals.py 22-row dict
# ---------------------------------------------------------------------------

class CuratedDeal(SQLModel, table=True):
    __tablename__ = "curated_deals"

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    legacy_id: str = Field(max_length=100, unique=True, index=True)
    buyer: str
    seller: Optional[str] = Field(default=None)
    deal_type: Optional[str] = Field(default=None, max_length=100)
    energy_source: Optional[str] = Field(default=None, max_length=100)
    capacity_mw: Optional[int] = Field(default=None)
    location: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None, max_length=10)
    lat: Optional[float] = Field(default=None)
    lon: Optional[float] = Field(default=None)
    announced_date: Optional[str] = Field(default=None, max_length=20)
    status: Optional[str] = Field(default=None, max_length=100)
    duration_years: Optional[int] = Field(default=None)
    headline: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    excerpt: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    source_type: Optional[str] = Field(default=None, max_length=100)
    source_url: Optional[str] = Field(default=None)
    edgar_url: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    data_source: Optional[str] = Field(default=None)
    energy_contract_mwh_million: Optional[float] = Field(default=None)
    note: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    created_at: datetime = Field(default_factory=_ts_now)
    updated_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# EDGAR Extractions — Phase 1A staging table
# ---------------------------------------------------------------------------

class EdgarExtraction(SQLModel, table=True):
    """EDGAR-extracted records -- Phase 1A staging table.

    Stores raw EDGAR extraction results before entity resolution links them
    to companies/sites.  Phase 1C LLM extractor replaces regex but writes
    here too.
    """
    __tablename__ = "edgar_extractions"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_edgar_extraction_accession"),
    )

    id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True))
    cik: str = Field(max_length=20, index=True)
    accession_number: str = Field(max_length=30)
    form_type: str = Field(max_length=10)
    filing_date: Optional[date] = Field(default=None, index=True)
    item_codes: Optional[str] = Field(default=None, max_length=100)
    edgar_url: Optional[str] = Field(default=None)
    capacity_mw: Optional[float] = Field(default=None)
    energy_source: Optional[str] = Field(default=None, max_length=50)
    buyer_raw: Optional[str] = Field(default=None)
    seller_raw: Optional[str] = Field(default=None)
    excerpt: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    parser_version: str = Field(default="regex-v1", max_length=50)
    confidence: Optional[float] = Field(default=None, sa_column=SAColumn(Numeric(3, 2)))
    retrieved_at: datetime = Field(default_factory=_ts_now)
    # FK lookups (populated by entity resolution after extraction)
    buyer_company_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger))
    seller_company_id: Optional[int] = Field(default=None, sa_column=SAColumn(BigInteger))
    # Pillar tag — distinguishes 'power_contract' (existing extractor) from
    # 'vendor_supply' (Phase 2 supplier-insights extractor). Plain VARCHAR
    # rather than enum to keep migrations simple; routers filter on this.
    pillar: Optional[str] = Field(default=None, max_length=32, index=True)
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Brief Runs -- Phase 1C weekly LLM-generated intelligence briefings
# ---------------------------------------------------------------------------

class BriefRun(SQLModel, table=True):
    """Persisted weekly briefing produced by the LLM reasoning agent.

    One row per generation run. The frontend reads /api/brief/latest, which
    returns the most-recent row by generated_at.
    """
    __tablename__ = "brief_runs"

    id: Optional[int] = Field(
        default=None,
        sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True),
    )
    generated_at: datetime = Field(default_factory=_ts_now)
    period_start: date = Field(...)
    period_end: date = Field(...)
    markdown: str = Field(sa_column=SAColumn(Text, nullable=False))
    model: Optional[str] = Field(default=None, max_length=100)
    prompt_version: Optional[str] = Field(default=None, max_length=50)
    bullet_count: Optional[int] = Field(default=None)
    tokens_in: Optional[int] = Field(default=None)
    tokens_out: Optional[int] = Field(default=None)
    latency_ms: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Anomalies -- Phase 2 WoW deviation detector (AC5)
# ---------------------------------------------------------------------------

class Anomaly(SQLModel, table=True):
    """One row per detected anomaly: a metric whose week-over-week change
    exceeds 2 standard deviations of the trailing 12-week distribution.

    metric_kind     -- e.g. "pjm_queue_mw", "permit_filings_va", "edgar_capacity_mw"
    dimension       -- optional sub-bucket like state code or fuel type ("ALL" if N/A)
    period_end      -- ISO week-ending date this observation belongs to
    value           -- the observed metric value for the week
    baseline_mean   -- trailing-window mean (excluding the current week)
    baseline_stddev -- trailing-window standard deviation
    z_score         -- (value - baseline_mean) / baseline_stddev
    direction       -- "spike" (z > 0) | "drop" (z < 0)
    """
    __tablename__ = "anomalies"
    __table_args__ = (
        UniqueConstraint(
            "metric_kind", "dimension", "period_end",
            name="uq_anomaly_metric_dim_period",
        ),
        Index("ix_anomaly_period_end", "period_end"),
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True),
    )
    metric_kind: str = Field(max_length=50, index=True)
    dimension: str = Field(default="ALL", max_length=20)
    period_end: date
    value: float
    baseline_mean: Optional[float] = Field(default=None)
    baseline_stddev: Optional[float] = Field(default=None)
    z_score: Optional[float] = Field(default=None)
    direction: str = Field(default="spike", max_length=10)
    sample_size: Optional[int] = Field(default=None)
    note: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    detected_at: datetime = Field(default_factory=_ts_now)
    created_at: datetime = Field(default_factory=_ts_now)


# ---------------------------------------------------------------------------
# Press Releases -- Phase 2 IR scraper (AC3)
# ---------------------------------------------------------------------------

class PressRelease(SQLModel, table=True):
    """IR-page press releases that mention power, datacenter, capacity, etc.

    company_canon  -- canonical company name (Microsoft, Amazon, ...)
    source_url     -- direct URL to the release (NOT the IR index)
    published_date -- ISO date as published; falls back to retrieved_at date
    title          -- release headline
    summary        -- LLM- or heuristic-extracted 1-3 sentence summary
    matched_terms  -- which keywords triggered (datacenter, power, GW, etc.)
    """
    __tablename__ = "press_releases"
    __table_args__ = (
        UniqueConstraint("source_url", name="uq_press_release_url"),
        Index("ix_press_release_company_date", "company_canon", "published_date"),
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=SAColumn(BigInteger, primary_key=True, autoincrement=True),
    )
    company_canon: str = Field(max_length=100, index=True)
    source_url: str = Field(max_length=1024)
    published_date: Optional[date] = Field(default=None, index=True)
    title: str = Field(max_length=500)
    summary: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    matched_terms: Optional[str] = Field(default=None, max_length=300)
    excerpt: Optional[str] = Field(default=None, sa_column=SAColumn(Text))
    parser_version: str = Field(default="press-v1", max_length=50)
    retrieved_at: datetime = Field(default_factory=_ts_now)
    # Pillar tag — see EdgarExtraction.pillar; valid values today are
    # 'power_contract' or 'vendor_supply'.
    pillar: Optional[str] = Field(default=None, max_length=32, index=True)
    created_at: datetime = Field(default_factory=_ts_now)
