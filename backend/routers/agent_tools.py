"""FastAPI tool-wrapper router for OpenClaw plugins.

Spec: docs/plans/ai-insights-automation/11b-openclaw-migration-architecture.md §3
Override: docs/plans/ai-insights-automation/11c-openclaw-migration-addendum.md §B/§G

Each of the seven AI-Insights chat tools is exposed here as an HTTP
endpoint that the OpenClaw plugin layer calls back into. Tool bodies
are imported from `agents.insights.tools.<name>` and invoked exactly
the way the in-process `agents.insights.tools.registry.dispatch` does
today; no tool body is reimplemented.

Auth: every endpoint requires a Bearer token equal to the env var
`AGENT_TOOLS_BEARER`. The compare uses `hmac.compare_digest` (constant
time). Missing env var means the router is disabled (503).

Wire format (POST):
    {
      "args":    { ... tool-specific ... },
      "context": {
        "insight_id":  "<uuid>",          # required
        "session_key": "<openclaw key>",  # optional, informational
        "thread_id":   "<uuid>"           # optional; derived if missing
      }
    }

Response:
    success -> {"ok": true, "result": <tool's dict>}
    failure -> {"ok": false, "error": "<repr>", "code": "TOOL_FAILED"}

Failure responses use HTTP 200 so the OpenClaw plugin can pass the
JSON straight back to the model rather than treating it as a network
error. Bearer mismatch returns 401; malformed bodies return 422 via
Pydantic validation.

Plus one GET endpoint:
    GET /api/agent-tools/insight-context?insight_id=<uuid>
returns the same dict that `_build_chat_context` produces in
`backend/routers/insights.py`. Used by the plugin's
`agent:bootstrap` hook (ADDENDUM 11c §G/§H).
"""
from __future__ import annotations

