"""OpenClaw QA-lane forwarder.

Spec: docs/plans/ai-insights-automation/15-agent-unification-cleanup-architecture.md §3-§4
PRD:  docs/plans/ai-insights-automation/15-agent-unification-cleanup-prd.md AC-1..AC-3

This module is the QA-lane sibling of `forward_chat` (chat lane) and
`run_agentic_synthesis` (synthesis lane). It powers two callsites:

  - agents/datacenter_qa.py        (QA-global, namespace "qa:global")
  - agents/triangulation_qa.py     (Triangulation, namespace "triangulation")

Two-layer design (PRD AC-2):
  - `iter_qa_events(...)`  yields `QATranslatedEvent` objects.
                           Used directly by the agent shims.
  - `forward_qa(...)`      yields raw SSE bytes (`data: {json}\\n\\n`).
                           Thin wrapper around `iter_qa_events` for any
                           future caller that wants to bypass the agent
                           shim entirely.

Wire-format invariant (research §5): the QA lane uses single-line
`data: {json.dumps(event.model_dump())}\\n\\n` framing. We MUST NOT
call `to_sse_text(...)` on QA events — that is the chat-lane multi-
line format and would silently break the frontend `useQA` hook.

Stream draining: we reuse `_drive_openclaw_stream` from
`openclaw/forwarder.py` so the QA lane shares timeout / cap-enforcement
/ HTTP semantics with the synthesis lane. The shared driver invokes a
caller-supplied `on_translated_event` callback per event; we plumb that
through an `asyncio.Queue` so this generator can yield events as they
arrive (cooperative back-pressure).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import AsyncIterator, Optional

from schemas.qa import ErrorEvent as QAErrorEvent, Message

from .forwarder import _drive_openclaw_stream
from .sse_translator import (
    QAChunkAccumulator,
    QATranslatedEvent,
    translate_qa_chunk,
)

logger = logging.getLogger(__name__)


# Stream-end sentinel pushed onto the internal queue so the consumer
# loop knows the producer task has finished. Distinct object identity.
_QA_STREAM_END = object()


# Defaults aligned with synthesis lane (`_drive_openclaw_stream` defaults
# are 12 / 30 / 600). QA budgets are tighter — research §6.
_QA_CAP_TURNS = 12
_QA_CAP_TOOL_CALLS = 20
_QA_CAP_WALL_SECONDS = 120.0


def _qa_session_key(
    *,
    namespace: str,
    question: str,
    x_session_id: Optional[str] = None,
) -> str:
    """Build the OpenClaw `x-openclaw-session-key` for a QA turn.

    Scheme (arch §3.4): `agent:main:{namespace}:{stable_id}` where
    `stable_id` is either the caller-supplied `x-session-id` header
    or a deterministic blake2b digest of the question (so identical
    questions reuse the same OpenClaw memory partition while still
    being scoped to the namespace).

    Args:
      namespace: short slug — "qa:global" or "triangulation".
      question: the user question (used for the fallback hash).
      x_session_id: optional client-supplied session id.
    """
    if x_session_id:
        stable = x_session_id
    else:
        # 8-byte blake2b digest is enough — collisions across distinct
        # questions are tolerable (worst case: shared memory partition,
        # which OpenClaw already evicts under TTL).
        stable = hashlib.blake2b(
            question.encode("utf-8"), digest_size=8
        ).hexdigest()
    return f"agent:main:{namespace}:{stable}"


async def iter_qa_events(
    *,
    question: str,
    history: list[Message],
    system_prompt: str,
    namespace: str,
    x_session_id: Optional[str] = None,
    surface_tool_events: bool = True,
    cap_turns: int = _QA_CAP_TURNS,
    cap_tool_calls: int = _QA_CAP_TOOL_CALLS,
    cap_wall_seconds: float = _QA_CAP_WALL_SECONDS,
) -> AsyncIterator[QATranslatedEvent]:
    """Drive one QA turn through OpenClaw and yield translated events.

    This is the inner layer used directly by the agent shims
    (`agents/datacenter_qa.py`, `agents/triangulation_qa.py`).

    Args:
      question: the user question for this turn.
      history: prior turns as `Message` objects (already trimmed by the
        caller; OpenClaw also keeps memory under the session_key).
      system_prompt: the rendered persona prompt (loaded from
        `agents/insights/prompts/{qa_global_rules,triangulation_rules}.md`).
      namespace: OpenClaw memory namespace, e.g. `"qa:global"` or
        `"triangulation"`.
      x_session_id: optional client-supplied session id. When omitted
        we fall back to a blake2b hash of the question so identical
        questions share a memory partition.
      surface_tool_events: when False, drop `ToolCallEvent` and
        `ToolResultEvent` from the output. The triangulation lane
        sets this False because its caller serialises events to plain
        text and tool plumbing would leak into the response.
      cap_turns / cap_tool_calls / cap_wall_seconds: hard upper bounds
        passed through to `_drive_openclaw_stream`.

    Yields:
      `QATranslatedEvent` instances. The terminal `DoneEvent` is NOT
      emitted by this function — callers must emit it in their own
      `finally` clause (matches existing `routers/qa.py` pattern).
    """
    session_key = _qa_session_key(
        namespace=namespace,
        question=question,
        x_session_id=x_session_id,
    )
    acc = QAChunkAccumulator(session_key=session_key)

    # Build OpenAI-shape messages: system, ...history, user.
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": question})

    # Cross-task hand-off queue. The driver task pushes translated events
    # into the queue; this generator drains and yields them. We use a
    # bounded queue so a slow consumer applies cooperative back-pressure
    # to the upstream parser.
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    async def _on_event(evt: QATranslatedEvent) -> None:
        await queue.put(evt)

    async def _run_driver() -> None:
        """Run `_drive_openclaw_stream` and signal end-of-stream."""
        try:
            result = await _drive_openclaw_stream(
                session_key=session_key,
                messages=messages,
                on_translated_event=_on_event,
                accumulator=acc,
                translator=translate_qa_chunk,
                cap_turns=cap_turns,
                cap_tool_calls=cap_tool_calls,
                cap_wall_seconds=cap_wall_seconds,
            )
            # If the driver closed degraded (cap, http error, timeout,
            # exception) we surface a terminal QAErrorEvent so the
            # consumer can render the failure. The driver itself has
            # no QA-shape errors to emit.
            if result.degraded and result.reason not in (None, "completed"):
                await queue.put(
                    QAErrorEvent(
                        message=f"qa_stream_degraded: {result.reason}",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("qa_forwarder.driver_unhandled")
            await queue.put(
                QAErrorEvent(
                    message=f"qa_forwarder_unhandled: {type(exc).__name__}",
                )
            )
        finally:
            await queue.put(_QA_STREAM_END)

    driver_task = asyncio.create_task(_run_driver())

    try:
        while True:
            item = await queue.get()
            if item is _QA_STREAM_END:
                break
            # Filter tool plumbing for the triangulation lane.
            if not surface_tool_events:
                # Use class name instead of isinstance to avoid an
                # extra import pair — the QA event surface is small.
                cls_name = item.__class__.__name__
                if cls_name in ("ToolCallEvent", "ToolResultEvent"):
                    continue
            yield item
    finally:
        # Make sure the producer task is awaited even on early exit so
        # we don't leak. We never call `task.cancel()` (httpx #1461 /
        # #2437); the driver respects `acc.finished` for cooperative
        # close, and any cap-trip will cause it to return promptly.
        if not driver_task.done():
            try:
                await driver_task
            except Exception:  # noqa: BLE001
                logger.exception("qa_forwarder.driver_await_failed")


async def forward_qa(
    *,
    question: str,
    history: list[Message],
    system_prompt: str,
    namespace: str,
    x_session_id: Optional[str] = None,
    surface_tool_events: bool = True,
    cap_turns: int = _QA_CAP_TURNS,
    cap_tool_calls: int = _QA_CAP_TOOL_CALLS,
    cap_wall_seconds: float = _QA_CAP_WALL_SECONDS,
) -> AsyncIterator[bytes]:
    """SSE-bytes wrapper around `iter_qa_events`.

    Yields `data: {json}\\n\\n` lines that the QA lane wire format
    expects. Does NOT emit a terminal DoneEvent — the caller (typically
    a FastAPI route) is responsible for that in its `finally` clause,
    matching the existing `routers/qa.py` pattern so behaviour is
    byte-identical to the legacy implementation.

    NEVER use `to_sse_text(...)` here — that emits the chat-lane multi-
    line framing and would break the QA frontend.
    """
    async for evt in iter_qa_events(
        question=question,
        history=history,
        system_prompt=system_prompt,
        namespace=namespace,
        x_session_id=x_session_id,
        surface_tool_events=surface_tool_events,
        cap_turns=cap_turns,
        cap_tool_calls=cap_tool_calls,
        cap_wall_seconds=cap_wall_seconds,
    ):
        payload = evt.model_dump()
        yield f"data: {json.dumps(payload, default=str)}\n\n".encode("utf-8")
