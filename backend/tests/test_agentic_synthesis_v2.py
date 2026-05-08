"""Phase C tests for `run_agentic_synthesis` v1/v2 prompt branching.

We don't re-test the full SSE drive here -- `test_agentic_synthesis.py`
locks down the loop. This file pins the *prompt assembly* contract so:

  * v1 (default) loads `synthesis_rules.md` and the user message contains
    a `factpack_digest` + `instructions` block.
  * v2 loads `synthesis_rules_v2.md` and the user message contains
    `workspace_pointers` and NO factpack_digest.
  * v1 stays byte-identical to the pre-Phase-C contract.

Mock `_drive_openclaw_stream` to capture the messages and short-circuit
the loop with a degraded StreamResult so the test is deterministic.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import agents  # noqa: E402,F401
import agents.insights  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDB:
    async def execute(self, *a, **k):
        class _R:
            def scalar_one_or_none(self_inner):
                return None
            def first(self_inner):
                return None
        return _R()

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _empty_factpack():
    """Return an empty FactPack stand-in usable by v1's _factpack_digest."""
    from datetime import datetime, timezone

    from agents.insights.hypothesizer import FactPack

    return FactPack(sections=[], generated_at=datetime.now(timezone.utc))


def _make_stream_result(degraded=True, reason="forced_break"):
    from openclaw.forwarder import StreamResult

    return StreamResult(degraded=degraded, reason=reason, total_chunks=0)


# ---------------------------------------------------------------------------
# v1 baseline (must stay byte-identical)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_loads_synthesis_rules_md_and_includes_factpack():
    from agents.insights.agentic_synthesis import run_agentic_synthesis

    captured: dict[str, Any] = {}

    async def _fake_drive(**kwargs):
        captured.update(kwargs)
        return _make_stream_result()

    with patch(
        "agents.insights.agentic_synthesis._drive_openclaw_stream",
        side_effect=_fake_drive,
    ):
        await run_agentic_synthesis(
            session_id=uuid.uuid4(),
            fact_pack=_empty_factpack(),
            max_insights=3,
            db=_FakeDB(),  # type: ignore[arg-type]
            sse_emit=None,
            cron_run_date=None,
            mode="manual",
            # version omitted -> defaults to v1
        )

    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    sys_body = messages[0]["content"]
    # The v1 prompt is the original; reading the file directly confirms
    # we did not silently swap to v2.
    from agents.insights.prompts import load_prompt

    assert sys_body == load_prompt("synthesis_rules")

    user_payload = json.loads(messages[1]["content"])
    assert "factpack_digest" in user_payload
    assert "instructions" in user_payload
    assert "workspace_pointers" not in user_payload


# ---------------------------------------------------------------------------
# v2 branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_loads_synthesis_rules_v2_and_omits_factpack():
    from agents.insights.agentic_synthesis import run_agentic_synthesis

    captured: dict[str, Any] = {}

    async def _fake_drive(**kwargs):
        captured.update(kwargs)
        return _make_stream_result()

    with patch(
        "agents.insights.agentic_synthesis._drive_openclaw_stream",
        side_effect=_fake_drive,
    ):
        await run_agentic_synthesis(
            session_id=uuid.uuid4(),
            fact_pack=_empty_factpack(),
            max_insights=4,
            db=_FakeDB(),  # type: ignore[arg-type]
            sse_emit=None,
            cron_run_date=None,
            mode="manual",
            version="v2",
        )

    messages = captured["messages"]
    sys_body = messages[0]["content"]
    from agents.insights.prompts import load_prompt

    assert sys_body == load_prompt("synthesis_rules_v2")
    # v2 prompt must reference (not restate) the playbook + preflight.
    assert "AI_INSIGHTS_PLAYBOOK.md" in sys_body
    assert "AI_INSIGHTS_PREFLIGHT_CHECKLIST.md" in sys_body
    # v2 prompt must stay slim.
    assert len(sys_body.encode("utf-8")) < 4_096

    user_payload = json.loads(messages[1]["content"])
    assert user_payload["version"] == "v2"
    assert user_payload["workspace_pointers"] == ["SCHEMA.md", "FRESHNESS.md"]
    assert "factpack_digest" not in user_payload
    assert "instructions" not in user_payload
    assert int(user_payload["max_insights"]) == 4


@pytest.mark.asyncio
async def test_v2_caps_unchanged():
    """Caps (12 turns, 30 tool calls, 600s wall) must be the same in v2."""
    from agents.insights.agentic_synthesis import run_agentic_synthesis

    captured: dict[str, Any] = {}

    async def _fake_drive(**kwargs):
        captured.update(kwargs)
        return _make_stream_result()

    with patch(
        "agents.insights.agentic_synthesis._drive_openclaw_stream",
        side_effect=_fake_drive,
    ):
        await run_agentic_synthesis(
            session_id=uuid.uuid4(),
            fact_pack=_empty_factpack(),
            max_insights=3,
            db=_FakeDB(),  # type: ignore[arg-type]
            version="v2",
        )

    assert captured["cap_turns"] == 12
    assert captured["cap_tool_calls"] == 30
    assert captured["cap_wall_seconds"] == 600.0
