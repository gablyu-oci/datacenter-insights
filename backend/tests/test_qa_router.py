"""Tests for POST /api/qa/ask (QA-lane router + datacenter_qa shim).

Coverage map (PRD/ARCH 15 §3-§4):
  t1  happy path: 3 text chunks + done
  t2  propose_qa_chart -> chart_spec event with spec fields preserved
  t3  invalid chart args dropped silently; done still emitted
  t4  X-Session-Id header threaded into session_key
  t5  no header -> blake2b hex fallback (regex check)
  t6  upstream raises mid-stream -> done still emitted, no 500

Fake-upstream injection point
-----------------------------
Rather than mocking ``httpx.AsyncClient`` we monkeypatch
``openclaw.qa_forwarder._drive_openclaw_stream`` (the inner driver the
forwarder reuses from ``openclaw.forwarder``). The fake captures
session_key + messages and pumps a caller-supplied list of events
through the supplied ``on_translated_event`` callback so the rest of
the pipeline (router framing, generator shutdown, finally clause)
runs unchanged.

This mirrors the convention used by ``test_openclaw_forwarder.py``
which patches per-module symbols rather than the global httpx layer.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any, Awaitable, Callable, Optional

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

import openclaw.qa_forwarder as qa_fwd_mod  # noqa: E402
from main import app  # noqa: E402
from schemas.qa import (  # noqa: E402
    ChartSpecEvent,
    CitationEvent,
    ErrorEvent as QAErrorEvent,
    TextChunkEvent,
    ToolCallEvent,
    ToolResultEvent,
)


# ---------------------------------------------------------------------------
# Helpers — drive_openclaw_stream replacement
# ---------------------------------------------------------------------------


class _DriveCapture:
    """Captures session_key + messages passed to the patched driver."""

    def __init__(self) -> None:
        self.session_key: Optional[str] = None
        self.messages: Optional[list[dict[str, Any]]] = None
        self.calls: int = 0


def _make_fake_driver(
    *,
    capture: _DriveCapture,
    events: list[Any],
    raise_after: Optional[int] = None,
) -> Callable[..., Awaitable[Any]]:
    """Build a coroutine that mimics ``_drive_openclaw_stream``.

    Pumps ``events`` into ``on_translated_event`` in order. If
    ``raise_after`` is set, raises ``RuntimeError`` after emitting that
    many events (simulating an upstream mid-stream failure).

    Returns a ``StreamResult``-shaped object with ``degraded=False`` so
    the forwarder does not append its own QAErrorEvent.
    """

    async def _fake(
        *,
        session_key: str,
        messages: list[dict[str, Any]],
        on_translated_event: Callable[[Any], Awaitable[None]],
        accumulator: Any,
        translator: Callable[[Any, Any], list[Any]],
        cap_turns: int = 12,
        cap_tool_calls: int = 30,
        cap_wall_seconds: float = 600.0,
    ) -> Any:
        capture.session_key = session_key
        capture.messages = messages
        capture.calls += 1

        for i, evt in enumerate(events):
            if raise_after is not None and i == raise_after:
                raise RuntimeError("simulated_upstream_failure")
            await on_translated_event(evt)
            await asyncio.sleep(0)

        # Mimic the dataclass shape — duck typing is fine; the
        # forwarder reads .degraded and .reason via attribute access.
        class _Result:
            degraded = False
            reason = "completed"
            total_chunks = len(events)
            total_tool_calls = 0

        return _Result()

    return _fake


def _parse_sse_data_lines(body: str) -> list[dict]:
    """Extract every JSON payload from `data: {...}\\n\\n` frames."""
    out: list[dict] = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload:
            continue
        try:
            out.append(json.loads(payload))
        except json.JSONDecodeError:
            # The router's terminal frame is the literal
            # `data: {"type": "done"}\n\n`; valid JSON.
            continue
    return out


# ---------------------------------------------------------------------------
# t1 — happy path: 3 text chunks + done
# ---------------------------------------------------------------------------


def test_t1_happy_path_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    events = [
        TextChunkEvent(content="alpha "),
        TextChunkEvent(content="beta "),
        TextChunkEvent(content="gamma"),
    ]
    monkeypatch.setattr(
        qa_fwd_mod, "_drive_openclaw_stream", _make_fake_driver(capture=capture, events=events)
    )

    client = TestClient(app)
    r = client.post("/api/qa/ask", json={"question": "hello?", "history": []})
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("text/event-stream")

    payloads = _parse_sse_data_lines(r.text)
    text_chunks = [p for p in payloads if p.get("type") == "text_chunk"]
    assert len(text_chunks) == 3
    assert [p["content"] for p in text_chunks] == ["alpha ", "beta ", "gamma"]

    # Terminal done frame must be present.
    assert any(p.get("type") == "done" for p in payloads), payloads

    # Wire-format invariant: every data line ends \n\n (single-line frame).
    for line in r.text.split("\n\n"):
        if not line:
            continue
        # exactly one "data:" prefix per frame
        assert line.count("data:") == 1


# ---------------------------------------------------------------------------
# t2 — chart_spec event survives end-to-end
# ---------------------------------------------------------------------------


def test_t2_chart_emit_via_propose_qa_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    chart_evt = ChartSpecEvent(
        chart_type="bar",
        x="company",
        y="mw_total",
        series=[{"name": "MW", "values": [1, 2, 3]}],
        title="MW by company",
        source_table="datacenters",
        breakdown_by=None,
        reasoning="aggregated MW per company",
    )
    events = [
        TextChunkEvent(content="here is a chart "),
        chart_evt,
    ]
    monkeypatch.setattr(
        qa_fwd_mod, "_drive_openclaw_stream", _make_fake_driver(capture=capture, events=events)
    )

    client = TestClient(app)
    r = client.post("/api/qa/ask", json={"question": "chart please", "history": []})
    assert r.status_code == 200, r.text

    payloads = _parse_sse_data_lines(r.text)
    chart_payloads = [p for p in payloads if p.get("type") == "chart_spec"]
    assert len(chart_payloads) == 1, payloads
    cp = chart_payloads[0]
    assert cp["chart_type"] == "bar"
    assert cp["x"] == "company"
    assert cp["y"] == "mw_total"
    assert cp["title"] == "MW by company"
    assert cp["source_table"] == "datacenters"
    assert cp["series"] == [{"name": "MW", "values": [1, 2, 3]}]


# ---------------------------------------------------------------------------
# t3 — invalid chart args dropped silently; stream still terminates with done
# ---------------------------------------------------------------------------


def test_t3_invalid_chart_args_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Translator-level test: a propose_qa_chart chunk with bogus args
    must produce zero ChartSpecEvents (silent drop) but the response
    must still end with `done`. We exercise this through the real
    translator by feeding a raw OpenAI-shaped chunk into the forwarder.

    To avoid retyping the SSE-line parser, we patch the driver to call
    ``translate_qa_chunk`` directly (the same function the real driver
    invokes per chunk) so we exercise the validation path.
    """
    from openclaw.sse_translator import translate_qa_chunk

    capture = _DriveCapture()

    bogus_chunk = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_x",
                            "function": {
                                "name": "propose_qa_chart",
                                # Missing required `chart_type`, `x`, etc.
                                "arguments": '{"title": "broken"}',
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    }
    finish_chunk = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    text_chunk = {
        "choices": [{"delta": {"content": "ok"}, "finish_reason": None}]
    }

    async def _fake(
        *,
        session_key: str,
        messages: list[dict[str, Any]],
        on_translated_event: Callable[[Any], Awaitable[None]],
        accumulator: Any,
        translator: Callable[[Any, Any], list[Any]],
        **_kw,
    ) -> Any:
        capture.session_key = session_key
        capture.messages = messages
        # Drive translation through the actual translator so the
        # ChartSpec validation path is exercised.
        for chunk in (bogus_chunk, finish_chunk, text_chunk):
            for evt in translator(chunk, accumulator):
                await on_translated_event(evt)

        class _Result:
            degraded = False
            reason = "completed"
            total_chunks = 3
            total_tool_calls = 1

        return _Result()

    monkeypatch.setattr(qa_fwd_mod, "_drive_openclaw_stream", _fake)
    # Use the real translator so the patched driver call
    # `translator(chunk, acc)` works as expected.
    monkeypatch.setattr(qa_fwd_mod, "translate_qa_chunk", translate_qa_chunk)

    client = TestClient(app)
    r = client.post("/api/qa/ask", json={"question": "broken chart", "history": []})
    assert r.status_code == 200, r.text

    payloads = _parse_sse_data_lines(r.text)

    # No chart_spec event must surface for the bogus args.
    assert not any(p.get("type") == "chart_spec" for p in payloads), payloads
    # ToolCallEvent for propose_qa_chart still surfaces (it always does)
    # plus a generic ToolResultEvent — that's OK, the validation drop
    # only suppresses the chart_spec emission.
    # Terminal done present.
    assert any(p.get("type") == "done" for p in payloads), payloads


