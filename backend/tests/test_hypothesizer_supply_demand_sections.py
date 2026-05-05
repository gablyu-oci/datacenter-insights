"""Unit tests for the four supply/demand-gap section builders.

After the post-Phase-4 patch, these sections query the `sites` table
(operator-vs-tenant gap data) instead of `energy_projects` (which is sparsely
populated and gives 0 rows in production). Section names + row_id format
preserved for prompt/SSE compatibility; SQL + FactRow shape rewritten.

Sections under test (registered after `top_companies_by_delta_7d`):
  - uncontracted_capacity_top_sites           (ORM scalars over Site)
  - concentrated_offtake_sites                (raw SQL, sites + per-state q3)
  - capacity_by_developer_with_low_offtake    (raw SQL, sites grouped by provider)
  - epa_echo_high_mw_no_known_customer        (raw SQL, sites filtered to
                                               Active/Construction stages)

A separate test asserts the system-prompt SUPPLY/DEMAND GAPS bullet still
ships.
"""
from __future__ import annotations

from typing import Any

import pytest

from agents.insights.hypothesizer import (
    _SYSTEM_PROMPT,
    _section_capacity_by_developer_with_low_offtake,
    _section_concentrated_offtake_sites,
    _section_epa_echo_high_mw_no_known_customer,
    _section_uncontracted_capacity_top_sites,
    build_factpack,
)
from db.models import Site


# ---------------------------------------------------------------------------
# Fake AsyncSession — same protocol as test_hypothesizer_factpack.py
# ---------------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeMappings:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeResult:
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
    """Returns canned `_FakeResult`s in order; missing entries -> empty."""

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
        return _FakeResult([])


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_uncontracted_site() -> Site:
    """A Site with power_capacity_mw set but no end_user_companies — should
    match the uncontracted_capacity_top_sites filter."""
    return Site(
        id=1001,
        aterio_dc_uid="aterio-uncontracted-1",
        building_name="Ernsberger Rd Data Center",
        provider_name="EnergiAcres",
        state_code="OH",
        stage="Not Approved/Withdrawn",
        power_capacity_mw=900.0,
        aterio_est_mw=None,
        end_user_companies=None,
    )


def _concentrated_offtake_mapping() -> dict[str, Any]:
    return {
        "id": 1002,
        "building_name": "Memphis Supercluster AI Data Center (Phase 3)",
        "campus_name": None,
        "aterio_dc_uid": "aterio-memphis-3",
        "provider_name": "xAI",
        "state_code": "MS",
        "power_capacity_mw": 700.0,
        "end_user_companies": "xAI",
        "stage": "Construction",
        "q3": 66.0,
    }


def _low_offtake_dev_mapping() -> dict[str, Any]:
    return {
        "dev": "Amazon AWS",
        "total_mw": 39847.43,
        "n_projects": 702,
        "median_n_customers": 0.0,
    }


def _epa_echo_active_stage_mapping() -> dict[str, Any]:
    return {
        "id": 1003,
        "building_name": "Wyoming Crusoe DC-1",
        "campus_name": None,
        "aterio_dc_uid": "aterio-crusoe-wy-1",
        "provider_name": "Crusoe",
        "state_code": "WY",
        "power_capacity_mw": 360.0,
        "stage": "Construction",
        "aterio_est_mw": 84.2,
    }


# ---------------------------------------------------------------------------
# uncontracted_capacity_top_sites (ORM scalars())
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uncontracted_capacity_top_sites_empty():
    session = _FakeSession([_FakeResult([])])
    section = await _section_uncontracted_capacity_top_sites(session)
    assert section.name == "uncontracted_capacity_top_sites"
    assert section.rows == []
    assert section.error is None


@pytest.mark.asyncio
async def test_uncontracted_capacity_top_sites_populated():
    session = _FakeSession([_FakeResult([_make_uncontracted_site()])])
    section = await _section_uncontracted_capacity_top_sites(session)
    assert section.name == "uncontracted_capacity_top_sites"
    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.row_id == "uncontracted_capacity_top_sites:0"
    assert row.entity == "Ernsberger Rd Data Center"
    assert row.metric == "power_capacity_mw_unsold"
    assert row.value == 900.0
    assert row.detail == {
        "provider": "EnergiAcres",
        "state": "OH",
        "stage": "Not Approved/Withdrawn",
        "aterio_est_mw": None,
    }


# ---------------------------------------------------------------------------
# concentrated_offtake_sites (raw mappings())
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concentrated_offtake_sites_empty():
    session = _FakeSession([_FakeResult([], mapping_rows=[])])
    section = await _section_concentrated_offtake_sites(session)
    assert section.name == "concentrated_offtake_sites"
    assert section.rows == []
    assert section.error is None


