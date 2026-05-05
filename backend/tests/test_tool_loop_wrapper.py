"""tool_loop() — module-level async wrapper around ToolLoopDriver.

Verifies:
  * `tool_loop` is importable from agents.insights.tool_loop.
  * It's an async callable.
  * Smoke: with a dummy llm_call that returns no tool calls on turn 1,
    the loop terminates immediately with terminated_reason=='completed'.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from agents.insights.tool_loop import LoopResult, tool_loop


def test_tool_loop_is_async_callable():
    assert callable(tool_loop)
    assert inspect.iscoroutinefunction(tool_loop), (
        "tool_loop must be an async function (returns a coroutine)"
    )


@pytest.mark.asyncio
async def test_tool_loop_smoke_completes_immediately():
    """An LLM that returns no tool calls on the first turn should
    short-circuit the loop with terminated_reason='completed'.
    """
    dispatched: list[str] = []

    async def llm_call(messages, tools):
        return {"content": "done", "tool_calls": []}

    async def dispatch(name, args, ctx):
        dispatched.append(name)
        return {"ok": True}

    result = await tool_loop(
        llm_call=llm_call,
        dispatch=dispatch,
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    )
    assert isinstance(result, LoopResult)
    assert result.terminated_reason == "completed"
    assert result.turns == 1
    assert result.final_content == "done"
    assert dispatched == []  # no tool calls were made
