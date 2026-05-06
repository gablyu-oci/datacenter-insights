"""OpenClaw chat forwarder.

Spec:
  - docs/plans/ai-insights-automation/11b-openclaw-migration-architecture.md §5
  - docs/plans/ai-insights-automation/11c-openclaw-migration-addendum.md §B/§C/§J

`forward_chat(...)` is the async generator that powers the OpenClaw
lane of POST /api/insights/insights/{id}/chat. It:

  1. Persists the user message to `agent_message` BEFORE dialling
     OpenClaw, so the audit trail is intact even if the gateway is
     unreachable (PRD R7 / ARCH §6.1).
  2. POSTs the user message to OpenClaw's OpenAI-compatible chat
     endpoint with `stream: true`, the gateway Bearer token, and
     `x-openclaw-session-key: agent:main:insight:<id>`.
  3. Reads the SSE stream chunk-by-chunk, runs each through the
     `sse_translator.translate_chunk` pure function, and yields the
     produced events as raw SSE bytes (via `to_sse_text`).
  4. On `message_complete`, persists an assistant `agent_message`
     row with the buffered text and a JSONB record of any tool
     calls. On error/timeout, persists a best-effort assistant row
     with `content=None` and the partial tool_calls.

The chat dispatcher in `routers/insights.py` wraps this generator in
a `StreamingResponse(media_type="text/event-stream")` so the wire
contract is identical to the legacy ToolLoopDriver lane (PRD R5).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.insights.db.models import AgentMessage
from agents.insights.specs.sse_events import (
    ErrorData,
    ErrorEvent,
    to_sse_text,
)
from config import settings

from .sse_translator import (
    ChunkAccumulator,
    parse_sse_data_field,
    translate_chunk,
)

logger = logging.getLogger(__name__)


# Per ARCH §5.2 the read budget is 60s; httpx connect/read timeout aligns.
_OPENCLAW_TIMEOUT = httpx.Timeout(60.0, read=60.0, connect=10.0)


async def forward_chat(
    *,
    insight_id: uuid.UUID,
    user_text: str,
    db: AsyncSession,
    thread_id: uuid.UUID,
    session_id: uuid.UUID,
) -> AsyncIterator[bytes]:
    """Forward one user turn through the OpenClaw gateway as SSE bytes.

    Caller MUST be inside a DB-session-context that owns `db`. This
    function commits multiple times: once for the user-message write
    (step 1) and once on completion (step 4). On exception the caller
    is responsible for rolling back any uncommitted work.

    Args:
      insight_id: the insight scope of the chat session.
      user_text: the inbound user message body.
      db: an open AsyncSession, NOT closed by this function.
      thread_id: the `insight_thread.id` to attach messages to.
      session_id: the parent `ai_session.id` (FK on agent_message).

    Yields:
      bytes ready to write into the SSE response. Each chunk is one
      SSE event in the project's existing on-the-wire taxonomy.
    """
    assistant_message_id = f"msg_{uuid.uuid4().hex[:12]}"

    # ----- Step 1: persist the user message (write-through). ----------
    user_seq = await _next_seq(db, thread_id=thread_id)
    db.add(
        AgentMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            insight_id=insight_id,
            thread_id=thread_id,
            seq=user_seq,
            role="user",
            content=user_text,
        )
    )
    await db.commit()

    # ----- Step 2-4: dial OpenClaw, translate, persist. ---------------
    acc = ChunkAccumulator(
        thread_id=str(thread_id),
        message_id=assistant_message_id,
        insight_id=str(insight_id),
    )
    assistant_buffer: list[str] = []

    session_key = f"{settings.openclaw_session_prefix}{insight_id}"
    headers = {
        "Content-Type": "application/json",
        "x-openclaw-session-key": session_key,
    }
    if settings.openclaw_gateway_token:
        headers["Authorization"] = f"Bearer {settings.openclaw_gateway_token}"
    body = {
        "model": "openclaw/default",
        "messages": [{"role": "user", "content": user_text}],
        "stream": True,
    }
    url = f"{settings.openclaw_gateway_url.rstrip('/')}/v1/chat/completions"

    finished_normally = False

    # NOTE (Phase 2): the shared `_drive_openclaw_stream` helper sits
    # below this function. We keep `forward_chat` inline for now to
    # preserve byte-identical streaming semantics — the chat lane yields
    # SSE bytes as each chunk arrives, which is hard to layer through
    # an async-callback collector without changing observable timing.
    # The synthesis lane (which has no streaming-to-browser contract)
    # uses `_drive_openclaw_stream` directly. PRD AC-4 / FR-X.6.

    try:
        async with httpx.AsyncClient(timeout=_OPENCLAW_TIMEOUT) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code >= 400:
                    err_text: str
                    try:
                        err_text = (await response.aread()).decode("utf-8", "replace")[:500]
                    except Exception:  # noqa: BLE001
                        err_text = f"http_{response.status_code}"
                    yield _yield_error(
                        insight_id=str(insight_id),
                        code="openclaw_unavailable",
                        message=f"openclaw http {response.status_code}: {err_text}",
                        retryable=response.status_code in (502, 503, 504),
                    )
                else:
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        # SSE lines we care about start with "data:".
                        if not line.startswith("data:"):
                            continue
                        parsed = parse_sse_data_field(line[len("data:") :])
                        if parsed is None:
                            continue

                        events = translate_chunk(parsed, acc)
                        for evt in events:
                            # Capture assistant-text deltas for the DB row.
                            data = getattr(evt, "data", None)
                            if (
                                evt.__class__.__name__ == "AssistantMessageTokenEvent"
                                and data is not None
                            ):
                                delta = getattr(data, "delta", "") or ""
                                if delta:
                                    assistant_buffer.append(delta)

                            yield to_sse_text(evt).encode("utf-8")

                        if acc.finished:
                            finished_normally = True
                            break

    except httpx.TimeoutException as exc:
        logger.warning("openclaw.forwarder.timeout: %s", exc)
        yield _yield_error(
            insight_id=str(insight_id),
            code="openclaw_timeout",
            message=str(exc),
            retryable=True,
        )
    except httpx.HTTPError as exc:
        logger.warning("openclaw.forwarder.http_error: %s", exc)
        yield _yield_error(
            insight_id=str(insight_id),
            code="openclaw_unavailable",
            message=str(exc),
            retryable=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("openclaw.forwarder.unhandled")
        yield _yield_error(
            insight_id=str(insight_id),
            code="openclaw_error",
            message=str(exc),
            retryable=False,
        )

    # ----- Step 4: persist the assistant message. ---------------------
    final_text = "".join(assistant_buffer) if assistant_buffer else None
    tool_calls_payload: Optional[list[dict[str, Any]]] = (
        list(acc.tool_calls_log) if acc.tool_calls_log else None
    )

    try:
        asst_seq = await _next_seq(db, thread_id=thread_id)
        db.add(
            AgentMessage(
                id=uuid.uuid4(),
                session_id=session_id,
                insight_id=insight_id,
                thread_id=thread_id,
                seq=asst_seq,
                role="assistant",
                content=final_text,
                tool_calls=tool_calls_payload,
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("openclaw.forwarder.persist_failed")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # If the upstream cut us off without a finish frame, surface a
    # synthetic message_complete so the client always sees a terminator.
    if not finished_normally and not acc.finished:
        # Emit a synthetic terminator with finish_reason=error so the dock
        # can render the partial turn as failed.
        from agents.insights.specs.sse_events import (
            MessageCompleteData,
            MessageCompleteEvent,
        )

        evt = MessageCompleteEvent(
            event_id=f"mco_{uuid.uuid4().hex[:12]}",
            seq=0,
            data=MessageCompleteData(
                thread_id=str(thread_id),
                message_id=assistant_message_id,
                finish_reason="error",
            ),
        )
        yield to_sse_text(evt).encode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _next_seq(db: AsyncSession, *, thread_id: uuid.UUID) -> int:
    """Return the next monotonic seq for a thread (1-based)."""
    last = (
        await db.execute(
            select(AgentMessage.seq)
            .where(AgentMessage.thread_id == thread_id)
            .order_by(AgentMessage.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return int(last or 0) + 1


def _yield_error(
    *,
    insight_id: str,
    code: str,
    message: str,
    retryable: bool,
) -> bytes:
    """Build one ErrorEvent and serialise it to wire bytes."""
    evt = ErrorEvent(
        event_id=f"err_{uuid.uuid4().hex[:12]}",
        seq=0,
        data=ErrorData(
            insight_id=insight_id,
            code=code,
            message=message,
            retryable=retryable,
        ),
    )
    return to_sse_text(evt).encode("utf-8")


# ---------------------------------------------------------------------------
# Phase 2 (PRD/ARCH 14) — shared OpenClaw stream driver
# ---------------------------------------------------------------------------


@dataclass
class StreamResult:
    """Outcome of a `_drive_openclaw_stream` invocation.

    Attributes:
      degraded: True when the stream was cut short by a cap or upstream
        error rather than reaching a clean terminator.
      reason: short slug ("turn_cap" | "tool_cap" | "wall_clock" |
        "http_error" | "timeout" | "exception" | "completed") used by
        the caller to set ai_session.failure_reason.
      total_chunks: number of SSE data: frames parsed.
      total_tool_calls: number of tool_call_complete events observed.
    """

    degraded: bool = False
    reason: Optional[str] = None
    total_chunks: int = 0
    total_tool_calls: int = 0


async def _drive_openclaw_stream(
    *,
    session_key: str,
    messages: list[dict[str, Any]],
    on_translated_event: Callable[[Any], Awaitable[None]],
    accumulator: Any,
    translator: Callable[[Any, Any], list[Any]],
    cap_turns: int = 12,
    cap_tool_calls: int = 30,
    cap_wall_seconds: float = 600.0,
) -> StreamResult:
    """POST to OpenClaw `/v1/chat/completions` and drain SSE.

    Shared between the chat lane (`forward_chat`) and the synthesis lane
    (`agents.insights.agentic_synthesis.run_agentic_synthesis`). The
    `accumulator` and `translator` arguments are intentionally untyped
    here so the same body can carry either of:

      - chat:      `ChunkAccumulator` + `translate_chunk`
      - synthesis: `SynthesisChunkAccumulator` + `translate_synthesis_chunk`

    Caps are enforced by inspecting `accumulator.cap_counters` (synthesis)
    or by counting locally (chat). On cap-trip we set `degraded=True` and
    break out of the SSE drain — we NEVER call `task.cancel()` (httpx
    issues #1461 / #2437).

    Args:
      session_key: value for the `x-openclaw-session-key` header. The
        OpenClaw memory store is keyed on this string.
      messages: OpenAI-shape `[{role, content}]` list.
      on_translated_event: per-event async sink. The caller chooses
        whether to push bytes onto an SSE response, persist to DB, or
        both.
      accumulator: mutable per-stream state.
      translator: pure function (chunk, acc) -> list[event].
      cap_turns: hard upper bound on assistant turns. Synthesis caps
        come from `acc.cap_counters["turns"]`; chat does not enforce
        this cap (left at the default to satisfy the API).
      cap_tool_calls: hard upper bound on tool-call completions.
      cap_wall_seconds: hard upper bound on wall-clock seconds.
    """
    result = StreamResult()

    headers = {
        "Content-Type": "application/json",
        "x-openclaw-session-key": session_key,
    }
    if settings.openclaw_gateway_token:
        headers["Authorization"] = f"Bearer {settings.openclaw_gateway_token}"

    body = {
        "model": "openclaw/default",
        "messages": messages,
        "stream": True,
    }
    url = f"{settings.openclaw_gateway_url.rstrip('/')}/v1/chat/completions"

    started = time.monotonic()
    # Synthesis accumulator carries cap_counters; chat accumulator does
    # not. We probe with getattr so the same helper handles both shapes.
    cap_counters = getattr(accumulator, "cap_counters", None)
    if isinstance(cap_counters, dict):
        cap_counters["wall_clock_started_at"] = started

    try:
        async with httpx.AsyncClient(timeout=_OPENCLAW_TIMEOUT) as client:
            async with client.stream(
                "POST", url, headers=headers, json=body
            ) as response:
                if response.status_code >= 400:
                    err_text: str
                    try:
                        err_text = (await response.aread()).decode(
                            "utf-8", "replace"
                        )[:500]
                    except Exception:  # noqa: BLE001
                        err_text = f"http_{response.status_code}"
                    logger.warning(
                        "openclaw.driver.http_error: %s %s",
                        response.status_code,
                        err_text,
                    )
                    result.degraded = True
                    result.reason = "http_error"
                    return result

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    parsed = parse_sse_data_field(line[len("data:") :])
                    if parsed is None:
                        continue

                    result.total_chunks += 1
                    events = translator(parsed, accumulator)
                    for evt in events:
                        await on_translated_event(evt)

                    # ---- Cap enforcement (cooperative break-out) ----
                    if isinstance(cap_counters, dict):
                        if int(cap_counters.get("tool_calls", 0)) > cap_tool_calls:
                            result.degraded = True
                            result.reason = "tool_cap"
                            break
                        if int(cap_counters.get("turns", 0)) > cap_turns:
                            result.degraded = True
                            result.reason = "turn_cap"
                            break
                    if (time.monotonic() - started) > cap_wall_seconds:
                        result.degraded = True
                        result.reason = "wall_clock"
                        break

                    if getattr(accumulator, "finished", False):
                        break

    except httpx.TimeoutException as exc:
        logger.warning("openclaw.driver.timeout: %s", exc)
        result.degraded = True
        result.reason = "timeout"
        return result
    except httpx.HTTPError as exc:
        logger.warning("openclaw.driver.http_error: %s", exc)
        result.degraded = True
        result.reason = "http_error"
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("openclaw.driver.unhandled")
        result.degraded = True
        result.reason = f"exception:{type(exc).__name__}"
        return result

    if isinstance(cap_counters, dict):
        result.total_tool_calls = int(cap_counters.get("tool_calls", 0))
    if not result.degraded and result.reason is None:
        result.reason = "completed"
    return result
