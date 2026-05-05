"""ToolLoopDriver — OpenAI-style tool-call loop on top of LlmClient.reason().

Caps (ARCH A10.2):
    * max_turns                = 20   (V2 default; V1 was 12)
    * max_parallel_tool_calls  = 4    (extra calls in same turn dropped)
    * wall_budget_seconds      = 120  (per insight, default)

V2 insight discovery: 20 turns x 4 parallel = 80 tool calls/session
(PRD §5.1, V2 line). The chat agent constructs ToolLoopDriver explicitly
with ``max_turns=12`` so chat stays at 12 x 4 = 48 (PRD §5.4).

Returns a `LoopResult` with the final messages, turn count, executed tool
calls, and a structured `terminated_reason`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .specs.skill_context import SkillContext

logger = logging.getLogger(__name__)


# V2 insight discovery: 20 x 4 = 80 (PRD §5.1, V2 line).
# Chat agent overrides this to 12 (12 x 4 = 48; PRD §5.4).
DEFAULT_MAX_TURNS = 20
DEFAULT_MAX_PARALLEL = 4
DEFAULT_WALL_BUDGET_S = 120.0


@dataclass
class ToolCallRecord:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    ok: bool
    result: Any
    latency_ms: int


@dataclass
class LoopResult:
    messages: list[dict[str, Any]]
    turns: int
    tool_calls: list[ToolCallRecord]
    terminated_reason: str
    final_content: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ToolLoopDriver:
    """Drives a tool-using conversation under hard caps.

    The `llm_call` callable encapsulates whatever LlmClient invocation
    style the caller prefers. Signature::

        async def llm_call(messages, tools) -> {
            "content": Optional[str],
            "tool_calls": list[{
                "id": str,
                "function": {"name": str, "arguments": str (JSON)}
            }],
            "model": str,
            "tokens": dict,
        }

    `dispatch` is the registry dispatcher::

        async def dispatch(name, args, ctx) -> Any
    """

    def __init__(
        self,
        *,
        llm_call: Callable[..., Awaitable[dict[str, Any]]],
        dispatch: Callable[..., Awaitable[Any]],
        max_turns: int = DEFAULT_MAX_TURNS,
        max_parallel_tool_calls: int = DEFAULT_MAX_PARALLEL,
        wall_budget_seconds: float = DEFAULT_WALL_BUDGET_S,
    ) -> None:
        self.llm_call = llm_call
        self.dispatch = dispatch
        self.max_turns = max_turns
        self.max_parallel = max_parallel_tool_calls
        self.wall_budget = wall_budget_seconds

    async def run(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        ctx: SkillContext | None = None,
    ) -> LoopResult:
        started = time.monotonic()
        msgs = list(messages)
        tool_calls: list[ToolCallRecord] = []
        turns = 0
        last_content: str | None = None

        while True:
            # Wall-budget check.
            elapsed = time.monotonic() - started
            if elapsed > self.wall_budget:
                return LoopResult(
                    messages=msgs,
                    turns=turns,
                    tool_calls=tool_calls,
                    terminated_reason="wall_budget_exceeded",
                    final_content=last_content,
                )

            if turns >= self.max_turns:
                return LoopResult(
                    messages=msgs,
                    turns=turns,
                    tool_calls=tool_calls,
                    terminated_reason="turn_budget_exceeded",
                    final_content=last_content,
                )

            try:
                turn = await self.llm_call(messages=msgs, tools=tools)
            except Exception as exc:
                logger.exception("ai_insights.tool_loop.llm_error")
                return LoopResult(
                    messages=msgs,
                    turns=turns,
                    tool_calls=tool_calls,
                    terminated_reason=f"llm_error:{exc}",
                    final_content=last_content,
                )

            turns += 1
            last_content = turn.get("content") or last_content
            assistant_tool_calls = turn.get("tool_calls") or []

            # Append assistant turn (with or without tool_calls).
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": turn.get("content"),
            }
            if assistant_tool_calls:
                assistant_msg["tool_calls"] = assistant_tool_calls
            msgs.append(assistant_msg)

            # Termination — no tool calls means model produced a final answer.
            if not assistant_tool_calls:
                return LoopResult(
                    messages=msgs,
                    turns=turns,
                    tool_calls=tool_calls,
                    terminated_reason="completed",
                    final_content=last_content,
                )

            # Truncate excess parallel calls per ARCH A10.2.
            if len(assistant_tool_calls) > self.max_parallel:
                logger.warning(
                    "ai_insights.tool_loop.parallel_truncation",
                    extra={
                        "received": len(assistant_tool_calls),
                        "kept": self.max_parallel,
                    },
                )
                assistant_tool_calls = assistant_tool_calls[: self.max_parallel]

            # Dispatch tool calls in parallel.
            async def _exec_one(tc: dict[str, Any]) -> ToolCallRecord:
                tool_call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                fn = tc.get("function") or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = (
                        raw_args
                        if isinstance(raw_args, dict)
                        else json.loads(raw_args)
                    )
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}

                t0 = time.monotonic()
                try:
                    result = await self.dispatch(name, args, ctx)
                    ok = not (isinstance(result, dict) and result.get("ok") is False)
                except Exception as exc:
                    result = {"ok": False, "error": "dispatch_exception", "detail": str(exc)}
                    ok = False
                latency_ms = int((time.monotonic() - t0) * 1000)
                return ToolCallRecord(
                    tool_call_id=tool_call_id,
                    tool_name=name,
                    args=args,
                    ok=ok,
                    result=result,
                    latency_ms=latency_ms,
                )

            records = await asyncio.gather(
                *[_exec_one(tc) for tc in assistant_tool_calls]
            )
            tool_calls.extend(records)

            # Append tool results back to the conversation.
            for rec in records:
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": rec.tool_call_id,
                        "content": json.dumps(rec.result, default=str),
                    }
                )

            # Loop back for the next assistant turn.


async def tool_loop(
    *,
    llm_call,
    dispatch,
    messages,
    tools,
    ctx=None,
    max_turns=DEFAULT_MAX_TURNS,
    max_parallel_tool_calls=DEFAULT_MAX_PARALLEL,
    wall_budget_seconds=DEFAULT_WALL_BUDGET_S,
) -> LoopResult:
    """Functional wrapper around ToolLoopDriver for callers preferring async-fn shape."""
    driver = ToolLoopDriver(
        llm_call=llm_call,
        dispatch=dispatch,
        max_turns=max_turns,
        max_parallel_tool_calls=max_parallel_tool_calls,
        wall_budget_seconds=wall_budget_seconds,
    )
    return await driver.run(messages, tools, ctx=ctx)
