"""Endpoint test for ``GET /api/insights/open-questions``.

Phase A AI Insights v2 (arch §1.7, §3 — MEMORY.md parsing contract).

We mount only the ``insights`` router under a tiny FastAPI app to avoid
pulling in the full ``main.py`` (which imports DB + every other router).
The route handler is self-contained — it only reads MEMORY.md from the
workspace dir resolved via ``OPENCLAW_WORKSPACE_DIR`` — so a partial
mount is sufficient.

Cases:
  * Happy path: 4 input bullets (one duplicate id, one malformed) ->
    list of 2, dedup keeps the latest by date, sorted by last_seen DESC.
  * Missing MEMORY.md -> 200 OK, ``[]``.
  * MEMORY.md present but no ``## open_questions`` section -> 200 OK, ``[]``.
"""
from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# routers.insights pulls in agents.insights orchestrator + DB models. That is
# the same heavy import path test_api_insights_latest.py already exercises in
# this suite, so doing it here is not a new dependency.
import routers.insights as insights_router_mod  # noqa: E402
from routers.insights import list_open_questions  # noqa: E402


# Memory fixture per the user's exact request.
MEMORY_MD_FIXTURE = """# MEMORY.md
## Open Questions
- q_crusoe-wy | watching | high | 720MW Wyoming, no offtaker  _<2026-05-06>_
- q_crusoe-wy | watching | high | 2026-05-07: +120MW DC-2 stage=construction  _<2026-05-07>_
- q_qts-va | disproved | low | permit data shows expected pause  _<2026-05-02>_
- malformed line without enough pipes
"""


@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    """Tiny FastAPI app that exposes only the open-questions route."""
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    # Wipe the in-process TTL cache so each test sees fresh state.
    monkeypatch.setattr(insights_router_mod, "_OQ_CACHE", None)

    app = FastAPI()
    sub = APIRouter(prefix="/api/insights", tags=["insights"])
    sub.add_api_route(
        "/open-questions",
        list_open_questions,
        methods=["GET"],
        response_model=list[insights_router_mod.OpenQuestion],
    )
    app.include_router(sub)
    yield app


async def _get(app, path):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_open_questions_parses_dedups_and_drops_malformed(app, tmp_path):
    (tmp_path / "MEMORY.md").write_text(MEMORY_MD_FIXTURE, encoding="utf-8")

    r = await _get(app, "/api/insights/open-questions")
    assert r.status_code == 200, r.text
    items = r.json()

    # 4 input bullets: q_crusoe-wy collapses to 1, q_qts-va kept,
    # malformed dropped -> 2 items total.
    assert len(items) == 2

    # q_crusoe-wy must show the 2026-05-07 entry as latest_note.
    by_id = {item["id"]: item for item in items}
    assert "q_crusoe-wy" in by_id
    assert "q_qts-va" in by_id

    crusoe = by_id["q_crusoe-wy"]
    assert "2026-05-07: +120MW DC-2 stage=construction" in crusoe["latest_note"]
    assert crusoe["last_seen_iso"].startswith("2026-05-07")
    assert crusoe["status"] == "watching"
    assert crusoe["materiality"] == "high"

    qts = by_id["q_qts-va"]
    assert qts["status"] == "disproved"
    assert qts["materiality"] == "low"
    assert qts["last_seen_iso"].startswith("2026-05-02")

    # Sorted by last_seen_iso DESC -> q_crusoe-wy first.
    assert items[0]["id"] == "q_crusoe-wy"
    assert items[1]["id"] == "q_qts-va"
    assert items[0]["last_seen_iso"] >= items[1]["last_seen_iso"]


@pytest.mark.asyncio
async def test_open_questions_returns_empty_when_memory_missing(app, tmp_path):
    # No MEMORY.md written -> graceful empty response.
    assert not (tmp_path / "MEMORY.md").exists()
    r = await _get(app, "/api/insights/open-questions")
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_open_questions_returns_empty_when_section_missing(app, tmp_path):
    # File present but no ## open_questions header.
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY.md\n\n## Recent decisions\n- something else _<2026-05-07>_\n",
        encoding="utf-8",
    )
    r = await _get(app, "/api/insights/open-questions")
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_open_questions_section_with_no_bullets_returns_empty(app, tmp_path):
    # Section header present but body is empty / non-bullet text only.
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY.md\n\n## Open Questions\n\n(none yet)\n\n## Next section\n",
        encoding="utf-8",
    )
    r = await _get(app, "/api/insights/open-questions")
    assert r.status_code == 200, r.text
    assert r.json() == []