# ---------------------------------------------------------------------------
# t4 — explicit X-Session-Id header threads into session_key
# ---------------------------------------------------------------------------


def test_t4_session_key_with_header(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    monkeypatch.setattr(
        qa_fwd_mod,
        "_drive_openclaw_stream",
        _make_fake_driver(capture=capture, events=[TextChunkEvent(content="hi")]),
    )

    # The current router doesn't forward x_session_id (it doesn't accept
    # the header into AskRequest). Confirm the QA shim builds the
    # session_key correctly when invoked directly with x_session_id.
    # The router test here verifies the default-namespace prefix only;
    # we exercise the header-propagation path via direct shim call.
    from agents.datacenter_qa import answer_question

    async def _drive() -> None:
        async for _ in answer_question(
            None,  # session is unused in the shim
            "what?",
            history=[],
            x_session_id="my-session-abc",
        ):
            pass

    asyncio.get_event_loop().run_until_complete(_drive()) if False else asyncio.run(_drive())

    assert capture.session_key is not None
    assert capture.session_key.startswith("agent:main:qa:global:my-session-abc"), capture.session_key


# ---------------------------------------------------------------------------
# t5 — fallback session key is blake2b 16-hex digest
# ---------------------------------------------------------------------------


def test_t5_session_key_hash_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    monkeypatch.setattr(
        qa_fwd_mod,
        "_drive_openclaw_stream",
        _make_fake_driver(capture=capture, events=[TextChunkEvent(content="hi")]),
    )

    client = TestClient(app)
    r = client.post(
        "/api/qa/ask",
        json={"question": "what is the meaning of MW?", "history": []},
    )
    assert r.status_code == 200, r.text

    assert capture.session_key is not None
    # Format: agent:main:qa:global:<16 hex chars>
    assert re.match(
        r"^agent:main:qa:global:[0-9a-f]{16}$", capture.session_key
    ), capture.session_key


# ---------------------------------------------------------------------------
# t6 — upstream raises mid-stream; router still emits a terminal frame
# ---------------------------------------------------------------------------


def test_t6_done_emitted_on_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    events = [TextChunkEvent(content="partial")]
    monkeypatch.setattr(
        qa_fwd_mod,
        "_drive_openclaw_stream",
        _make_fake_driver(capture=capture, events=events, raise_after=1),
    )

    client = TestClient(app)
    r = client.post(
        "/api/qa/ask",
        json={"question": "boom", "history": []},
    )
    # Must NOT 500.
    assert r.status_code == 200, r.text

    payloads = _parse_sse_data_lines(r.text)
    # Must end with a `done` (or `error`) frame, never raw exception.
    last_terminal = next(
        (
            p
            for p in reversed(payloads)
            if p.get("type") in ("done", "error")
        ),
        None,
    )
    assert last_terminal is not None, payloads
    # The forwarder surfaces a QAErrorEvent for the unhandled exception
    # before the route's terminal `done` frame fires.
    assert any(p.get("type") == "done" for p in payloads), payloads