@pytest.mark.asyncio
async def test_concentrated_offtake_sites_populated():
    session = _FakeSession(
        [_FakeResult([], mapping_rows=[_concentrated_offtake_mapping()])]
    )
    section = await _section_concentrated_offtake_sites(session)
    assert section.name == "concentrated_offtake_sites"
    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.row_id == "concentrated_offtake_sites:0"
    assert row.entity == "Memphis Supercluster AI Data Center (Phase 3)"
    assert row.metric == "power_capacity_mw_single_tenant"
    assert row.value == 700.0
    assert row.detail == {
        "provider": "xAI",
        "state": "MS",
        "end_user": "xAI",
        "state_q3_threshold": 66.0,
        "stage": "Construction",
    }


# ---------------------------------------------------------------------------
# capacity_by_developer_with_low_offtake (raw mappings())
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capacity_by_developer_with_low_offtake_empty():
    session = _FakeSession([_FakeResult([], mapping_rows=[])])
    section = await _section_capacity_by_developer_with_low_offtake(session)
    assert section.name == "capacity_by_developer_with_low_offtake"
    assert section.rows == []
    assert section.error is None


@pytest.mark.asyncio
async def test_capacity_by_developer_with_low_offtake_populated():
    session = _FakeSession(
        [_FakeResult([], mapping_rows=[_low_offtake_dev_mapping()])]
    )
    section = await _section_capacity_by_developer_with_low_offtake(session)
    assert section.name == "capacity_by_developer_with_low_offtake"
    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.row_id == "capacity_by_developer_with_low_offtake:0"
    assert row.entity == "Amazon AWS"
    assert row.metric == "developer_pipeline_mw_low_offtake"
    assert row.value == 39847.43
    assert row.detail == {
        "n_projects": 702,
        "median_n_customers": 0.0,
    }


# ---------------------------------------------------------------------------
# epa_echo_high_mw_no_known_customer (raw mappings())
# Section name preserved; underlying signal repurposed to active/construction
# sites with capacity but no offtaker (EPA ECHO rated_mw_total is NULL in the
# real dataset, so the original query yielded zero rows).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epa_echo_high_mw_no_known_customer_empty():
    session = _FakeSession([_FakeResult([], mapping_rows=[])])
    section = await _section_epa_echo_high_mw_no_known_customer(session)
    assert section.name == "epa_echo_high_mw_no_known_customer"
    assert section.rows == []
    assert section.error is None


@pytest.mark.asyncio
async def test_epa_echo_high_mw_no_known_customer_populated():
    session = _FakeSession(
        [_FakeResult([], mapping_rows=[_epa_echo_active_stage_mapping()])]
    )
    section = await _section_epa_echo_high_mw_no_known_customer(session)
    assert section.name == "epa_echo_high_mw_no_known_customer"
    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.row_id == "epa_echo_high_mw_no_known_customer:0"
    assert row.entity == "Wyoming Crusoe DC-1"
    assert row.metric == "active_stage_uncontracted_mw"
    assert row.value == 360.0
    assert row.detail == {
        "provider": "Crusoe",
        "state": "WY",
        "stage": "Construction",
        "aterio_est_mw": 84.2,
    }


# ---------------------------------------------------------------------------
# build_factpack integration: the four new sections sit at indices 7-10.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supply_demand_sections_present_in_factpack(monkeypatch):
    """All four new sections are registered (in order) and surface in the
    pack returned by `build_factpack`, even when their queries return no
    rows.

    We feed the FakeSession only enough empty results to satisfy each
    section; the underlying builders never raise, so each new section
    shows up with rows=[] and error=None.
    """
    monkeypatch.delenv("AI_INSIGHTS_FAKE_LLM", raising=False)
    # 7 existing builders + 4 new = 11. Anomalies builder may issue a 2nd
    # execute on empty; FakeSession returns empty defaults beyond the
    # queue, so any extra calls are safely absorbed.
    responses = [_FakeResult([], mapping_rows=[]) for _ in range(20)]
    session = _FakeSession(responses)
    pack = await build_factpack(session)

    names = [s.name for s in pack.sections]
    assert names[-4:] == [
        "uncontracted_capacity_top_sites",
        "concentrated_offtake_sites",
        "capacity_by_developer_with_low_offtake",
        "epa_echo_high_mw_no_known_customer",
    ]
    for s in pack.sections[-4:]:
        assert s.rows == []
        assert s.error is None


# ---------------------------------------------------------------------------
# System-prompt bullet for supply/demand-gap framing.
# ---------------------------------------------------------------------------


def test_system_prompt_mentions_supply_demand_gaps():
    assert "SUPPLY/DEMAND GAPS" in _SYSTEM_PROMPT
    assert "potentially contractable" in _SYSTEM_PROMPT
