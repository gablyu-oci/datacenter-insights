"""MCP server for the strategic-insights backend.

PRD : docs/plans/ai-insights-automation/13-mcp-migration-prd.md
ARCH: docs/plans/ai-insights-automation/13-mcp-migration-architecture.md
RES : docs/plans/ai-insights-automation/13-mcp-migration-research.md

What this module does
---------------------
Exposes the seven existing AI-Insights chat tools (defined in
``backend/agents/insights/tools/``) as MCP tools over streamable-HTTP,
mounted at ``/mcp`` on the parent FastAPI app. The OpenClaw gateway,
running in a sibling container, discovers these tools at startup and
calls them on every chat turn (when ``OPENCLAW_ENABLED=1``).

Tool bodies are NOT reimplemented here. Each ``@mcp.tool()`` handler
is a thin shim that:

  1. Validates ``insight_id`` is a UUID.
  2. Opens a fresh async DB session.
  3. Builds a ``SkillContext`` via the shared factory in
     ``agents.insights.skill_ctx_factory.build_skill_ctx`` — the SAME
     factory the legacy HTTP router (``backend/routers/agent_tools.py``)
     uses, so the two lanes are bit-for-bit equivalent.
  4. Invokes ``agents.insights.tools.registry.dispatch(name, args, ctx)``.
  5. Wraps any failure into ``{ok: false, error, code: "TOOL_FAILED"}``.

Auth
----
A Starlette ``AuthenticationMiddleware`` with the ``StaticBearer``
backend defined below guards the mount. Behaviour mirrors
``routers.agent_tools._require_bearer``:

  * ``AGENT_TOOLS_BEARER`` env unset/empty -> 503
  * Missing or wrong header                 -> 401
  * Correct header                          -> 200

Mount geometry
--------------
``streamable_http_app()`` returns a Starlette app whose only route
is ``/mcp`` pointing at a ``StreamableHTTPASGIApp``. Mounting that
Starlette directly at ``/mcp`` on the FastAPI parent would yield
``/mcp/mcp`` (issue mcp-python-sdk #1367). To avoid the doubling
we extract the underlying ASGI app and place it at ``/`` of a
fresh sub-Starlette, then mount that sub at ``/mcp`` on the parent.
The sub also carries the auth middleware so it applies only to
``/mcp/*`` and nothing else.

Lifespan
--------
The streamable-HTTP transport relies on a ``Task group`` initialised
by the inner Starlette's lifespan handler. FastAPI does NOT propagate
mounted-app lifespans automatically (issue #1367). ``mount_mcp``
composes the inner lifespan with whatever lifespan the parent FastAPI
already declares, so neither is dropped.
"""
from __future__ import annotations

import hmac
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

try:
    # mcp >= 1.10 ships TransportSecuritySettings here. We use it to
    # whitelist host.docker.internal so OpenClaw (running in a sibling
    # container) can reach the mount under that hostname without being
    # rejected by FastMCP's DNS-rebinding protection.
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover — defensive for older SDKs
    TransportSecuritySettings = None  # type: ignore[assignment]
from starlette.applications import Starlette
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
)
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

# ``stateless_http=True`` (research §5) keeps each request independent —
# we have no per-session server state and don't want the SDK to spin up
# session bookkeeping. ``json_response=True`` returns plain JSON bodies
# instead of SSE-framed ones; OpenClaw's MCP client accepts either, and
# JSON keeps the test harness simpler.
# DNS-rebinding allow list. FastMCP's default rejects requests whose
# Host header is not localhost/127.0.0.1; OpenClaw (running in a
# sibling container) reaches us via ``host.docker.internal:8002`` so
# that hostname has to be added explicitly. Wildcards are supported per
# TransportSecuritySettings — ``host.docker.internal:*`` covers any
# port the FastAPI is bound to.
_ALLOWED_HOSTS = [
    "host.docker.internal",
    "host.docker.internal:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
]

