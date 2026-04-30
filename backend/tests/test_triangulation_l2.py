"""
Tests for Triangulation L2 (compute-demand layer).

Strategy: monkeypatch the two helpers at module level
  - agents.triangulation.nvidia_data_center_latest
  - agents.triangulation.contracted_gw_map

so the math/shape can be exercised without a live DB. The endpoint
test reuses the same monkeypatch trick and FastAPI's TestClient.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# Synthetic helper returns
# ---------------------------------------------------------------------------

def _synthetic_payload():
    """The shape nvidia_data_center_latest() emits for a real row."""
    return (
        {
            "headline": "synthetic NVIDIA Data Center segment row",
            "segment_name": "Data Center",
            "period_end": "2025-04-27",
            "revenue_usd": 100_000_000_000,
            "inventory_usd": 21_000_000_000,
            "purchase_commitments_usd": None,
            "customer_concentration_pct": None,
            "narrative_excerpt": "synthetic",
        },
        "2025-04-27",
    )


def _synthetic_contracted_map():
    return {
        "Microsoft": 10.47,
        "Amazon": 17.9,
        "Google": 12.75,
        "Oracle": 11.6,
        "Meta": 7.0,
    }


# ---------------------------------------------------------------------------
# Pure math tests (no DB, no network)
# ---------------------------------------------------------------------------

def test_math_basic(monkeypatch):
    """L2 math — known-revenue case end-to-end."""
    import agents.triangulation as tri

    async def _fake_nvidia(_session):
        return _synthetic_payload()

    async def _fake_map(_session):
        return _synthetic_contracted_map()

    monkeypatch.setattr(tri, "nvidia_data_center_latest", _fake_nvidia)
    monkeypatch.setattr(tri, "contracted_gw_map", _fake_map)

    out = asyncio.run(tri.compute_l2(session=None))

    assert out["nvidia_dc_revenue_usd"] == 100_000_000_000
    assert out["nvidia_inventory_usd"] == 21_000_000_000
    assert out["period_end"] == "2025-04-27"
    assert out["inferred_units_total"] == 2_857_142

    # 2_857_142 * 850 * 0.6 * 1.4 / 1e9 = ~2.04, rounded to 1 decimal = 2.0;
    # tolerance window in the brief is < 0.05, so either is acceptable.
    assert abs(out["inferred_compute_gw"] - 2.04) < 0.05

    shares = out["per_hyperscaler_share"]
    assert len(shares) == 5

    summed = sum(h["implied_compute_gw"] for h in shares)
    assert abs(summed - out["inferred_compute_gw"]) < 0.01

    microsoft = next(h for h in shares if h["company"] == "Microsoft")
    assert microsoft["contracted_gw"] == 10.47
    assert microsoft["status"] in ("overcontracted", "undercontracted")
    # Microsoft contracted 10.47 GW vs ~0.36 GW implied → overcontracted.
    assert microsoft["status"] == "overcontracted"


def test_no_data(monkeypatch):
    """Helpers return (None, None) and {} → endpoint returns sensible zeros."""
    import agents.triangulation as tri

    async def _fake_nvidia(_session):
        return (None, None)

    async def _fake_map(_session):
        return {}

    monkeypatch.setattr(tri, "nvidia_data_center_latest", _fake_nvidia)
    monkeypatch.setattr(tri, "contracted_gw_map", _fake_map)

    out = asyncio.run(tri.compute_l2(session=None))

    assert out["nvidia_dc_revenue_usd"] is None
    assert out["inferred_compute_gw"] == 0 or out["inferred_compute_gw"] == 0.0
    assert out["inferred_units_total"] == 0
    assert out["per_hyperscaler_share"] == []

    # Assumptions block must still be present so the UI can render it.
    a = out["assumptions"]
    assert a["avg_gpu_price_usd"] == 35_000
    assert a["avg_blended_power_w"] == 850


# ---------------------------------------------------------------------------
# Endpoint shape (FastAPI TestClient + monkeypatched helpers)
# ---------------------------------------------------------------------------

def test_endpoint_shape(monkeypatch):
    """GET /api/triangulation/l2 returns CoverageEnvelope with expected keys."""
    import agents.triangulation as tri

    async def _fake_nvidia(_session):
        return _synthetic_payload()

    async def _fake_map(_session):
        return _synthetic_contracted_map()

    monkeypatch.setattr(tri, "nvidia_data_center_latest", _fake_nvidia)
    monkeypatch.setattr(tri, "contracted_gw_map", _fake_map)

    # The router calls async_session_factory() to get a session; we don't
    # care about the session itself because the helpers are stubbed, but
    # the context-manager protocol still has to work. Patch the factory
    # to a no-op async context manager that yields None.
    class _NullSessionCtx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    import routers.triangulation as r_tri

    monkeypatch.setattr(r_tri, "async_session_factory", lambda: _NullSessionCtx())

    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.get("/api/triangulation/l2")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "data" in body
    assert "lineage" in body
    assert "coverage" in body

    a = body["data"]["assumptions"]
    for key in (
        "avg_gpu_price_usd",
        "avg_blended_power_w",
        "utilization_pct",
        "overhead_multiplier",
        "h100_avg_power_w",
        "b200_avg_power_w",
    ):
        assert key in a, f"missing assumption key: {key}"

    assert body["lineage"]["parser_version"] == "l2-v1"
    assert body["lineage"]["source_url"] == "internal://triangulation-l2"
    assert body["coverage"]["pillar"] == "triangulation"
