"""
AterioAdapter -- ingests Aterio CSV + Energy Project xlsx into PostgreSQL.

Handles three data streams:
  A. Sites from data_center_inventory CSV (6973+ rows, 73 columns)
  B. Events synthesized from site timeline date columns
     (The Data Dictionary xlsx describes the event schema but does not
     contain actual event data rows, so we derive events from dates.)
  C. Energy Projects from the Energy Project Inventory xlsx (1695 rows, 65 columns)

Plus:
  - Role edges (site <-> company associations) via entity resolution
  - DataCoverage rows per US state
  - IngestionRun audit trail
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import polars as pl
from openpyxl import load_workbook
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    Site,
    Event,
    EnergyProject,
    SiteCompanyAssociation,
    DataCoverage,
    IngestionRun,
)
from entity_resolution import resolve_company
from seed.canonical_companies import seed_companies

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column mapping: CSV header (UPPERCASE) -> Site model field (lowercase)
# ---------------------------------------------------------------------------

COLUMN_MAP: Dict[str, str] = {
    "ATERIO_DATA_CENTER_UID": "aterio_dc_uid",
    "DATA_CENTER_BUILDING_NAME": "building_name",
    "ATERIO_DATA_CENTER_CAMPUS_UID": "aterio_campus_uid",
    "DATA_CENTER_CAMPUS_NAME": "campus_name",
    "DATA_CENTER_STAGE": "stage",
    "FLG_AI_FACILITY": "is_ai_facility",
    "FLG_BTM_ONSITE_POWER_GENERATION": "flg_btm_onsite_power_generation",
    "TOT_PROJECT_COST": "tot_project_cost",
    # ATERIO_PROVIDER_UID -- skipped (no model field)
    "PROVIDER_NAME": "provider_name",
    "PROVIDER_URL": "provider_url",
    "PROVIDER_PUBLIC_PRIVATE": "provider_public_private",
    "PROVIDER_TICKER_NAME": "provider_ticker",
    "PROVIDER_BLOOMBERG_TICKER_NAME": "provider_bloomberg_ticker",
    # STOCK_EXCHANGE_PROVIDER_NAME -- skipped
    "PROVIDER_BACKED_BY": "provider_backed_by",
    "CONSTRUCTION_EQUIPMENT_PROVIDER_COMPANIES": "construction_equipment_provider_companies",
    "PROJECT_FINANCING_COMPANIES": "project_financing_companies",
    "END_USER_COMPANIES": "end_user_companies",
    "FULL_ADDRESS": "full_address",
    "ZIP_CODE": "zip_code",
    "COUNTY_FIPS_CODE": "county_fips",
    "COUNTY_NAME": "county_name",
    "CITY_NAME": "city_name",
    "PLACE_FIPS_CODE": "place_fips_code",
    "STATE_CODE": "state_code",
    "STATE_NAME": "state_name",
    "COUNTRY_CODE": "country_code",
    "COUNTRY_NAME": "country_name",
    "LOCATION_LATITUDE": "latitude",
    "LOCATION_LONGITUDE": "longitude",
    "SITE_ACREAGE": "site_acreage",
    "TOT_FACILITY_SPACE_SQFT": "tot_facility_space_sqft",
    "TOT_DATACENTER_SPACE_SQFT": "tot_datacenter_space_sqft",
    "PROV_PUB_TOT_POWER_CAPACITY_MW": "prov_pub_tot_power_capacity_mw",
    "ATERIO_EST_TOT_POWER_CAPACITY_MW": "aterio_est_mw",
    "ATERIO_EST_TOT_POWER_CAPACITY_MW_LOWER": "aterio_est_mw_lower",
    "ATERIO_EST_TOT_POWER_CAPACITY_MW_UPPER": "aterio_est_mw_upper",
    "SELECTED_POWER_CAPACITY_MW": "power_capacity_mw",
    "AVG_MARKET_POWER_COST": "avg_market_power_cost",
    "YEARLY_PUE": "yearly_pue",
    "TOT_NUM_GENERATORS": "tot_num_generators",
    "DATA_CENTER_ANNOUNCED_DATE": "announced_date",
    "DATA_CENTER_CANCELLED_DATE": "cancelled_date",
    "DATA_CENTER_PROJECT_WITHDRAWN_DATE": "project_withdrawn_date",
    "DATA_CENTER_CONSTRUCTION_START_DATE": "construction_start_date",
    "LATEST_SATELLITE_PICTURE_DATE": "latest_satellite_picture_date",
    "PCT_CONSTRUCTION_STATUS": "pct_construction",
    "DATA_CENTER_CONSTRUCTION_FINISHED_DATE": "construction_finished_date",
    "DATA_CENTER_ACTIVATION_DATE": "activation_date",
    "ESTIMATED_ACTIVE_DATE_BY": "estimated_active_date_by",
    # ATERIO_ELECTRICAL_UTILITY_UID -- skipped
    "UTILITY_NAME": "utility_name",
    # UTILITY_CODE -- skipped
    "UTILITY_PUBLIC_PRIVATE": "utility_public_private",
    "UTILITY_TICKER_NAME": "utility_ticker",
    # UTILITY_BLOOMBERG_TICKER_NAME -- skipped
    # UTILITY_EXCHANGE_PROVIDER_TICKER_NAME -- skipped
    # ATERIO_BAL_AUTH_UID -- skipped
    "BAL_AUTH_ABBR": "bal_auth_abbr",
    "BAL_AUTH_NAME": "bal_auth_name",
    # ATERIO_BAL_AUTH_SUBREGION_UID -- skipped
    "BAL_AUTH_SUBREGION_CODE": "bal_auth_subregion_code",
    "BAL_AUTH_SUBREGION_NAME": "bal_auth_subregion_name",
    "DATASHEET_URL": "datasheet_url",
    "MAP_URL": "map_url",
    "PROJECT_PERMIT_URL": "permit_url",
    "CAPEX_URL": "capex_url",
    "PROJECT_EXECUTION_LIKELIHOOD": "project_execution_likelihood",
    "NOTES": "notes",
    "RECORD_CREATED_DATE": "record_created_at",
    "RECORD_UPDATED_DATE": "record_updated_at",
    "UPDATED_AT": "updated_at_source",
}

# Columns that should be skipped entirely (no model field)
_SKIP_CSV_COLS = {
    "ATERIO_PROVIDER_UID",
    "STOCK_EXCHANGE_PROVIDER_NAME",
    "ATERIO_ELECTRICAL_UTILITY_UID",
    "UTILITY_CODE",
    "UTILITY_BLOOMBERG_TICKER_NAME",
    "UTILITY_EXCHANGE_PROVIDER_TICKER_NAME",
    "ATERIO_BAL_AUTH_UID",
    "ATERIO_BAL_AUTH_SUBREGION_UID",
}

# Boolean columns that use Y/N encoding
_BOOL_COLS_CSV = {"FLG_AI_FACILITY", "FLG_BTM_ONSITE_POWER_GENERATION"}

# Numeric Site model fields (will be cast to float, except tot_num_generators -> int)
_NUMERIC_FIELDS = {
    "latitude", "longitude", "site_acreage", "tot_facility_space_sqft",
    "tot_datacenter_space_sqft", "prov_pub_tot_power_capacity_mw",
    "aterio_est_mw", "aterio_est_mw_lower", "aterio_est_mw_upper",
    "power_capacity_mw", "tot_project_cost", "avg_market_power_cost",
    "yearly_pue", "tot_num_generators", "pct_construction",
}
# NOTE: project_execution_likelihood is now VARCHAR ("High"/"Medium"/"Low"), not float

# Date-string fields (kept as str in the Site model)
_DATE_FIELDS = {
    "announced_date", "cancelled_date", "project_withdrawn_date",
    "construction_start_date", "latest_satellite_picture_date",
    "construction_finished_date", "activation_date",
    "estimated_active_date_by",
}

# Timestamp fields (converted to datetime objects)
_TIMESTAMP_FIELDS = {
    "record_created_at", "record_updated_at", "updated_at_source",
}

# ---------------------------------------------------------------------------
# Event synthesis: model date field -> event type
# ---------------------------------------------------------------------------

_DATE_TO_EVENT_TYPE = {
    "announced_date": "announcement",
    "construction_start_date": "construction_start",
    "construction_finished_date": "activation",
    "activation_date": "activation",
    "cancelled_date": "cancellation",
}

# Reverse lookup: model field -> CSV column name (built once)
_MODEL_TO_CSV: Dict[str, str] = {v: k for k, v in COLUMN_MAP.items()}

# ---------------------------------------------------------------------------
# Role-edge mapping for site <-> company associations
# ---------------------------------------------------------------------------

ROLE_MAP: Dict[str, Tuple[str, Optional[str], bool]] = {
    # CSV column -> (role, ticker_csv_column_or_None, is_multi_company)
    "PROVIDER_NAME": ("provider", "PROVIDER_TICKER_NAME", False),
    "PROVIDER_BACKED_BY": ("provider_backer", None, False),
    "END_USER_COMPANIES": ("end_user", None, True),
    "PROJECT_FINANCING_COMPANIES": ("financing", None, True),
    "CONSTRUCTION_EQUIPMENT_PROVIDER_COMPANIES": ("equipment", None, True),
    "UTILITY_NAME": ("utility", "UTILITY_TICKER_NAME", False),
}

# ---------------------------------------------------------------------------
# Energy Project: columns that map directly to EnergyProject model fields.
# ATERIO_ENERGY_PROJECT_UID is NOT in the model, so it goes to payload.
# ---------------------------------------------------------------------------

_ENERGY_DIRECT_FIELDS: Dict[str, str] = {
    "PROJECT_NAME": "project_name",
    "FLG_BTM_PROJECT": "flg_btm_project",
    "DEVELOPER_COMPANIES": "developer_companies",
    "DEVELOPER_COMPANIES_TICKER": "developer_ticker",
    "EIA_ENTITY_IDS": "eia_entity_ids",
    "EIA_ENTITY_NAMES": "eia_entity_names",
    "CONSTRUCTION_EQUIPMENT_PROVIDER_COMPANIES": "construction_equipment_provider_companies",
    "PROJECT_FINANCING_COMPANIES": "project_financing_companies",
    "CUSTOMER_COMPANIES": "customer_companies",
    "TOT_CONTRACTED_POWER_CAPACITY_MW": "tot_contracted_power_mw",
    "TOT_PROJECT_COST": "tot_project_cost",
    "PROJECT_FOOTPRINT_ACREAGE": "project_footprint_acreage",
    "SITE_BOUNDARY_ACREAGE": "site_boundary_acreage",
    "STATE_CODE": "state_code",
    "LOCATION_LATITUDE": "latitude",
    "LOCATION_LONGITUDE": "longitude",
}

# Numeric energy fields that need float casting
_ENERGY_NUMERIC = {
    "tot_contracted_power_mw", "tot_project_cost",
    "project_footprint_acreage", "site_boundary_acreage",
    "latitude", "longitude",
}

BATCH_SIZE = 100  # Keep small to stay under asyncpg 32767 param limit (Site has ~70 cols)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yn_to_bool(val: Any) -> Optional[bool]:
    """Convert Y/N string to boolean. Returns None for null/unrecognised."""
    if val is None:
        return None
    s = str(val).strip().upper()
    if s == "Y":
        return True
    if s == "N":
        return False
    return None


def _to_float(val: Any) -> Optional[float]:
    """Safely cast to float. Returns None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> Optional[int]:
    """Safely cast to int via float. Returns None on failure."""
    f = _to_float(val)
    if f is None:
        return None
    return int(f)