_mcp_kwargs: dict[str, Any] = {
    "json_response": True,
    "stateless_http": True,
}
if TransportSecuritySettings is not None:
    _mcp_kwargs["transport_security"] = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_ALLOWED_HOSTS,
    )

mcp = FastMCP("strategic-insights", **_mcp_kwargs)


# ---------------------------------------------------------------------------
# Shared invoke helper
# ---------------------------------------------------------------------------


async def _safe_rollback(db: Any) -> None:
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass


async def _invoke_session(
    name: str,
    session_id: str,
    args: dict[str, Any],
    *,
    thread_id: Optional[str] = None,
) -> dict[str, Any]:
    """Session-scoped sibling of `_invoke` for write-tools that target a
    parent ``ai_session`` row rather than an existing insight (Phase 2 /
    PRD/ARCH 14 §3.1).

    Differences from `_invoke`:
      - Validates ``session_id`` (UUID), not ``insight_id``.
      - Does NOT build a SkillContext (no current-insight scope).
      - Per-tool body is provided via the registry below; envelope shape
        and error handling mirror `_invoke` so OpenClaw sees a uniform
        ``{ok, result|error, code}`` from every MCP tool.

    Auth (StaticBearer) is enforced at the ASGI mount layer; tools do
    not re-check the bearer token here.
    """
    try:
        session_uuid = uuid.UUID(session_id)
    except (ValueError, TypeError, AttributeError) as exc:
        return {
            "ok": False,
            "error": f"bad_session_id: {exc}",
            "code": "BAD_INPUT",
        }

    from db.session import async_session_factory

    db = async_session_factory()
    try:
        from agents.insights import session_tools

        handler = session_tools.HANDLERS.get(name)
        if handler is None:
            return {
                "ok": False,
                "error": f"unknown_session_tool:{name}",
                "code": "TOOL_FAILED",
            }
        result = await handler(db, session_uuid, args)
        await db.commit()
        return {"ok": True, "result": result, "code": 0}
    except session_tools.ToolValidationError as exc:
        await _safe_rollback(db)
        return {
            "ok": False,
            "error": str(exc),
            "code": exc.code,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("mcp.session_invoke_failed", extra={"tool": name})
        await _safe_rollback(db)
        return {"ok": False, "error": str(exc), "code": "TOOL_FAILED"}
    finally:
        try:
            await db.close()
        except Exception:  # noqa: BLE001
            pass


async def _invoke(
    name: str,
    insight_id: str,
    args: dict[str, Any],
    *,
    thread_id: Optional[str],
    session_id: Optional[str],
) -> dict[str, Any]:
    """Resolve a SkillContext and dispatch to the named tool.

    Mirrors ``backend/routers/agent_tools.py::_invoke_tool`` so the
    OpenClaw lane and the curl-test lane share identical envelopes.
    """
    # Validate insight_id up front; the tool registry expects a real UUID
    # threaded through the SkillContext.
    try:
        insight_uuid = uuid.UUID(insight_id)
    except (ValueError, TypeError, AttributeError) as exc:
        return {"ok": False, "error": f"bad_insight_id: {exc}", "code": "TOOL_FAILED"}

    # Lazy import — these modules pull in the agents stack which is
    # heavy; defer until first call so module import stays cheap.
    from db.session import async_session_factory
    from agents.insights.skill_ctx_factory import build_skill_ctx

    db = async_session_factory()
    try:
        ctx = await build_skill_ctx(
            db,
            insight_id=insight_uuid,
            thread_id_hint=thread_id,
            session_id_hint=session_id,
        )
        # Flush any thread-create from build_skill_ctx so subsequent
        # tool bodies see the row.
        await db.commit()

        from agents.insights.tools.registry import dispatch

        result = await dispatch(name, args, ctx)
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 — surface every failure mode
        logger.exception("mcp.invoke_failed", extra={"tool": name})
        await _safe_rollback(db)
        return {"ok": False, "error": str(exc), "code": "TOOL_FAILED"}
    finally:
        try:
            await db.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Tool handlers (7) — see ARCH §3 for handler-by-handler rationale
# ---------------------------------------------------------------------------


@mcp.tool()
async def query_database(
    insight_id: str,
    sql: str,
    max_rows: int = 10000,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run a single read-only SELECT against the strategic-insights Postgres.

    Returns rows + row_hash + executed_sql. Max 10000 rows. The
    ``sql_gate.validate_sql`` AST validator runs inside the underlying
    tool body — MCP never sees a raw-SQL bypass.
    """
    return await _invoke(
        "query_database",
        insight_id,
        {"sql": sql, "max_rows": max_rows},
        thread_id=thread_id,
        session_id=session_id,
    )


@mcp.tool()
async def call_api(
    insight_id: str,
    endpoint: str,
    params: Optional[dict[str, Any]] = None,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Invoke an internal /api/ endpoint in-process. GET only.

    Use for fetching aggregated views from the existing routers.
    """
    return await _invoke(
        "call_api",
        insight_id,
        {"endpoint": endpoint, "params": params or {}},
        thread_id=thread_id,
        session_id=session_id,
    )


@mcp.tool()
async def get_chart_data(
    insight_id: str,
    tab: str,
    chart_id: str,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Fetch the data behind a known chart on an existing tab.

    Use for warm-start triangulation.
    """
    return await _invoke(
        "get_chart_data",
        insight_id,
        {"tab": tab, "chart_id": chart_id},
        thread_id=thread_id,
        session_id=session_id,
    )


@mcp.tool()
async def web_search(
    insight_id: str,
    query: str,
    n: int = 5,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """V2: run a Brave Search query and return up to 5 results.

    Per-session cap: 8 calls. Snippets are pre-truncated to 280
    characters. If the API key is missing or the upstream circuit is
    open, the tool returns degraded=true with a reason.
    """
    return await _invoke(
        "web_search",
        insight_id,
        {"query": query, "n": n},
        thread_id=thread_id,
        session_id=session_id,
    )


@mcp.tool()
async def run_skill(
    insight_id: str,
    skill_name: str,
    inputs: dict[str, Any],
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Invoke a converted analytics skill.

    The dispatcher injects the skill's process fragment + RAG chunks for
    the next reasoning turn only. ``skill_name`` must be one of the 15
    known skills; the enum is enforced in the underlying tool body
    rather than the MCP schema (avoids module-load coupling to
    ``ALL_SKILLS``).
    """
    return await _invoke(
        "run_skill",
        insight_id,
        {"skill_name": skill_name, "inputs": inputs},
        thread_id=thread_id,
        session_id=session_id,
    )


@mcp.tool()
async def emit_chart(
    insight_id: str,
    spec: dict[str, Any],
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Emit a final ChartSpec for the current insight.

    The spec is validated and the row_hash recomputed at server side.
    The ``spec`` argument IS the ChartSpec dict — it is passed straight
    to the ``emit_chart`` tool body which expects a free-form object.
    """
    # ARCH §3.6: emit_chart's input is a free-form ChartSpec; the tool
    # body receives the spec dict as its args, not a wrapper around it.
    return await _invoke(
        "emit_chart",
        insight_id,
        spec,
        thread_id=thread_id,
        session_id=session_id,
    )


@mcp.tool()
async def emit_citation(
    insight_id: str,
    url: str,
    title: str,
    snippet: str,
    agree_or_disagree: str,
    rationale: str,
    search_query: str,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """V2: persist + emit a validated web citation for the current insight.

    Validates snippet <=280 chars, agree_or_disagree enum, URL
    reachability (HEAD 2xx/3xx), and rationale-substring-of-snippet.
    agree/disagree tags require a numeric GW/MW/%/$ token in the
    snippet else are downgraded to 'context'.
    """
    return await _invoke(
        "emit_citation",
        insight_id,
        {
            "url": url,
            "title": title,
            "snippet": snippet,
            "agree_or_disagree": agree_or_disagree,
            "rationale": rationale,
            "search_query": search_query,
        },
        thread_id=thread_id,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Phase 2 (PRD/ARCH 14) — session-scoped write tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def persist_insight(
    session_id: str,
    insight: dict[str, Any],
    supporting_row_ids: list[str],
) -> dict[str, Any]:
    """Persist one insight under a synthesis ai_session.

    Args:
      session_id: UUID of the parent ai_session (must exist + be running).
      insight: dict matching `agents.insights.hypothesizer.InsightOutput`
        — headline, body, confidence_signal, materiality, plus optional
        chart_type / chart_y_label.
      supporting_row_ids: row_ids drawn from the session's FactPack;
        ids that do not match the FactPack are filtered out
        server-side (mirrors `_coerce_insights` filtering, FR-2.4).

    Returns:
      Standard envelope. On success: ``{ok:True, result:{insight_id, idx}, code:0}``.
    """
    return await _invoke_session(
        "persist_insight",
        session_id,
        {"insight": insight, "supporting_row_ids": supporting_row_ids},
    )


@mcp.tool()
async def finalize_session(
    session_id: str,
    status: str,
    token_estimate: int = 0,
) -> dict[str, Any]:
    """Flip an ai_session row to a terminal status.

    Args:
      session_id: UUID of the ai_session to finalize.
      status: one of ``"complete"`` | ``"degraded"`` | ``"failed"``.
        ``"complete"`` is the agentic equivalent of the legacy
        ``"complete"`` enum value used by the V1 orchestrator.
      token_estimate: best-effort token count; persisted into
        ai_session.token_estimate (>= 0).

    Returns:
      ``{ok:True, result:{session_id, status}, code:0}`` on success.
    """
    return await _invoke_session(
        "finalize_session",
        session_id,
        {"status": status, "token_estimate": int(token_estimate or 0)},
    )


@mcp.tool()
async def persist_brief(
    session_id: str,
    sections: dict[str, Any],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist a weekly brief.

    Phase 2 stub — full BriefRun wiring lands in Phase 4. Today this
    looks up a BriefRun row by `session_id` (matched against
    BriefRun.context_session_id once that column exists, or via
    fallback to the ai_session row); if not present we surface a
    ``brief_run_not_found`` error so the agent stops cleanly.

    Args:
      session_id: parent ai_session UUID.
      sections: dict of brief sections (e.g. movers, anomalies).
      citations: list of citation dicts to attach to the brief.

    # TODO(Phase 4): full BriefRun wiring — INSERT/UPSERT brief_run row
    # with markdown rendered from sections + citations, idempotency
    # check against (period_start, period_end), bullet_count derivation.
    """
    return await _invoke_session(
        "persist_brief",
        session_id,
        {"sections": sections, "citations": citations},
    )


# ---------------------------------------------------------------------------
# Bearer auth (Starlette AuthenticationBackend)
# ---------------------------------------------------------------------------


# Sentinel suffix that travels inside ``AuthenticationError`` so the
# on_error handler can map it to a 503 instead of the default 401 that
# Starlette uses for auth failures. Keeps the parity table in ARCH §4.3
# honest without re-implementing the middleware.
_BEARER_NOT_CONFIGURED_SENTINEL = "_503"


class StaticBearer(AuthenticationBackend):
    """Compares ``Authorization: Bearer <token>`` against
    ``AGENT_TOOLS_BEARER`` in constant time.

    Behaviour matches ``routers.agent_tools._require_bearer``:
      * env unset/empty -> raise with the 503 sentinel
      * header missing  -> raise "missing_bearer" (-> 401)
      * wrong token     -> raise "invalid_bearer" (-> 401)
      * correct token   -> return AuthCredentials + SimpleUser
    """

    async def authenticate(self, conn):
        expected = os.environ.get("AGENT_TOOLS_BEARER", "") or ""
        if not expected:
            # Fail closed; same behaviour as the legacy HTTP router.
            raise AuthenticationError(
                f"agent_tools_bearer_not_configured{_BEARER_NOT_CONFIGURED_SENTINEL}"
            )

        header = conn.headers.get("Authorization", "")
        if not header:
            raise AuthenticationError("missing_bearer")
        if not header.startswith("Bearer "):
            raise AuthenticationError("missing_bearer")
        token = header[7:]
        if not hmac.compare_digest(
            token.encode("utf-8"), expected.encode("utf-8")
        ):
            raise AuthenticationError("invalid_bearer")
        return AuthCredentials(["authenticated"]), SimpleUser("openclaw")


def _on_auth_error(conn, exc: AuthenticationError) -> JSONResponse:
    """Map AuthenticationError sentinels onto HTTP statuses.

    The default Starlette handler always returns 400; we want 401 for
    a wrong/missing bearer and 503 when the secret is unconfigured.
    """
    detail = str(exc)
    if detail.endswith(_BEARER_NOT_CONFIGURED_SENTINEL):
        return JSONResponse(
            {"detail": detail.removesuffix(_BEARER_NOT_CONFIGURED_SENTINEL)},
            status_code=503,
        )
    return JSONResponse({"detail": detail}, status_code=401)


# ---------------------------------------------------------------------------
# Mount helper
# ---------------------------------------------------------------------------


def _attach_lifespan(app, lifespan_ctx) -> None:
    """Compose ``lifespan_ctx`` with whatever lifespan the parent FastAPI
    app already has so neither is dropped.

    FastAPI does not auto-inherit lifespans from mounted apps (issue
    mcp-python-sdk #1367); without this composition the streamable-HTTP
    transport raises ``Task group is not initialized`` on the first
    request. We wrap both contexts so they enter on startup and exit
    on shutdown in nested order.
    """
    existing = app.router.lifespan_context

    @asynccontextmanager
    async def combined(app_ref):
        async with lifespan_ctx(app_ref):
            async with existing(app_ref):
                yield

    app.router.lifespan_context = combined


def mount_mcp(app) -> None:
    """Wire the FastMCP streamable-HTTP sub-app under ``/mcp`` on the
    given FastAPI app, with bearer auth applied to that mount only.

    Steps:
      1. Build the inner Starlette via ``mcp.streamable_http_app()``.
         Its only route is ``/mcp`` -> ``StreamableHTTPASGIApp``; we
         pull the ASGI handler out so we can re-mount it cleanly.
      2. Build a fresh sub-Starlette routed at ``/`` -> the streamable
         ASGI handler. This sidesteps the ``/mcp/mcp`` doubling that
         issue #1367 documents (the inner Starlette's ``/mcp`` route is
         never reached because we mount the underlying handler at root).
      3. Add ``AuthenticationMiddleware(StaticBearer)`` to sub.
      4. Compose the inner Starlette's lifespan with the parent FastAPI
         app's lifespan so the streamable-HTTP session manager spins up.
      5. ``app.mount("/mcp", sub)`` — external URL is now ``/mcp``.
    """
    inner = mcp.streamable_http_app()
    # The inner Starlette has one Route("/mcp", StreamableHTTPASGIApp).
    # Extract the ASGI handler so we can mount it at root inside our
    # auth-wrapped sub-Starlette without inheriting the inner /mcp prefix.
    streamable_asgi = None
    for route in inner.routes:
        candidate = getattr(route, "app", None)
        if candidate is not None:
            streamable_asgi = candidate
            break
    if streamable_asgi is None:
        # Shouldn't happen with mcp 1.27.x, but fail loud if the SDK
        # changes its route layout in a future minor version.
        raise RuntimeError(
            "mcp.streamable_http_app() returned no ASGI handler — "
            "FastMCP layout may have changed; revisit mount_mcp."
        )

    sub = Starlette(
        routes=[Mount("/", app=streamable_asgi)],
        middleware=[
            Middleware(
                AuthenticationMiddleware,
                backend=StaticBearer(),
                on_error=_on_auth_error,
            ),
        ],
        lifespan=inner.router.lifespan_context,
    )

    _attach_lifespan(app, inner.router.lifespan_context)
    app.mount("/mcp", sub)
