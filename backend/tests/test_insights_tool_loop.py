"""ToolLoopDriver cap tests (AI Insights V1).

NOTE: the kickoff brief mentioned a "40-call cap"; the actual code in
agents/insights/tool_loop.py uses two distinct caps:
    - max_turns                 = 12 (LLM passes)
    - max_parallel_tool_calls   = 4  (per turn; extras truncated)
Total tool calls are bounded by max_turns * max_parallel = 48 by default.

These tests assert the actual contract: the loop returns a `LoopResult`
with `terminated_reason == "turn_budget_exceeded"` once the turn cap
is hit, and "completed" otherwise.
"""
from __future__ import annotations

import json

import pytest

from agents.insights.tool_loop import ToolLoopDriver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_call(name: str = "noop", args: dict | None = None, call_id: str | None = None) -> dict:
    return {
        "id": call_id or "call_x",
        "function": {
            "name": name,
            "arguments": json.dumps(args or {}),
        },
    }


# ---------------------------------------------------------------------------
# Cap enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_cap_terminates_loop():
    """If the model never stops requesting tool calls, the loop must
    terminate at max_turns with a structured terminated_reason.
    """

    call_log: list[str] = []

    async def llm_call(messages, tools):
        # Always request another tool call -> forces the cap to bite.
        return {
            "content": None,
            "tool_calls": [_make_tool_call("noop")],
        }

    async def dispatch(name, args, ctx):
        call_log.append(name)
        return {"ok": True, "rows": []}

    driver = ToolLoopDriver(
        llm_call=llm_call,
        dispatch=dispatch,
        max_turns=5,
        max_parallel_tool_calls=2,
        wall_budget_seconds=30.0,
    )

    result = await driver.run(messages=[{"role": "user", "content": "go"}], tools=[])

    assert result.terminated_reason == "turn_budget_exceeded"
    assert result.turns == 5
    # 5 turns * 1 call/turn = 5 dispatches.
    assert len(call_log) == 5


@pytest.mark.asyncio
async def test_parallel_truncation_caps_per_turn():
    """If the model emits more parallel tool calls than max_parallel
    in a single turn, only max_parallel are dispatched.
    """

    dispatched: list[str] = []
    sent_calls = 0

    async def llm_call(messages, tools):
        nonlocal sent_calls
        sent_calls += 1
        if sent_calls == 1:
            # Ask for 6 calls in one turn -> driver must keep only max_parallel=3.
            return {
                "content": None,
                "tool_calls": [
                    _make_tool_call("t", {"i": i}, call_id=f"c{i}") for i in range(6)
                ],
            }
        # On the next turn, finalise (no tool_calls).
        return {"content": "done", "tool_calls": []}

    async def dispatch(name, args, ctx):
        dispatched.append(f"{name}:{args.get('i')}")
        return {"ok": True}

    driver = ToolLoopDriver(
        llm_call=llm_call,
        dispatch=dispatch,
        max_turns=12,
        max_parallel_tool_calls=3,
    )

    result = await driver.run(messages=[{"role": "user", "content": "go"}], tools=[])
    assert result.terminated_reason == "completed"
    assert len(dispatched) == 3, f"expected 3 dispatched (cap), got {len(dispatched)}"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_under_cap_completes():
    """One tool call, then a final answer — terminates with 'completed'."""

    seen = []
    sent_calls = 0

    async def llm_call(messages, tools):
        nonlocal sent_calls
        sent_calls += 1
        if sent_calls == 1:
            return {
                "content": None,
                "tool_calls": [_make_tool_call("query_database", {"q": 1})],
            }
        return {"content": "final answer", "tool_calls": []}

    async def dispatch(name, args, ctx):
        seen.append(name)
        return {"ok": True, "rows": [{"x": 1}]}

    driver = ToolLoopDriver(
        llm_call=llm_call,
        dispatch=dispatch,
        max_turns=12,
        max_parallel_tool_calls=4,
    )

    result = await driver.run(messages=[{"role": "user", "content": "ask"}], tools=[])
    assert result.terminated_reason == "completed"
    assert result.final_content == "final answer"
    assert seen == ["query_database"]
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].ok is True