import hmac
import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session_factory
from agents.insights.skill_ctx_factory import (
    build_skill_ctx as _build_skill_ctx,
    _noop_emit_event,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/agent-tools", tags=["agent-tools"])


# ---------------------------------------------------------------------------
# Bearer auth
# ---------------------------------------------------------------------------


def _require_bearer(authorization: Optional[str] = Header(default=None)) -> None:
    """Verify the inbound Authorization header matches AGENT_TOOLS_BEARER.

    Behavior:
      - Missing env var (`AGENT_TOOLS_BEARER` empty)      -> 503.
      - Missing Authorization header                       -> 401.
      - Header does not match expected value (const time)  -> 401.
    """
    expected = os.environ.get("AGENT_TOOLS_BEARER", "") or ""
    if not expected:
        # Fail closed: router is inert until the operator wires the secret.
        raise HTTPException(status_code=503, detail="agent_tools_bearer_not_configured")

    if not authorization:
        raise HTTPException(status_code=401, detail="missing_bearer")

    presented = authorization.strip()
    target = f"Bearer {expected}"
    # constant-time compare across the full strings (including the Bearer
    # prefix). Both sides are ASCII so encoding is unambiguous.
    if not hmac.compare_digest(presented.encode("utf-8"), target.encode("utf-8")):
        raise HTTPException(status_code=401, detail="invalid_bearer")


# ---------------------------------------------------------------------------
# Wire-format Pydantic envelope
# ---------------------------------------------------------------------------


class _ToolContext(BaseModel):
    """Per-call routing context supplied by the OpenClaw plugin layer."""

    insight_id: str = Field(..., min_length=1)
    session_key: Optional[str] = Field(default=None, max_length=256)
    thread_id: Optional[str] = Field(default=None, max_length=64)
    session_id: Optional[str] = Field(default=None, max_length=64)


class _ToolEnvelope(BaseModel):
    """Top-level body shape for every POST /api/agent-tools/<tool>."""

    args: dict[str, Any] = Field(default_factory=dict)
    context: _ToolContext


# ---------------------------------------------------------------------------
# SkillContext factory — moved to agents.insights.skill_ctx_factory so the
# new MCP server in backend/mcp_server.py can share the exact same
# construction. The names `_build_skill_ctx` and `_noop_emit_event` are
# re-exported above (see import block) to keep the existing test suite's
# monkeypatch points stable.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Common invocation helper
# ---------------------------------------------------------------------------


async def _invoke_tool(tool_name: str, envelope: _ToolEnvelope) -> dict[str, Any]:
    """Invoke the named tool with `envelope.args` and a fresh DB session.

    Wraps any exception into the {"ok": false, ...} envelope so plugins
    can forward the JSON to the model verbatim (ARCH 11b §3.3).
    """
    try:
        insight_uuid = uuid.UUID(envelope.context.insight_id)
    except (ValueError, AttributeError) as exc:
        return {"ok": False, "error": f"bad_insight_id: {exc}", "code": "TOOL_FAILED"}

    db = async_session_factory()
    try:
        ctx = await _build_skill_ctx(
            db,
            insight_id=insight_uuid,
            thread_id_hint=envelope.context.thread_id,
            session_id_hint=envelope.context.session_id,
        )
        await db.commit()  # flush any thread-create from _build_skill_ctx

        # Lazy import to avoid heavy loads when this router is unused.
        from agents.insights.tools.registry import dispatch

        result = await dispatch(tool_name, dict(envelope.args or {}), ctx, db=db)
        return {"ok": True, "result": result}
    except HTTPException:
        # Re-raise FastAPI-shaped errors (404 etc.) so the proper status
        # code reaches the plugin layer.
        await _safe_rollback(db)
        raise
    except Exception as exc:  # noqa: BLE001 — surface every failure mode
        logger.exception("agent_tools.invoke_failed", extra={"tool": tool_name})
        await _safe_rollback(db)
        return {"ok": False, "error": str(exc), "code": "TOOL_FAILED"}
    finally:
        try:
            await db.close()
        except Exception:  # noqa: BLE001
            pass


async def _safe_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Tool endpoints (POST)
# ---------------------------------------------------------------------------


@router.post("/query_database", dependencies=[Depends(_require_bearer)])
async def post_query_database(envelope: _ToolEnvelope = Body(...)) -> dict[str, Any]:
    """Webhook for the `query_database` tool (ARCH 11b §3.4)."""
    return await _invoke_tool("query_database", envelope)


@router.post("/call_api", dependencies=[Depends(_require_bearer)])
async def post_call_api(envelope: _ToolEnvelope = Body(...)) -> dict[str, Any]:
    """Webhook for `call_api`."""
    return await _invoke_tool("call_api", envelope)


@router.post("/get_chart_data", dependencies=[Depends(_require_bearer)])
async def post_get_chart_data(envelope: _ToolEnvelope = Body(...)) -> dict[str, Any]:
    """Webhook for `get_chart_data`."""
    return await _invoke_tool("get_chart_data", envelope)


@router.post("/web_search", dependencies=[Depends(_require_bearer)])
async def post_web_search(envelope: _ToolEnvelope = Body(...)) -> dict[str, Any]:
    """Webhook for `web_search`."""
    return await _invoke_tool("web_search", envelope)


@router.post("/run_skill", dependencies=[Depends(_require_bearer)])
async def post_run_skill(envelope: _ToolEnvelope = Body(...)) -> dict[str, Any]:
    """Webhook for `run_skill`."""
    return await _invoke_tool("run_skill", envelope)


@router.post("/emit_chart", dependencies=[Depends(_require_bearer)])
async def post_emit_chart(envelope: _ToolEnvelope = Body(...)) -> dict[str, Any]:
    """Webhook for `emit_chart`."""
    return await _invoke_tool("emit_chart", envelope)


@router.post("/emit_citation", dependencies=[Depends(_require_bearer)])
async def post_emit_citation(envelope: _ToolEnvelope = Body(...)) -> dict[str, Any]:
    """Webhook for `emit_citation`."""
    return await _invoke_tool("emit_citation", envelope)


# ---------------------------------------------------------------------------
# GET /api/agent-tools/insight-context
# ---------------------------------------------------------------------------


@router.get("/insight-context", dependencies=[Depends(_require_bearer)])
async def get_insight_context(insight_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    """Return the bootstrap context bundle for an insight.

    Re-uses the existing `_build_chat_context(db, insight_id)` helper
    in `backend.routers.insights` (do NOT duplicate). Also returns
    `parent_session_id` and `thread_id` so the OpenClaw plugin can
    stash them on the session for downstream tool calls.
    """
    try:
        insight_uuid = uuid.UUID(insight_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad_insight_id: {exc}")

    # Lazy import to avoid an import cycle at module load.
    from routers.insights import _build_chat_context, _get_or_create_thread
    from agents.insights.db.models import AIInsight
    from sqlalchemy import select

    db = async_session_factory()
    try:
        ctx_payload = await _build_chat_context(db, insight_uuid)
        thread = await _get_or_create_thread(db, insight_id=insight_uuid)
        insight_row = (
            await db.execute(select(AIInsight).where(AIInsight.id == insight_uuid))
        ).scalar_one_or_none()
        parent_session_id = (
            str(insight_row.session_id) if insight_row is not None else None
        )
        await db.commit()
        return {
            **ctx_payload,
            "thread_id": str(thread.id),
            "parent_session_id": parent_session_id,
        }
    except HTTPException:
        await _safe_rollback(db)
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent_tools.insight_context_failed")
        await _safe_rollback(db)
        raise HTTPException(status_code=500, detail=f"insight_context_failed: {exc}")
    finally:
        try:
            await db.close()
        except Exception:  # noqa: BLE001
            pass
