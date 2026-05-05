"""call_api — invoke an internal router endpoint via in-process ASGI transport.

Per ARCH A6.2 the agent is restricted to read-only paths under `/api/`.
We use httpx.AsyncClient with httpx.ASGITransport to talk to the FastAPI
app without going through a real HTTP socket.

V1 allow-list:
    - any GET on /api/...
    - no POST/PUT/DELETE
    - explicit deny on `/api/agent` POSTs (write surface)
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..specs.skill_context import SkillContext

logger = logging.getLogger(__name__)


_DENY_POST_PATHS = (
    "/api/agent",
    "/api/insights/sessions",  # creating a new session via the agent itself = recursion
)


def _resolve_app() -> Any:
    """Lazy-import the FastAPI app so this module is testable in isolation."""
    # The app's package layout puts `main.py` at backend/main.py. When the
    # CWD is the backend/ folder uvicorn is started from, `import main` works.
    try:
        from main import app  # type: ignore
        return app
    except Exception:
        # Fall back to the absolute path used in tests where backend isn't on
        # PYTHONPATH.
        from backend.main import app  # type: ignore
        return app


async def call_api(
    endpoint: str,
    params: dict[str, Any] | None = None,
    ctx: SkillContext | None = None,
    *,
    method: str = "GET",
) -> dict[str, Any]:
    """Invoke `endpoint` against the FastAPI app in-process.

    Returns a dict::

        {"status": int, "body": <json or text>, "endpoint": str}
    """
    if not endpoint.startswith("/api/"):
        return {
            "status": 400,
            "body": {"error": "endpoint_not_allowed", "endpoint": endpoint},
            "endpoint": endpoint,
        }

    method_upper = method.upper()
    if method_upper != "GET":
        # V1 deny-by-default for writes.
        return {
            "status": 405,
            "body": {"error": "write_methods_disabled_in_v1", "method": method_upper},
            "endpoint": endpoint,
        }

    if any(endpoint.startswith(p) for p in _DENY_POST_PATHS):
        return {
            "status": 403,
            "body": {"error": "endpoint_denied", "endpoint": endpoint},
            "endpoint": endpoint,
        }

    app = _resolve_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://app.local") as client:
        resp = await client.request(method_upper, endpoint, params=params or {})
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
        return {
            "status": resp.status_code,
            "body": body,
            "endpoint": endpoint,
        }