def _parse_ts(val: Any) -> Optional[datetime]:
    """Parse a date/datetime string into a datetime object.

    Tries several common formats. Returns None if unparseable.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_date(val: Any) -> Optional[date]:
    """Parse a date/datetime string into a date object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _smart_split(value: str) -> List[str]:
    """Split a comma-separated company list, respecting 'Inc.,' style names.

    Strategy: split on ', ' then re-join fragments that look like suffixes
    (Inc., LLC, Ltd., Co., Corp., L.P., etc.) back onto the previous part.
    """
    if not value or not value.strip():
        return []

    _SUFFIXES = {
        "inc.", "inc", "llc", "llc.", "ltd.", "ltd", "co.", "co",
        "corp.", "corp", "l.p.", "lp", "l.l.c.", "n.a.", "plc",
        "s.a.", "gmbh", "ag", "se", "nv", "bv",
    }

    raw_parts = [p.strip() for p in value.strip().split(", ")]
    merged: List[str] = []

    for part in raw_parts:
        if not part:
            continue
        # If this fragment looks like a company suffix, merge with previous
        if merged and (
            part.lower().rstrip(".") in _SUFFIXES
            or part.lower() in _SUFFIXES
        ):
            merged[-1] = merged[-1] + ", " + part
        else:
            merged.append(part)

    return [p for p in merged if p]


