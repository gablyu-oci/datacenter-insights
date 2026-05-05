"""Unit tests for `agents.insights.hypothesizer.build_factpack` and the
FactPack/FactSection/FactRow Pydantic models.

These tests do NOT touch a real database. We pass a fake AsyncSession that
returns canned row lists in the order that build_factpack invokes its
section builders. Six of the seven sections call `await db.execute(stmt)`
followed by `result.scalars().all()` (via the `_safe_query` helper);
the seventh, `top_companies_by_delta_7d`, calls `result.mappings().all()`.
The fake `_FakeResult` supports both protocols.

We never set AI_INSIGHTS_FAKE_LLM here -- build_factpack does not use it,
and the fixtures defensively unset it to keep environments clean.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any

import pytest

from agents.insights.hypothesizer import (
    FACT_PACK_MAX_ROWS_PER_SECTION,
    FactPack,
    FactRow,
    FactSection,
    build_factpack,
)
from db.models import (
    Anomaly,
    BuildingPermit,
    DataCoverage,
    EdgarExtraction,
    EnergyProject,
    Site,
    GeneratorPermit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_fake_llm(monkeypatch):
    """Ensure no environment variable leaks across tests."""
    monkeypatch.delenv("AI_INSIGHTS_FAKE_LLM", raising=False)


# ---------------------------------------------------------------------------
# Fake AsyncSession
# ---------------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeMappings:
    def __init__(self, rows: list[Any]) -> None:
        # rows here are expected to be dicts when mappings().all() is used
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeResult:
    """Mimics the SQLAlchemy Result API used by hypothesizer:
    - `.scalars().all()` for ORM rows
    - `.mappings().all()` for the raw-SQL CTE section
    """

    def __init__(self, rows: list[Any], *, mapping_rows: list[Any] | None = None) -> None:
        self._rows = rows
        self._mapping_rows = mapping_rows if mapping_rows is not None else rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._mapping_rows)

    def fetchall(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """Records every execute() call and returns canned results in order.

    `responses` is a list whose element can be:
      - a `_FakeResult` (returned)
      - a `list` (wrapped in a `_FakeResult(scalars=list)`)
      - an Exception class or instance (raised)
      - a callable (invoked with the stmt; its return value used recursively)
    """

    def __init__(self, responses: list[Any]) -> None:
        self._queue: list[Any] = list(responses)
        self.calls: list[Any] = []

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> _FakeResult:
        self.calls.append((stmt, args, kwargs))
        if not self._queue:
            return _FakeResult([])
        head = self._queue.pop(0)
        if isinstance(head, _FakeResult):
            return head
        if isinstance(head, list):
            return _FakeResult(head)
        if isinstance(head, type) and issubclass(head, BaseException):
            raise head("fake_session_execute_failure")
        if isinstance(head, BaseException):
            raise head
        if callable(head):
            return head(stmt)
        return _FakeResult([])


# ---------------------------------------------------------------------------
# Builders for ORM-shaped fixtures
# ---------------------------------------------------------------------------


def _energy_project() -> EnergyProject:
    now = datetime.now(timezone.utc)
    return EnergyProject(
        id=1,
        project_name="Foo Solar",
        tot_contracted_power_mw=500.0,
        state_code="VA",
        developer_companies="Microsoft",
        created_at=now,
        updated_at=now,
    )


def _building_permit() -> BuildingPermit:
    return BuildingPermit(
        id=1,
        source="loudoun_va",
        source_permit_id="P-1",
        county="Loudoun",
        state="VA",
        permit_type="datacenter",
        permit_status="issued",
        issued_date=date.today(),
        applicant_name="Acme",
        raw_payload={},
    )


def _anomaly() -> Anomaly:
    return Anomaly(
        id=1,
        metric_kind="permit_filings_va",
        dimension="VA",
        period_end=date.today(),
        value=10.0,
        baseline_mean=2.0,
        baseline_stddev=1.0,
        z_score=8.0,
        direction="spike",
    )


def _edgar_extraction() -> EdgarExtraction:
    return EdgarExtraction(
        id=1,
        cik="0001",
        accession_number="0001-25-1",
        form_type="8-K",
        filing_date=date.today(),
        capacity_mw=200.0,
        buyer_raw="Microsoft",
        seller_raw="Constellation",
        edgar_url="https://example.com/8k",
        excerpt="...",
        parser_version="regex-v1",
        retrieved_at=datetime.now(timezone.utc),
    )


def _generator_permit() -> GeneratorPermit:
    return GeneratorPermit(
        id=1,
        source="epa_echo",
        facility_name="Site A",
        permittee_raw_name="Big Co",
        state_code="TX",
        rated_mw_total=300.0,
        fuel_type="gas",
        permit_status="active",
    )


def _data_coverage() -> DataCoverage:
    return DataCoverage(
        id=1,
        pillar="permits",
        state_code="VA",
        source="loudoun_va",
        coverage_status="partial",
        record_count=10,
        last_ingested_at=datetime.now(timezone.utc),
        freshness_sla_hours=24,
    )


def _top_dev_mapping() -> dict[str, Any]:
    return {
        "dev": "Microsoft",
        "curr_mw": 800.0,
        "prior_mw": 200.0,
        "delta": 600.0,
    }


# Order matches `_SECTION_BUILDERS` in hypothesizer.py:
#  1) top_capacity_movers_24h        (1 execute)
#  2) new_permits_24h                (1 execute)
#  3) anomalies_today                (1-2 executes; period_end first; falls
#     back to detected_at ONLY if first returns empty)
#  4) edgar_capacity_mentions_7d     (1 execute)
#  5) epa_echo_new_records_24h       (1 execute)
#  6) coverage_gaps                  (1 execute)
#  7) top_companies_by_delta_7d      (1 execute -- uses .mappings().all())
#  8) uncontracted_capacity_top_sites           (1 execute -- ORM scalars())
#  9) concentrated_offtake_sites                (1 execute -- raw mappings())
# 10) capacity_by_developer_with_low_offtake    (1 execute -- raw mappings())
# 11) epa_echo_high_mw_no_known_customer        (1 execute -- raw mappings())
def _uncontracted_project() -> Site:
    """Now a Site row (post-Phase-4 patch). Section queries `sites` rather
    than `energy_projects` because the latter is sparse in production."""
    return Site(
        id=2,
        aterio_dc_uid="aterio-uncontracted-fixture",
        building_name="Uncontracted Wind",
        provider_name="Acme Power",
        state_code="TX",
        stage="Active",
        power_capacity_mw=750.0,
        aterio_est_mw=None,
        end_user_companies=None,
    )


def _concentrated_offtake_mapping() -> dict[str, Any]:
    return {
        "id": 3,
        "building_name": "Single-Buyer Solar",
        "campus_name": None,
        "aterio_dc_uid": "aterio-single-buyer",
        "provider_name": "Acme Power",
        "state_code": "VA",
        "power_capacity_mw": 500.0,
        "end_user_companies": "OnlyCustomer Inc",
        "stage": "Construction",
        "q3": 400.0,
    }


def _low_offtake_dev_mapping() -> dict[str, Any]:
    return {
        "dev": "Acme Power",
        "total_mw": 1500.0,
        "n_projects": 4,
        "median_n_customers": 0.5,
    }


def _epa_echo_high_mw_mapping() -> dict[str, Any]:
    """Now an active/construction Site row (post-Phase-4 patch). Section name
    preserved for prompt compatibility; SQL repurposed because EPA ECHO
    rated_mw_total is NULL across the real dataset."""
    return {
        "id": 4,
        "building_name": "Big Permit Site",
        "campus_name": None,
        "aterio_dc_uid": "aterio-big-permit",
        "provider_name": "Big Co",
        "state_code": "TX",
        "power_capacity_mw": 600.0,
        "stage": "Construction",
        "aterio_est_mw": None,
    }


def _happy_path_responses() -> list[Any]:
    return [
        _FakeResult([_energy_project()]),
        _FakeResult([_building_permit()]),
        _FakeResult([_anomaly()]),  # period_end query returns >0 rows -> no fallback call
        _FakeResult([_edgar_extraction()]),
        _FakeResult([_generator_permit()]),
        _FakeResult([_data_coverage()]),
        _FakeResult([], mapping_rows=[_top_dev_mapping()]),
        # New supply/demand gap sections:
        _FakeResult([_uncontracted_project()]),  # uncontracted_capacity_top_sites (scalars)
        _FakeResult([], mapping_rows=[_concentrated_offtake_mapping()]),  # concentrated_offtake_sites
        _FakeResult([], mapping_rows=[_low_offtake_dev_mapping()]),  # capacity_by_developer_with_low_offtake
        _FakeResult([], mapping_rows=[_epa_echo_high_mw_mapping()]),  # epa_echo_high_mw_no_known_customer
    ]


# ---------------------------------------------------------------------------
# FactPack / FactSection / FactRow model unit tests
# ---------------------------------------------------------------------------


def test_factpack_lookup_preserves_input_order():
    pack = FactPack(
        generated_at=datetime.now(timezone.utc),
        sections=[
            FactSection(
                name="a",
                description="",
                rows=[FactRow(row_id="a:0"), FactRow(row_id="a:1")],
            ),
            FactSection(
                name="b",
                description="",
                rows=[FactRow(row_id="b:0")],
            ),
        ],
    )
    out = pack.lookup(["a:1", "b:0", "a:0", "ghost:99"])
    assert [r.row_id for r in out] == ["a:1", "b:0", "a:0"]


def test_factpack_total_rows():
    pack = FactPack(
        generated_at=datetime.now(timezone.utc),
        sections=[
            FactSection(name="a", description="",
                        rows=[FactRow(row_id="a:0"), FactRow(row_id="a:1")]),
            FactSection(name="b", description="", rows=[FactRow(row_id="b:0")]),
            FactSection(name="c", description="", rows=[]),
        ],
    )
    assert pack.total_rows() == 3


def test_factpack_to_compact_json_round_trips():
    pack = FactPack(
        generated_at=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
        sections=[
            FactSection(
                name="alpha",
                description="alpha section",
                rows=[FactRow(row_id="alpha:0", entity="Microsoft", value=42)],
            )
        ],
    )
    blob = pack.to_compact_json()

    # JSON must parse.
    parsed = json.loads(blob)
    assert "sections" in parsed
    assert parsed["sections"][0]["name"] == "alpha"
    assert parsed["sections"][0]["rows"][0]["row_id"] == "alpha:0"

    # Section name + row_id present in the raw text (as a basic sanity check).
    assert "alpha" in blob
    assert "alpha:0" in blob

    # Compactness: no pretty-printing whitespace -- separators=(",",":") so no
    # ", " or ": " sequences should appear in the compact form.
    assert ", " not in blob
    assert ": " not in blob
    assert "\n" not in blob


# ---------------------------------------------------------------------------
# build_factpack: shape + error containment + caps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_factpack_happy_path():
    session = _FakeSession(_happy_path_responses())
    pack = await build_factpack(session)

    # 11 sections, in the same order the builders were registered.
    expected_names = [
        "top_capacity_movers_24h",
        "new_permits_24h",
        "anomalies_today",
        "edgar_capacity_mentions_7d",
        "epa_echo_new_records_24h",
        "coverage_gaps",
        "top_companies_by_delta_7d",
        "uncontracted_capacity_top_sites",
        "concentrated_offtake_sites",
        "capacity_by_developer_with_low_offtake",
        "epa_echo_high_mw_no_known_customer",
    ]
    actual_names = [s.name for s in pack.sections]
    assert actual_names == expected_names

    # Each section has at least one row, and the first row_id is `<name>:0`.
    for section in pack.sections:
        assert len(section.rows) >= 1, f"{section.name} unexpectedly empty"
        assert section.rows[0].row_id == f"{section.name}:0"
        assert section.error is None, f"{section.name} reported error: {section.error}"

    assert pack.total_rows() >= 11


@pytest.mark.asyncio
async def test_build_factpack_section_error_isolated():
    """When the third section's query raises, that section ends up with
    rows=[] and a populated `error`, while the other 6 still have rows."""
    responses = _happy_path_responses()
    # Section 3 = anomalies_today. _safe_query swallows the first execute's
    # exception (period_end query) and returns []. With raw=[] empty, the
    # builder makes a second execute() call (detected_at fallback). To make
    # the section error-out cleanly, we replace BOTH attempts with
    # exceptions; _safe_query catches both -> rows=[] and section.error
    # will be None. To trigger section.error we need the OUTER builder to
    # raise. The cleanest way is to inject a callable that raises so the
    # exception escapes _safe_query -- but _safe_query catches Exception.
    # So instead we wrap the raise INSIDE _section_anomalies_today's outer
    # try by raising during result iteration. _safe_query only catches
    # exceptions from `await db.execute(stmt)` and `result.scalars().all()`.
    #
    # Mechanism: a _FakeResult whose .scalars().all() raises on the SECOND
    # access pattern -> still caught by _safe_query. To force the OUTER
    # try/except in build_factpack itself, we make the FAKE session raise
    # something the section builder won't catch. _safe_query catches all
    # `Exception`. Therefore: raising BaseException (not subclassing
    # Exception) escapes _safe_query but NOT build_factpack's outer
    # try/except (which catches Exception too). We need a generic Exception
    # that escapes _safe_query. That happens if exception is raised AFTER
    # _safe_query returns -- e.g. when iterating result rows in the
    # section builder. We model this by returning rows that look valid to
    # _safe_query but cause an AttributeError inside the builder loop.

    class _BadRow:
        # No `.dimension`, `.metric_kind`, etc. -> AttributeError when the
        # builder tries to read them. That AttributeError is raised AFTER
        # _safe_query returns, escaping that helper, but caught by the
        # outer try/except in build_factpack -> populates section.error.
        pass

    responses[2] = _FakeResult([_BadRow()])
    session = _FakeSession(responses)

    pack = await build_factpack(session)
    sections_by_name = {s.name: s for s in pack.sections}
    assert "anomalies_today" in sections_by_name
    assert sections_by_name["anomalies_today"].rows == []
    assert sections_by_name["anomalies_today"].error is not None

    # All 11 sections still present.
    assert len(pack.sections) == 11
    # Other 10 should each have at least one row.
    other_sections = [s for s in pack.sections if s.name != "anomalies_today"]
    assert len(other_sections) == 10
    for s in other_sections:
        assert len(s.rows) >= 1, f"{s.name} should have rows; got {s.rows!r}"


@pytest.mark.asyncio
async def test_build_factpack_caps_per_section():
    """If a builder somehow returns 50 rows, the section is trimmed to
    FACT_PACK_MAX_ROWS_PER_SECTION (12)."""
    big = [_energy_project() for _ in range(50)]
    responses = [
        _FakeResult(big),                 # top_capacity_movers_24h: 50 rows
        _FakeResult([_building_permit()]),
        _FakeResult([_anomaly()]),
        _FakeResult([_edgar_extraction()]),
        _FakeResult([_generator_permit()]),
        _FakeResult([_data_coverage()]),
        _FakeResult([], mapping_rows=[_top_dev_mapping()]),
    ]
    session = _FakeSession(responses)
    pack = await build_factpack(session)

    section = next(s for s in pack.sections if s.name == "top_capacity_movers_24h")
    assert len(section.rows) == FACT_PACK_MAX_ROWS_PER_SECTION


@pytest.mark.asyncio
async def test_build_factpack_row_id_format():
    """Every FactRow.row_id MUST match `<section_name>:<idx>`."""
    session = _FakeSession(_happy_path_responses())
    pack = await build_factpack(session)
    pat = re.compile(r"^[a-z_0-9]+:\d+$")
    for section in pack.sections:
        for row in section.rows:
            assert pat.match(row.row_id), f"bad row_id: {row.row_id}"
