"""Hypothesizer module for AI Insights automation (Phase 1).

Implements two public coroutines:

    build_factpack(db)            -> FactPack
    synthesize_insights(fp, n=7)  -> list[InsightOutput]

Per architecture §3 (Hypothesizer module) and §4 (Orchestrator rewrite):
the hypothesizer pulls a small, deterministic FactPack from the warehouse,
then makes a single LLM call to synthesize a structured list of insights
that reference back into the FactPack via row_ids. Phase 1 scope ends here
— the orchestrator wires it into the existing SSE flow.

Field-name notes (architecture skeletons drift from real models):
    - Anomaly: filter on period_end == today; fall back to date(detected_at).
    - EnergyProject: group by developer_companies (no parent_company_id).
    - DataCoverage: coverage_status (NOT status).
    - BuildingPermit holds county-level building permits (separate from
      generator_permits / Event).
    - GeneratorPermit with source='epa_echo' is the EPA ECHO landing table.

D7 ceiling: prompt+completion tokens are accounted and warned (never raised)
when above HYPOTHESIZER_TOKEN_CEILING.

Determinism for tests: setting AI_INSIGHTS_FAKE_LLM in the environment to a
JSON string of the form {"insights":[...]} short-circuits the LLM call and
returns the parsed list directly.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Anomaly,
    BuildingPermit,
    DataCoverage,
    EdgarExtraction,
    EnergyProject,
    GeneratorPermit,
    Site,
)
from llm.client import MODELS, llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

FACT_PACK_MAX_ROWS_PER_SECTION = 12
# 11 sections × 12 = 132 worst case; cap at 132 so every section can be heard
# by the LLM. Prompt tokens grow ~linearly with row count — at 132 rows we land
# around 4-5K prompt tokens, well under the 30K hard ceiling.
FACT_PACK_MAX_TOTAL_ROWS = 132
HYPOTHESIZER_TOKEN_CEILING = 80_000  # D7 hard cap (warn-only) — bumped Phase 2 (FR-X.5: 30K -> 80K) for the agentic loop's multi-turn budget
PROMPT_VERSION = "ai-insights/hypothesizer-v1"

# Fixed UTC clock helper.
def _utcnow() -> datetime:
    # tz-naive — DB columns (energy_projects.created_at, generator_permits.created_at)
    # are TIMESTAMP WITHOUT TIME ZONE, so asyncpg rejects tz-aware values in WHERE.
    return datetime.utcnow()


def _today_utc() -> date:
    return _utcnow().date()


# ---------------------------------------------------------------------------
# Pydantic schema (architecture §3.2)
# ---------------------------------------------------------------------------


class FactRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_id: str
    entity: Optional[str] = None
    metric: Optional[str] = None
    value: Optional[Any] = None
    delta: Optional[float] = None
    source_url: Optional[str] = None
    detail: dict = Field(default_factory=dict)


class FactSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    rows: list[FactRow] = Field(default_factory=list)
    error: Optional[str] = None


class FactPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    sections: list[FactSection] = Field(default_factory=list)

    def lookup(self, row_ids: list[str]) -> list[FactRow]:
        """Return FactRows whose row_id is in the input list, preserving order."""
        index: dict[str, FactRow] = {}
        for section in self.sections:
            for row in section.rows:
                index[row.row_id] = row
        out: list[FactRow] = []
        for rid in row_ids:
            row = index.get(rid)
            if row is not None:
                out.append(row)
        return out

    def to_compact_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            default=str,
            separators=(",", ":"),
        )

    def total_rows(self) -> int:
        return sum(len(s.rows) for s in self.sections)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline_draft: str
    supporting_row_ids: list[str] = Field(default_factory=list)
    confidence_signal: str  # "weak" | "moderate" | "strong"
    needs_drilldown: bool = False


class InsightOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    body: str
    confidence_signal: str  # "weak" | "moderate" | "strong"
    materiality: str  # "low" | "medium" | "high"
    supporting_row_ids: list[str] = Field(default_factory=list)
    # LLM-picked chart shape; orchestrator falls back to "bar" when omitted /
    # invalid. Set to "none" to suppress the chart for this insight (e.g. when
    # the supporting rows are not naturally chartable).
    chart_type: Optional[str] = None
    chart_y_label: Optional[str] = None


# ---------------------------------------------------------------------------
# Defensive query helper (mirrors weekly_brief._safe_query)
# ---------------------------------------------------------------------------


async def _safe_query(db: AsyncSession, label: str, stmt) -> list:
    """Run a SELECT defensively; on any error log + return []."""
    try:
        result = await db.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning(
            "ai_insights.hypothesizer.query_failed",
            extra={"label": label, "error": str(exc)},
        )
        return []


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _row_id(section_name: str, idx: int) -> str:
    return f"{section_name}:{idx}"


def _cap(rows: list[FactRow]) -> list[FactRow]:
    return rows[:FACT_PACK_MAX_ROWS_PER_SECTION]


async def _section_top_capacity_movers_24h(db: AsyncSession) -> FactSection:
    name = "top_capacity_movers_24h"
    desc = "EnergyProject rows created or updated in the last 30 days, ordered by contracted MW."
    cutoff = _utcnow() - timedelta(days=30)
    stmt = (
        select(EnergyProject)
        .where(
            or_(
                EnergyProject.created_at >= cutoff,
                EnergyProject.updated_at >= cutoff,
            )
        )
        .order_by(EnergyProject.tot_contracted_power_mw.desc().nulls_last())
        .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
    )
    raw = await _safe_query(db, name, stmt)
    rows: list[FactRow] = []
    for i, p in enumerate(raw):
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=p.project_name,
                metric="contracted_mw",
                value=p.tot_contracted_power_mw,
                source_url=None,
                detail={
                    "state": p.state_code,
                    "developer": p.developer_companies,
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_new_permits_24h(db: AsyncSession) -> FactSection:
    name = "new_permits_24h"
    desc = "BuildingPermit rows issued or applied for in the last 30 days."
    today = _today_utc()
    cutoff = today - timedelta(days=30)
    stmt = (
        select(BuildingPermit)
        .where(
            or_(
                BuildingPermit.issued_date >= cutoff,
                BuildingPermit.applied_date >= cutoff,
            )
        )
        .order_by(BuildingPermit.issued_date.desc().nulls_last())
        .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
    )
    raw = await _safe_query(db, name, stmt)
    rows: list[FactRow] = []
    for i, p in enumerate(raw):
        entity = f"{p.county or ''}, {p.state or ''}".strip(", ") or None
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=entity,
                metric=p.permit_type,
                value=p.permit_status,
                source_url=None,
                detail={
                    "applicant": p.applicant_name,
                    "jurisdiction": p.jurisdiction,
                    "valuation_usd": p.valuation_usd,
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_anomalies_today(db: AsyncSession) -> FactSection:
    name = "anomalies_today"
    desc = "Anomaly rows from the last 30 days, ordered by absolute z-score."
    today = _today_utc()
    cutoff = today - timedelta(days=30)
    stmt_period = (
        select(Anomaly)
        .where(Anomaly.period_end >= cutoff)
        .order_by(func.abs(Anomaly.z_score).desc())
        .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
    )
    raw = await _safe_query(db, f"{name}.period_end", stmt_period)
    if not raw:
        # Fallback: rows detected within the window even if period_end is older.
        stmt_detected = (
            select(Anomaly)
            .where(func.date(Anomaly.detected_at) >= cutoff)
            .order_by(func.abs(Anomaly.z_score).desc())
            .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
        )
        raw = await _safe_query(db, f"{name}.detected_at", stmt_detected)
    rows: list[FactRow] = []
    for i, a in enumerate(raw):
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=a.dimension,
                metric=a.metric_kind,
                value=a.value,
                delta=a.z_score,
                source_url=None,
                detail={
                    "direction": a.direction,
                    "baseline_mean": a.baseline_mean,
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_edgar_capacity_mentions_7d(db: AsyncSession) -> FactSection:
    name = "edgar_capacity_mentions_7d"
    desc = "EdgarExtraction rows from the last 90 days with a non-null capacity_mw."
    cutoff = (_utcnow() - timedelta(days=90)).date()
    stmt = (
        select(EdgarExtraction)
        .where(
            and_(
                EdgarExtraction.filing_date >= cutoff,
                EdgarExtraction.capacity_mw.isnot(None),
            )
        )
        .order_by(EdgarExtraction.capacity_mw.desc())
        .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
    )
    raw = await _safe_query(db, name, stmt)
    rows: list[FactRow] = []
    for i, x in enumerate(raw):
        buyer = x.buyer_canonical or x.buyer_raw
        seller = x.seller_canonical or x.seller_raw
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=buyer,
                metric="capacity_mw",
                value=x.capacity_mw,
                source_url=x.edgar_url,
                detail={
                    "seller": seller,
                    "energy_source": x.energy_source,
                    "filing_date": x.filing_date.isoformat() if x.filing_date else None,
                    "excerpt": (x.excerpt or "")[:200],
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_epa_echo_new_records_24h(db: AsyncSession) -> FactSection:
    name = "epa_echo_new_records_24h"
    desc = "GeneratorPermit rows from EPA ECHO created or updated in the last 30 days."
    cutoff = _utcnow() - timedelta(days=30)
    # Adapter upserts re-store rows without bumping created_at, so OR updated_at
    # to surface re-touched records.
    stmt = (
        select(GeneratorPermit)
        .where(
            and_(
                GeneratorPermit.source == "epa_echo",
                or_(
                    GeneratorPermit.created_at >= cutoff,
                    GeneratorPermit.updated_at >= cutoff,
                ),
            )
        )
        .order_by(GeneratorPermit.rated_mw_total.desc().nulls_last())
        .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
    )
    raw = await _safe_query(db, name, stmt)
    rows: list[FactRow] = []
    for i, g in enumerate(raw):
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=g.facility_name,
                metric="rated_mw_total",
                value=g.rated_mw_total,
                source_url=None,
                detail={
                    "state": g.state_code,
                    "permittee": g.permittee_raw_name,
                    "fuel": g.fuel_type,
                    "permit_status": g.permit_status,
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_coverage_gaps(db: AsyncSession) -> FactSection:
    name = "coverage_gaps"
    desc = "DataCoverage rows whose coverage_status is 'partial', stalest first."
    stmt = (
        select(DataCoverage)
        .where(DataCoverage.coverage_status == "partial")
        .order_by(DataCoverage.last_ingested_at.asc().nulls_first())
        .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
    )
    raw = await _safe_query(db, name, stmt)
    rows: list[FactRow] = []
    for i, c in enumerate(raw):
        entity = f"{c.pillar}/{c.state_code}/{c.source}"
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=entity,
                metric="coverage_status",
                value=c.coverage_status,
                source_url=None,
                detail={
                    "record_count": c.record_count,
                    "last_ingested_at": c.last_ingested_at.isoformat() if c.last_ingested_at else None,
                    "freshness_sla_hours": c.freshness_sla_hours,
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_top_companies_by_delta_7d(db: AsyncSession) -> FactSection:
    """Top developers by 7-day capacity delta.

    Two-CTE pattern over energy_projects, grouped by developer_companies
    (the model has no parent_company_id). curr_mw is the sum of
    tot_contracted_power_mw for projects updated in the last 7 days;
    prior_mw is the sum for projects updated in the prior 7-14 day window.
    """
    name = "top_companies_by_delta_7d"
    desc = "Top developers by week-over-week change in contracted MW."
    sql = text(
        """
        WITH curr AS (
            SELECT developer_companies AS dev,
                   COALESCE(SUM(tot_contracted_power_mw), 0) AS mw
            FROM energy_projects
            WHERE developer_companies IS NOT NULL
              AND updated_at >= :curr_start
            GROUP BY developer_companies
        ),
        prior AS (
            SELECT developer_companies AS dev,
                   COALESCE(SUM(tot_contracted_power_mw), 0) AS mw
            FROM energy_projects
            WHERE developer_companies IS NOT NULL
              AND updated_at >= :prior_start
              AND updated_at <  :curr_start
            GROUP BY developer_companies
        )
        SELECT c.dev AS dev,
               c.mw AS curr_mw,
               COALESCE(p.mw, 0) AS prior_mw,
               (c.mw - COALESCE(p.mw, 0)) AS delta
        FROM curr c
        LEFT JOIN prior p ON p.dev = c.dev
        ORDER BY delta DESC NULLS LAST
        LIMIT :limit
        """
    )
    now = _utcnow()
    curr_start = now - timedelta(days=7)
    prior_start = now - timedelta(days=14)
    rows: list[FactRow] = []
    try:
        result = await db.execute(
            sql,
            {
                "curr_start": curr_start,
                "prior_start": prior_start,
                "limit": FACT_PACK_MAX_ROWS_PER_SECTION,
            },
        )
        records = list(result.mappings().all())
    except Exception as exc:
        logger.warning(
            "ai_insights.hypothesizer.query_failed",
            extra={"label": name, "error": str(exc)},
        )
        records = []
    for i, r in enumerate(records):
        curr_mw = r.get("curr_mw")
        prior_mw = r.get("prior_mw")
        delta = r.get("delta")
        try:
            delta_f: Optional[float] = float(delta) if delta is not None else None
        except Exception:
            delta_f = None
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=r.get("dev"),
                metric="capacity_mw_delta_7d",
                value=curr_mw,
                delta=delta_f,
                source_url=None,
                detail={"prior_mw": prior_mw},
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


# ---------------------------------------------------------------------------
# Supply / demand gap section builders (PRD addendum Phase 4 + ADR 06)
# ---------------------------------------------------------------------------
#
# These four sections surface places where the warehouse already shows
# committed/built capacity but no (or only one) downstream offtaker — i.e.
# residual MW that may be commercially contractable. Each builder uses
# `_safe_query` for ORM selects, or wraps raw `text()` execute in try/except
# to mirror the helper's defensive behavior. All respect
# FACT_PACK_MAX_ROWS_PER_SECTION.


async def _section_uncontracted_capacity_top_sites(db: AsyncSession) -> FactSection:
    name = "uncontracted_capacity_top_sites"
    desc = (
        "Data-center Site rows with power_capacity_mw set but no end_user_companies — "
        "potential uncontracted residual capacity available to a new offtaker."
    )
    stmt = (
        select(Site)
        .where(
            and_(
                Site.power_capacity_mw.isnot(None),
                or_(
                    Site.end_user_companies.is_(None),
                    func.trim(Site.end_user_companies) == "",
                    func.lower(func.trim(Site.end_user_companies)).in_(
                        ("null", "[]")
                    ),
                ),
            )
        )
        .order_by(Site.power_capacity_mw.desc().nulls_last())
        .limit(FACT_PACK_MAX_ROWS_PER_SECTION)
    )
    raw = await _safe_query(db, name, stmt)
    rows: list[FactRow] = []
    for i, s in enumerate(raw):
        entity = s.building_name or s.campus_name or s.aterio_dc_uid
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=entity,
                metric="power_capacity_mw_unsold",
                value=s.power_capacity_mw,
                source_url=None,
                detail={
                    "provider": s.provider_name,
                    "state": s.state_code,
                    "stage": s.stage,
                    "aterio_est_mw": s.aterio_est_mw,
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_concentrated_offtake_sites(db: AsyncSession) -> FactSection:
    name = "concentrated_offtake_sites"
    desc = (
        "Data-center Site rows with exactly one end_user_company and "
        "power_capacity_mw at or above the state's top quartile — single-tenant "
        "concentration suggests potentially expandable capacity."
    )
    sql = text(
        """
        WITH per_state AS (
          SELECT state_code,
                 percentile_cont(0.75) WITHIN GROUP (ORDER BY power_capacity_mw)
                   FILTER (WHERE power_capacity_mw IS NOT NULL) AS q3
          FROM sites
          WHERE state_code IS NOT NULL
          GROUP BY state_code
        )
        SELECT s.id, s.building_name, s.campus_name, s.aterio_dc_uid,
               s.provider_name, s.state_code,
               s.power_capacity_mw, s.end_user_companies, s.stage,
               ps.q3 AS q3
        FROM sites s
        JOIN per_state ps USING (state_code)
        WHERE s.power_capacity_mw IS NOT NULL
          AND s.end_user_companies IS NOT NULL
          AND TRIM(s.end_user_companies) <> ''
          AND s.end_user_companies NOT LIKE '%,%'
          AND ps.q3 IS NOT NULL
          AND s.power_capacity_mw >= ps.q3
        ORDER BY s.power_capacity_mw DESC NULLS LAST
        LIMIT :limit
        """
    )
    rows: list[FactRow] = []
    try:
        result = await db.execute(sql, {"limit": FACT_PACK_MAX_ROWS_PER_SECTION})
        records = list(result.mappings().all())
    except Exception as exc:
        logger.warning(
            "ai_insights.hypothesizer.query_failed",
            extra={"label": name, "error": str(exc)},
        )
        records = []
    for i, r in enumerate(records):
        entity = r.get("building_name") or r.get("campus_name") or r.get("aterio_dc_uid")
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=entity,
                metric="power_capacity_mw_single_tenant",
                value=r.get("power_capacity_mw"),
                source_url=None,
                detail={
                    "provider": r.get("provider_name"),
                    "state": r.get("state_code"),
                    "end_user": r.get("end_user_companies"),
                    "state_q3_threshold": r.get("q3"),
                    "stage": r.get("stage"),
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_capacity_by_developer_with_low_offtake(
    db: AsyncSession,
) -> FactSection:
    name = "capacity_by_developer_with_low_offtake"
    desc = (
        "Data-center providers with high portfolio power_capacity_mw but low "
        "median end_user count — operators with capacity not yet matched to "
        "named tenants."
    )
    sql = text(
        """
        WITH per_provider AS (
          SELECT provider_name AS dev,
                 SUM(power_capacity_mw) AS total_mw,
                 COUNT(*) AS n_sites,
                 percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY CASE
                     WHEN end_user_companies IS NULL OR TRIM(end_user_companies)='' THEN 0
                     ELSE COALESCE(array_length(string_to_array(end_user_companies, ','), 1), 0)
                   END
                 ) AS median_n_customers
          FROM sites
          WHERE provider_name IS NOT NULL
            AND power_capacity_mw IS NOT NULL
          GROUP BY provider_name
          HAVING SUM(power_capacity_mw) > 0
        )
        SELECT dev, total_mw, n_sites AS n_projects, median_n_customers
        FROM per_provider
        WHERE median_n_customers <= 1
        ORDER BY total_mw DESC NULLS LAST
        LIMIT :limit
        """
    )
    rows: list[FactRow] = []
    try:
        result = await db.execute(sql, {"limit": FACT_PACK_MAX_ROWS_PER_SECTION})
        records = list(result.mappings().all())
    except Exception as exc:
        logger.warning(
            "ai_insights.hypothesizer.query_failed",
            extra={"label": name, "error": str(exc)},
        )
        records = []
    for i, r in enumerate(records):
        median_n = r.get("median_n_customers")
        try:
            median_f: Optional[float] = float(median_n) if median_n is not None else None
        except Exception:
            median_f = None
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=r.get("dev"),
                metric="developer_pipeline_mw_low_offtake",
                value=r.get("total_mw"),
                source_url=None,
                detail={
                    "n_projects": r.get("n_projects"),
                    "median_n_customers": median_f,
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


async def _section_epa_echo_high_mw_no_known_customer(
    db: AsyncSession,
) -> FactSection:
    # Section name preserved for backwards compatibility with prompt + tests; the
    # underlying signal is now "near-term uncontracted capacity at built or
    # under-construction data-center sites" (more actionable than EPA permits,
    # which lack rated_mw_total in this dataset).
    name = "epa_echo_high_mw_no_known_customer"
    desc = (
        "Sites in Active or Under Construction stage with power_capacity_mw "
        "set but no end_user_companies — near-term uncontracted capacity, "
        "highest urgency offtake opportunities."
    )
    sql = text(
        """
        SELECT s.id, s.building_name, s.campus_name, s.aterio_dc_uid,
               s.provider_name, s.state_code, s.power_capacity_mw,
               s.stage, s.aterio_est_mw
        FROM sites s
        WHERE s.power_capacity_mw IS NOT NULL
          AND (s.end_user_companies IS NULL OR TRIM(s.end_user_companies) = ''
               OR LOWER(TRIM(s.end_user_companies)) IN ('null','[]'))
          AND s.stage ILIKE ANY (ARRAY['%active%','%construction%','%commissioning%'])
        ORDER BY s.power_capacity_mw DESC NULLS LAST
        LIMIT :limit
        """
    )
    rows: list[FactRow] = []
    try:
        result = await db.execute(sql, {"limit": FACT_PACK_MAX_ROWS_PER_SECTION})
        records = list(result.mappings().all())
    except Exception as exc:
        logger.warning(
            "ai_insights.hypothesizer.query_failed",
            extra={"label": name, "error": str(exc)},
        )
        records = []
    for i, r in enumerate(records):
        entity = r.get("building_name") or r.get("campus_name") or r.get("aterio_dc_uid")
        rows.append(
            FactRow(
                row_id=_row_id(name, i),
                entity=entity,
                metric="active_stage_uncontracted_mw",
                value=r.get("power_capacity_mw"),
                source_url=None,
                detail={
                    "provider": r.get("provider_name"),
                    "state": r.get("state_code"),
                    "stage": r.get("stage"),
                    "aterio_est_mw": r.get("aterio_est_mw"),
                },
            )
        )
    return FactSection(name=name, description=desc, rows=_cap(rows))


# Section build descriptors -------------------------------------------------

_SECTION_BUILDERS: list[tuple[str, str, Any]] = [
    ("top_capacity_movers_24h",
     "EnergyProject rows created or updated in the last 24h, ordered by contracted MW.",
     _section_top_capacity_movers_24h),
    ("new_permits_24h",
     "BuildingPermit rows issued or applied for in the last 24h.",
     _section_new_permits_24h),
    ("anomalies_today",
     "Anomaly rows whose period_end is today (or detected today).",
     _section_anomalies_today),
    ("edgar_capacity_mentions_7d",
     "EdgarExtraction rows from the last 7 days with a non-null capacity_mw.",
     _section_edgar_capacity_mentions_7d),
    ("epa_echo_new_records_24h",
     "GeneratorPermit rows from EPA ECHO created in the last 24h.",
     _section_epa_echo_new_records_24h),
    ("coverage_gaps",
     "DataCoverage rows whose coverage_status is 'partial', stalest first.",
     _section_coverage_gaps),
    ("top_companies_by_delta_7d",
     "Top developers by week-over-week change in contracted MW.",
     _section_top_companies_by_delta_7d),
    # ----- supply / demand gap sections (Phase 4 PRD addendum) -----
    ("uncontracted_capacity_top_sites",
     "Data-center Site rows with power_capacity_mw set but no end_user_companies — "
     "potential uncontracted residual capacity available to a new offtaker.",
     _section_uncontracted_capacity_top_sites),
    ("concentrated_offtake_sites",
     "Sites with exactly one end_user_company and power_capacity_mw at or above "
     "the state's top quartile — single-tenant concentration suggests potentially "
     "expandable capacity.",
     _section_concentrated_offtake_sites),
    ("capacity_by_developer_with_low_offtake",
     "Data-center providers with high portfolio MW but low median end_user count — "
     "operators with capacity not yet matched to named tenants.",
     _section_capacity_by_developer_with_low_offtake),
    ("epa_echo_high_mw_no_known_customer",
     "Sites in Active or Under Construction stage with power_capacity_mw set but "
     "no end_user_companies — near-term uncontracted capacity, highest urgency.",
     _section_epa_echo_high_mw_no_known_customer),
]


# ---------------------------------------------------------------------------
# Public: build_factpack
# ---------------------------------------------------------------------------


async def build_factpack(db: AsyncSession) -> FactPack:
    """Build the FactPack by running each section builder defensively.

    A failure inside one section appends an empty section with `error`
    populated; the rest of the pack still builds.
    """
    sections: list[FactSection] = []
    for name, description, builder in _SECTION_BUILDERS:
        try:
            section = await builder(db)
            # Defensive cap (in case a builder ignored the per-section limit).
            if len(section.rows) > FACT_PACK_MAX_ROWS_PER_SECTION:
                section = FactSection(
                    name=section.name,
                    description=section.description,
                    rows=section.rows[:FACT_PACK_MAX_ROWS_PER_SECTION],
                    error=section.error,
                )
            sections.append(section)
        except Exception as exc:
            logger.warning(
                "ai_insights.hypothesizer.section_failed",
                extra={"section": name, "err": str(exc)},
            )
            sections.append(
                FactSection(
                    name=name,
                    description=description,
                    rows=[],
                    error=f"{type(exc).__name__}: {str(exc)[:120]}",
                )
            )

    # Enforce the global cap by trimming sections in order.
    total = sum(len(s.rows) for s in sections)
    if total > FACT_PACK_MAX_TOTAL_ROWS:
        budget = FACT_PACK_MAX_TOTAL_ROWS
        trimmed: list[FactSection] = []
        for s in sections:
            if budget <= 0:
                trimmed.append(
                    FactSection(name=s.name, description=s.description, rows=[], error=s.error)
                )
                continue
            keep = min(len(s.rows), budget)
            trimmed.append(
                FactSection(
                    name=s.name,
                    description=s.description,
                    rows=s.rows[:keep],
                    error=s.error,
                )
            )
            budget -= keep
        sections = trimmed
        total = sum(len(s.rows) for s in sections)

    pack = FactPack(generated_at=_utcnow(), sections=sections)
    logger.info(
        "ai_insights.hypothesizer.factpack_built",
        extra={"sections": len(sections), "total_rows": total},
    )
    return pack


# Alias kept for compatibility with the user spec spelling.
build_fact_pack = build_factpack


# ---------------------------------------------------------------------------
# Public: synthesize_insights
# ---------------------------------------------------------------------------


_INSIGHT_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                    "confidence_signal": {
                        "type": "string",
                        "enum": ["weak", "moderate", "strong"],
                    },
                    "materiality": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "supporting_row_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": [
                            "bar", "stacked_bar", "grouped_bar", "line",
                            "area", "pie", "scatter", "kpi_tile",
                            "sparkline", "none",
                        ],
                    },
                    "chart_y_label": {"type": "string"},
                },
                "required": [
                    "headline",
                    "body",
                    "confidence_signal",
                    "materiality",
                    "supporting_row_ids",
                ],
            },
        }
    },
    "required": ["insights"],
}


_SYSTEM_PROMPT = (
    "You are a competitive-intel analyst for the OCI Datacenter & Power "
    "Intelligence Platform. You receive a structured FactPack of recent "
    "warehouse rows (organised in named sections, each with row_ids of the "
    "form 'section_name:N'). Produce up to N concise insights that ground "
    "every claim in the supplied row_ids.\n\n"
    "Rules:\n"
    " - Each insight has: headline (<=140 chars), body (1-3 sentences), "
    "confidence_signal in {weak, moderate, strong}, materiality in "
    "{low, medium, high}, supporting_row_ids drawn ONLY from the FactPack.\n"
    " - Do NOT invent row_ids. If you cannot ground an insight in at least "
    "one row, omit it.\n"
    " - Prefer cross-section synthesis (e.g. correlate a permit with an "
    "EDGAR mention) when the rows make it natural.\n"
    " - Look for SUPPLY/DEMAND GAPS: when a section surfaces a site/developer "
    "with high committed capacity but few or zero offtakers, frame the "
    "insight as a commercial opportunity (e.g. potentially contractable "
    "residual MW). Cross-reference with EDGAR mentions and EPA ECHO permits "
    "where possible.\n"
    " - Keep tone factual; no marketing language.\n"
    " - For each insight, pick the visualisation that best conveys the point: "
    "set chart_type to one of {bar, stacked_bar, grouped_bar, line, area, pie, "
    "scatter, kpi_tile, sparkline, none}. Use 'bar' for ranked entities, "
    "'pie' for share-of-total when 2-6 slices sum meaningfully, 'line' or "
    "'area' for time series, 'scatter' for two numeric dimensions, "
    "'kpi_tile' for a single headline number, and 'none' when the supporting "
    "rows are not naturally chartable. Optionally set chart_y_label "
    "(e.g. \"MW\", \"sites\", \"USD\").\n\n"
    "Output: a single JSON object of the form {\"insights\": [...]} containing "
    "the array of insight objects. Do not wrap the JSON in code fences."
)


def _accounted_tokens(turn: Any) -> dict[str, int]:
    tokens = getattr(turn, "tokens", None) or {}
    return {
        "prompt": int(tokens.get("prompt", 0) or 0),
        "completion": int(tokens.get("completion", 0) or 0),
        "total": int(
            tokens.get("total", 0)
            or (int(tokens.get("prompt", 0) or 0) + int(tokens.get("completion", 0) or 0))
        ),
    }


def _coerce_insights(parsed, fact_pack: FactPack) -> list[InsightOutput]:
    """Validate parsed model output and drop any hallucinated row_ids."""
    if isinstance(parsed, list):
        raw_list = parsed
    elif isinstance(parsed, dict):
        raw_list = parsed.get("insights")
    else:
        raw_list = None
    if not isinstance(raw_list, list):
        return []
    valid_row_ids: set[str] = set()
    for section in fact_pack.sections:
        for r in section.rows:
            valid_row_ids.add(r.row_id)
    out: list[InsightOutput] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        try:
            ins = InsightOutput(**raw)
        except Exception:
            continue
        # Filter unknown row_ids; preserve order.
        filtered = [rid for rid in ins.supporting_row_ids if rid in valid_row_ids]
        if not filtered:
            # No grounding => drop.
            continue
        out.append(
            InsightOutput(
                headline=ins.headline,
                body=ins.body,
                confidence_signal=ins.confidence_signal,
                materiality=ins.materiality,
                supporting_row_ids=filtered,
                chart_type=ins.chart_type,
                chart_y_label=ins.chart_y_label,
            )
        )
    return out


async def synthesize_insights(
    fact_pack: FactPack,
    max_insights: int = 7,
) -> list[InsightOutput]:
    """Single mega-call that turns the FactPack into a list of insights.

    Behaviour:
        - Empty FactPack -> [] without an LLM call.
        - AI_INSIGHTS_FAKE_LLM env-var (JSON) -> short-circuit; tests use this.
        - Otherwise call llm_client.reason; on JSONDecodeError retry once.
        - Drop insights whose supporting_row_ids cannot be resolved.
    """
    if fact_pack.total_rows() == 0:
        return []

    fake = os.environ.get("AI_INSIGHTS_FAKE_LLM")
    if fake:
        try:
            parsed_fake = json.loads(fake)
        except json.JSONDecodeError as exc:
            logger.warning(
                "ai_insights.hypothesizer.fake_parse_failed",
                extra={"err": str(exc)},
            )
            return []
        validated = _coerce_insights(parsed_fake, fact_pack)
        return validated[:max_insights]

    user_message = fact_pack.to_compact_json()
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    parse_attempts = 0
    parsed: Optional[dict] = None
    last_turn: Any = None
    while parse_attempts < 2 and parsed is None:
        parse_attempts += 1
        turn = await llm_client.reason(
            model=MODELS["reasoning"],
            prompt_version=PROMPT_VERSION,
            messages=messages,
        )
        last_turn = turn
        content = (turn.content or "").strip()
        try:
            parsed = json.loads(content) if content else {}
        except json.JSONDecodeError as exc:
            logger.warning(
                "ai_insights.hypothesizer.parse_retry",
                extra={"attempt": parse_attempts, "err": str(exc)},
            )
            parsed = None
            if parse_attempts >= 2:
                raise RuntimeError("synthesis_parse_failed")

    if parsed is None:
        raise RuntimeError("synthesis_parse_failed")

    # Token accounting (D7 ceiling -- warn, do not raise).
    if last_turn is not None:
        tokens = _accounted_tokens(last_turn)
        print(
            "ai_insights.hypothesizer.tokens "
            f"prompt={tokens['prompt']} completion={tokens['completion']} total={tokens['total']}"
        )
        if tokens["total"] > HYPOTHESIZER_TOKEN_CEILING:
            logger.warning(
                "ai_insights.hypothesizer.token_ceiling_exceeded",
                extra={
                    "total": tokens["total"],
                    "ceiling": HYPOTHESIZER_TOKEN_CEILING,
                },
            )

    validated = _coerce_insights(parsed, fact_pack)
    return validated[:max_insights]


__all__ = [
    "FactRow",
    "FactSection",
    "FactPack",
    "Hypothesis",
    "InsightOutput",
    "build_factpack",
    "build_fact_pack",
    "synthesize_insights",
    "FACT_PACK_MAX_ROWS_PER_SECTION",
    "FACT_PACK_MAX_TOTAL_ROWS",
    "HYPOTHESIZER_TOKEN_CEILING",
    "PROMPT_VERSION",
]