# ---------------------------------------------------------------------------
# AterioAdapter
# ---------------------------------------------------------------------------

class AterioAdapter:
    """Ingests Aterio CSV + Energy Project xlsx into PostgreSQL.

    Entry point is the async ``run(session)`` method which executes:
      1. seed_companies -- ensure canonical companies exist
      2. _ingest_sites -- CSV -> sites table
      3. _synthesize_events -- derive events from site date columns
      4. _ingest_energy_projects -- xlsx -> energy_projects table
      5. _emit_role_edges -- entity resolution -> site_company_associations
      6. _write_coverage -- per-state DataCoverage rows
    All wrapped in an IngestionRun audit record.
    """

    adapter_name = "Aterio Dataset"
    adapter_id = "aterio_csv"
    adapter_version = "1.0.0"
    pillar = "power_sites"
    source_id = "aterio_csv"
    declared_status = "full"
    coverage_scope = "US"

    def __init__(
        self,
        csv_path: str,
        events_xlsx_path: str,
        energy_xlsx_path: str,
    ):
        self.csv_path = csv_path
        self.events_xlsx_path = events_xlsx_path
        self.energy_xlsx_path = energy_xlsx_path

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def run(self, session: AsyncSession) -> dict:
        """Run full ingestion pipeline.

        Returns a dict of counts for each stage.
        """
        # Seed canonical companies first so entity resolution can find them
        logger.info("seed_companies.start")
        await seed_companies(session)
        logger.info("seed_companies.done")

        # Create the ingestion run audit record
        run_record = IngestionRun(
            adapter_name=self.adapter_id,
            adapter_version=self.adapter_version,
            status="running",
            trigger="manual",
        )
        session.add(run_record)
        await session.flush()
        run_id = run_record.id
        logger.info("ingestion_run.started", extra={"run_id": run_id})

        stats: Dict[str, int] = {
            "sites_upserted": 0,
            "events_upserted": 0,
            "energy_projects_upserted": 0,
            "role_edges_upserted": 0,
            "coverage_rows": 0,
        }
        errors: List[str] = []

        try:
            # A. Sites
            sites_count = await self._ingest_sites(session)
            stats["sites_upserted"] = sites_count
            logger.info("sites.ingested", extra={"count": sites_count})

            # B. Events (synthesized from CSV date columns)
            events_count = await self._synthesize_events(session)
            stats["events_upserted"] = events_count
            logger.info("events.synthesized", extra={"count": events_count})

            # C. Energy Projects
            energy_count = await self._ingest_energy_projects(session)
            stats["energy_projects_upserted"] = energy_count
            logger.info("energy_projects.ingested", extra={"count": energy_count})

            # D. Role edges
            edges_count = await self._emit_role_edges(session)
            stats["role_edges_upserted"] = edges_count
            logger.info("role_edges.emitted", extra={"count": edges_count})

            # E. Coverage
            cov_count = await self._write_coverage(session)
            stats["coverage_rows"] = cov_count

            # F. Finalize ingestion run
            total_stored = (
                stats["sites_upserted"]
                + stats["events_upserted"]
                + stats["energy_projects_upserted"]
            )
            run_record.status = "success"
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = stats["sites_upserted"]
            run_record.records_stored = total_stored
            run_record.records_normalized = total_stored
            session.add(run_record)
            await session.flush()

            logger.info("ingestion_run.success", extra={"run_id": run_id, **stats})

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            errors.append(error_msg)
            logger.exception("ingestion_run.failed", extra={"run_id": run_id})

            run_record.status = "failure"
            run_record.completed_at = datetime.utcnow()
            run_record.error_log = {"errors": errors}
            session.add(run_record)
            await session.flush()
            raise

        return stats

    # -----------------------------------------------------------------------
    # A. Sites ingestion
    # -----------------------------------------------------------------------

    async def _ingest_sites(self, session: AsyncSession) -> int:
        """Read CSV with polars, map all 73 columns, upsert into sites table."""
        df = pl.read_csv(
            self.csv_path,
            null_values=["", "N/A", "n/a", "NA", "None", "null"],
            infer_schema_length=0,  # read everything as strings initially
        )
        logger.info("csv.loaded", extra={"rows": len(df), "cols": len(df.columns)})

        upserted = 0
        rows = df.to_dicts()

        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start : batch_start + BATCH_SIZE]
            records: List[Dict[str, Any]] = []

            for row in batch:
                try:
                    record = self._map_site_row(row)
                except Exception:
                    logger.warning(
                        "site_row.map_failed",
                        extra={"uid": row.get("ATERIO_DATA_CENTER_UID")},
                        exc_info=True,
                    )
                    continue
                if record.get("aterio_dc_uid") is None:
                    continue
                records.append(record)

            if not records:
                continue

            stmt = pg_insert(Site).values(records)
            # On conflict: update every column except the unique key itself
            update_cols = {
                col: stmt.excluded[col]
                for col in records[0].keys()
                if col != "aterio_dc_uid"
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["aterio_dc_uid"],
                set_=update_cols,
            )
            await session.execute(stmt)
            upserted += len(records)

        await session.flush()
        return upserted

    def _map_site_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Transform a single CSV row dict into a Site-compatible dict."""
        record: Dict[str, Any] = {}

        for csv_col, model_field in COLUMN_MAP.items():
            raw_val = row.get(csv_col)

            # Boolean (Y/N) columns
            if csv_col in _BOOL_COLS_CSV:
                record[model_field] = _yn_to_bool(raw_val)
                continue

            # Numeric columns
            if model_field in _NUMERIC_FIELDS:
                if model_field == "tot_num_generators":
                    record[model_field] = _to_int(raw_val)
                else:
                    record[model_field] = _to_float(raw_val)
                continue

            # Timestamp columns (-> datetime)
            if model_field in _TIMESTAMP_FIELDS:
                record[model_field] = _parse_ts(raw_val)
                continue

            # Date-string columns (kept as Optional[str] in the model)
            if model_field in _DATE_FIELDS:
                if raw_val is None:
                    record[model_field] = None
                else:
                    s = str(raw_val).strip()
                    record[model_field] = s if s else None
                continue

            # Default: string field -- strip whitespace, convert empty to None
            if raw_val is None:
                record[model_field] = None
            else:
                s = str(raw_val).strip()
                record[model_field] = s if s else None

        # Internal timestamps
        now = datetime.utcnow()
        record["created_at"] = now
        record["updated_at"] = now

        return record

    # -----------------------------------------------------------------------
    # B. Events (synthesized from CSV date columns)
    # -----------------------------------------------------------------------

    async def _synthesize_events(self, session: AsyncSession) -> int:
        """Create Event rows from the timeline date columns in the CSV.

        The Data Dictionary xlsx describes the event schema but does not
        contain actual event data rows.  We synthesize events from the
        site date columns (announced_date, construction_start_date, etc.).
        Deduplication: delete existing synthesized events for each batch's
        dc_uids, then re-insert.
        """
        df = pl.read_csv(
            self.csv_path,
            null_values=["", "N/A", "n/a", "NA", "None", "null"],
            infer_schema_length=0,
        )

        upserted = 0
        rows = df.to_dicts()

        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start : batch_start + BATCH_SIZE]
            event_records: List[Dict[str, Any]] = []

            for row in batch:
                dc_uid = row.get("ATERIO_DATA_CENTER_UID")
                if not dc_uid or not str(dc_uid).strip():
                    continue
                dc_uid = str(dc_uid).strip()

                for date_model_field, evt_type in _DATE_TO_EVENT_TYPE.items():
                    csv_col = _MODEL_TO_CSV.get(date_model_field)
                    if csv_col is None:
                        continue

                    raw_date = row.get(csv_col)
                    if raw_date is None or not str(raw_date).strip():
                        continue

                    event_date = _parse_date(raw_date)
                    if event_date is None:
                        continue

                    building_name = row.get("DATA_CENTER_BUILDING_NAME", "") or ""
                    description = (
                        f"{evt_type.replace('_', ' ').title()} for {building_name}"
                    ).strip()

                    event_records.append({
                        "aterio_dc_uid": dc_uid,
                        "event_type": evt_type,
                        "event_date": event_date,
                        "event_description": description,
                        "source_url": (row.get("DATASHEET_URL") or "").strip() or None,
                        "payload": {
                            "source": "aterio_csv_synthesized",
                            "csv_column": csv_col,
                            "provider_name": row.get("PROVIDER_NAME"),
                            "stage": row.get("DATA_CENTER_STAGE"),
                        },
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    })

            if not event_records:
                continue

            # Delete existing synthesized events for dc_uids in this batch,
            # then re-insert. This makes the operation idempotent.
            dc_uids_in_batch = list({r["aterio_dc_uid"] for r in event_records})
            await session.execute(
                text(
                    "DELETE FROM events WHERE aterio_dc_uid = ANY(:uids) "
                    "AND payload->>'source' = 'aterio_csv_synthesized'"
                ),
                {"uids": dc_uids_in_batch},
            )

            stmt = pg_insert(Event).values(event_records)
            await session.execute(stmt)
            upserted += len(event_records)

        await session.flush()
        return upserted

    # -----------------------------------------------------------------------
    # C. Energy Projects
    # -----------------------------------------------------------------------

    async def _ingest_energy_projects(self, session: AsyncSession) -> int:
        """Read the Energy Project Inventory xlsx and upsert into energy_projects.

        The xlsx has sheet 'Data Sample' with 65 columns.  Columns that map
        directly to EnergyProject model fields are extracted; everything else
        is packed into the payload JSONB column.

        Since EnergyProject has no natural unique key in the model, we use
        delete-then-insert keyed on the ATERIO_ENERGY_PROJECT_UID stored in
        payload.  On subsequent runs the old rows are cleared first.
        """
        wb = load_workbook(self.energy_xlsx_path, read_only=True, data_only=True)
        ws = wb["Data Sample"]

        # Build header map from row 1
        headers: List[Optional[str]] = []
        for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            headers = list(row)
            break

        # Clear previous energy project rows from this source so re-runs
        # are idempotent.  We tag rows via payload->>'source'.
        await session.execute(
            text(
                "DELETE FROM energy_projects "
                "WHERE payload->>'source' = 'aterio_energy_xlsx'"
            )
        )

        upserted = 0
        batch: List[Dict[str, Any]] = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            vals = list(row)

            # Skip empty rows
            if all(v is None for v in vals):
                continue

            try:
                row_dict = dict(zip(headers, vals))
                record = self._map_energy_row(row_dict, headers)
                batch.append(record)
            except Exception:
                logger.warning(
                    "energy_row.map_failed",
                    extra={"row_idx": row_idx},
                    exc_info=True,
                )
                continue

            if len(batch) >= BATCH_SIZE:
                upserted += await self._upsert_energy_batch(session, batch)
                batch = []

        if batch:
            upserted += await self._upsert_energy_batch(session, batch)

        wb.close()
        await session.flush()
        return upserted

    def _map_energy_row(
        self, row: Dict[str, Any], all_headers: List[Optional[str]]
    ) -> Dict[str, Any]:
        """Transform an xlsx row dict into an EnergyProject-compatible dict."""
        record: Dict[str, Any] = {}
        payload: Dict[str, Any] = {"source": "aterio_energy_xlsx"}

        for header in all_headers:
            if header is None:
                continue
            raw_val = row.get(header)

            if header in _ENERGY_DIRECT_FIELDS:
                model_field = _ENERGY_DIRECT_FIELDS[header]

                if model_field == "flg_btm_project":
                    record[model_field] = _yn_to_bool(raw_val)
                elif model_field in _ENERGY_NUMERIC:
                    record[model_field] = _to_float(raw_val)
                elif model_field == "eia_entity_ids":
                    # Parse comma-separated IDs into a JSON array
                    if raw_val is None:
                        record[model_field] = None
                    else:
                        s = str(raw_val).strip()
                        if s:
                            record[model_field] = [
                                x.strip() for x in s.split(",") if x.strip()
                            ]
                        else:
                            record[model_field] = None
                else:
                    # String field
                    if raw_val is None:
                        record[model_field] = None
                    else:
                        s = str(raw_val).strip()
                        record[model_field] = s if s else None
            else:
                # All other columns go into payload JSONB
                if raw_val is not None:
                    if isinstance(raw_val, datetime):
                        payload[header] = raw_val.isoformat()
                    elif isinstance(raw_val, date):
                        payload[header] = raw_val.isoformat()
                    else:
                        payload[header] = raw_val

        record["payload"] = payload if payload else None

        now = datetime.utcnow()
        record["created_at"] = now
        record["updated_at"] = now

        return record

    async def _upsert_energy_batch(
        self, session: AsyncSession, batch: List[Dict[str, Any]]
    ) -> int:
        """Insert a batch of energy project records."""
        if not batch:
            return 0
        stmt = pg_insert(EnergyProject).values(batch)
        await session.execute(stmt)
        return len(batch)

    # -----------------------------------------------------------------------
    # D. Role edges (site <-> company associations)
    # -----------------------------------------------------------------------

    async def _emit_role_edges(self, session: AsyncSession) -> int:
        """Create SiteCompanyAssociation rows by resolving company names.

        For each site, iterates over the ROLE_MAP columns, resolves each
        company name via entity_resolution.resolve_company(), and upserts
        an association row with ON CONFLICT DO NOTHING.
        """
        df = pl.read_csv(
            self.csv_path,
            null_values=["", "N/A", "n/a", "NA", "None", "null"],
            infer_schema_length=0,
        )
        rows = df.to_dicts()

        # Build uid -> site.id lookup
        result = await session.execute(
            select(Site.id, Site.aterio_dc_uid).where(Site.aterio_dc_uid.isnot(None))
        )
        uid_to_site_id: Dict[str, int] = {
            uid: sid for sid, uid in result.all()
        }

        edges_created = 0

        for row in rows:
            dc_uid = row.get("ATERIO_DATA_CENTER_UID")
            if not dc_uid or not str(dc_uid).strip():
                continue
            dc_uid = str(dc_uid).strip()
            site_id = uid_to_site_id.get(dc_uid)
            if site_id is None:
                continue

            for csv_col, (role, ticker_col, is_multi) in ROLE_MAP.items():
                raw_val = row.get(csv_col)
                if raw_val is None or not str(raw_val).strip():
                    continue

                raw_str = str(raw_val).strip()
                ticker: Optional[str] = None
                if ticker_col:
                    t = row.get(ticker_col)
                    if t and str(t).strip():
                        ticker = str(t).strip()

                if is_multi:
                    company_names = _smart_split(raw_str)
                else:
                    company_names = [raw_str]

                for name in company_names:
                    if not name:
                        continue
                    try:
                        company_id, confidence, match_method = await resolve_company(
                            session, name, ticker=ticker, source=self.source_id
                        )
                    except Exception:
                        logger.warning(
                            "role_edge.resolve_failed",
                            extra={"raw_name": name, "site_id": site_id},
                            exc_info=True,
                        )
                        continue

                    if company_id is None:
                        continue

                    stmt = (
                        pg_insert(SiteCompanyAssociation)
                        .values(
                            site_id=site_id,
                            company_id=company_id,
                            role=role,
                            source=self.source_id,
                            source_record_id=dc_uid,
                            confidence=confidence,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                        )
                        .on_conflict_do_nothing(
                            constraint="uq_site_company_role_source"
                        )
                    )
                    await session.execute(stmt)
                    edges_created += 1

                    # Only use the ticker for the first (single) company
                    # in the column; subsequent companies in a multi-company
                    # field won't share the same ticker.
                    ticker = None

        await session.flush()
        return edges_created

    # -----------------------------------------------------------------------
    # E. Coverage
    # -----------------------------------------------------------------------

    async def _write_coverage(self, session: AsyncSession) -> int:
        """Upsert DataCoverage rows for each US state present in the sites table."""
        result = await session.execute(
            select(Site.state_code, func.count(Site.id))
            .where(Site.state_code.isnot(None))
            .where(Site.country_code == "US")
            .group_by(Site.state_code)
        )
        state_counts = result.all()

        now = datetime.utcnow()
        count = 0

        for state_code, record_count in state_counts:
            if not state_code or not state_code.strip():
                continue
            stmt = (
                pg_insert(DataCoverage)
                .values(
                    pillar=self.pillar,
                    state_code=state_code.strip(),
                    source=self.source_id,
                    coverage_status="full",
                    record_count=record_count,
                    last_ingested_at=now,
                    freshness_sla_hours=720,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_coverage_pillar_state_source",
                    set_={
                        "coverage_status": "full",
                        "record_count": record_count,
                        "last_ingested_at": now,
                        "updated_at": now,
                    },
                )
            )
            await session.execute(stmt)
            count += 1

        await session.flush()
        logger.info("coverage.written", extra={"states": count})
        return count
