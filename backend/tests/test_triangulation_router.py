"""Tests for POST /api/agent/ask (Triangulation lane router + shim).

Coverage map (PRD/ARCH 15 §3-§4):
  t1  text-only stream returns plain `data: <delta>\\n\\n` lines
      terminated by `data: [DONE]\\n\\n` (legacy wire contract).
  t2  tool plumbing (ToolCallEvent / ToolResultEvent) is suppressed
      because the shim sets ``surface_tool_events=False``.
  t3  session_key starts with `agent:main:triangulation:` and is
      stable for the same question across two calls.
  t4  shim loads the `triangulation_rules` prompt.

Same fake-upstream injection style as test_qa_router.py.
"""
from __future__ import annotations

import asyncio
import os
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
    TextChunkEvent,
    ToolCallEvent,
    ToolResultEvent,
)


# ---------------------------------------------------------------------------
# Shared fake driver (similar to test_qa_router but multi-call aware)
# ---------------------------------------------------------------------------


class _DriveCapture:
    def __init__(self) -> None:
        self.session_keys: list[str] = []
        self.system_prompts: list[str] = []
        self.messages: list[list[dict[str, Any]]] = []


def _make_fake_driver(
    *,
    capture: _DriveCapture,
    events: list[Any],
) -> Callable[..., Awaitable[Any]]:
    async def _fake(
        *,
        session_key: str,
        messages: list[dict[str, Any]],
        on_translated_event: Callable[[Any], Awaitable[None]],
        accumulator: Any,
        translator: Callable[[Any, Any], list[Any]],
        **_kw,
    ) -> Any:
        capture.session_keys.append(session_key)
        capture.messages.append(list(messages))
        # System prompt is the first message in the OpenAI-shape list.
        if messages and messages[0].get("role") == "system":
            capture.system_prompts.append(messages[0].get("content", ""))
        for evt in events:
            await on_translated_event(evt)
            await asyncio.sleep(0)

        class _Result:
            degraded = False
            reason = "completed"
            total_chunks = len(events)
            total_tool_calls = 0

        return _Result()

    return _fake


# ---------------------------------------------------------------------------
# t1 — happy path: text-only deltas, legacy wire format preserved
# ---------------------------------------------------------------------------


def test_t1_text_only_str_iterator(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    events = [
        TextChunkEvent(content="hello "),
        TextChunkEvent(content="world"),
    ]
    monkeypatch.setattr(
        qa_fwd_mod,
        "_drive_openclaw_stream",
        _make_fake_driver(capture=capture, events=events),
    )

    client = TestClient(app)
    r = client.post("/api/agent/ask", json={"question": "ping?"})
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("text/event-stream")

    # Legacy wire format: `data: <delta>\n\n` lines, NOT JSON-framed.
    body = r.text
    # Each delta from the shim is yielded as `data: <text>\n\n`.
    assert "data: hello " in body, body
    assert "data: world" in body, body
    # Terminal sentinel is `data: [DONE]` (NOT a JSON `done` event).
    assert "data: [DONE]" in body, body
    # No `data: {"type":` JSON-event framing should appear from the
    # router itself (the QA-lane format must NOT leak into this lane).
    assert '"type": "text_chunk"' not in body, body
    assert '"type": "done"' not in body, body


# ---------------------------------------------------------------------------
# t2 — tool plumbing must NOT leak (surface_tool_events=False)
# ---------------------------------------------------------------------------


def test_t2_tool_events_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    events = [
        TextChunkEvent(content="answering "),
        ToolCallEvent(tool_name="query_database", args={"sql": "SELECT 1"}),
        ToolResultEvent(tool_name="query_database", summary="ok", row_count=1),
        TextChunkEvent(content="done."),
    ]
    monkeypatch.setattr(
        qa_fwd_mod,
        "_drive_openclaw_stream",
        _make_fake_driver(capture=capture, events=events),
    )

    client = TestClient(app)
    r = client.post("/api/agent/ask", json={"question": "do a thing"})
    assert r.status_code == 200, r.text

    body = r.text
    # Text deltas surface.
    assert "data: answering " in body, body
    assert "data: done." in body, body
    # Tool plumbing must be filtered out by the shim
    # (surface_tool_events=False); the iter_qa_events path drops
    # ToolCallEvent and ToolResultEvent by class name.
    assert "query_database" not in body, body
    assert "tool_call" not in body, body
    assert "tool_result" not in body, body


# ---------------------------------------------------------------------------
# t3 — session_key prefix + stability for the same question
# ---------------------------------------------------------------------------


def test_t3_session_key_topic_id(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    monkeypatch.setattr(
        qa_fwd_mod,
        "_drive_openclaw_stream",
        _make_fake_driver(
            capture=capture,
            events=[TextChunkEvent(content="x")],
        ),
    )

    client = TestClient(app)
    r1 = client.post("/api/agent/ask", json={"question": "what site has the most MW?"})
    r2 = client.post("/api/agent/ask", json={"question": "what site has the most MW?"})
    assert r1.status_code == 200
    assert r2.status_code == 200

    assert len(capture.session_keys) == 2
    for key in capture.session_keys:
        assert key.startswith("agent:main:triangulation:"), key
    # Stable across calls for the same question (blake2b is deterministic).
    assert capture.session_keys[0] == capture.session_keys[1]


# ---------------------------------------------------------------------------
# t4 — `triangulation_rules` prompt is loaded
# ---------------------------------------------------------------------------


def test_t4_prompt_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _DriveCapture()
    monkeypatch.setattr(
        qa_fwd_mod,
        "_drive_openclaw_stream",
        _make_fake_driver(
            capture=capture,
            events=[TextChunkEvent(content="ok")],
        ),
    )

    # Patch load_prompt so we can assert the shim asked for the right
    # name. Patch on the agents.triangulation_qa module since that's
    # where the import binding lives.
    seen_names: list[str] = []
    import agents.triangulation_qa as tri_mod

    real_load = tri_mod.load_prompt

    def _patched(name: str) -> str:
        seen_names.append(name)
        return real_load(name)

    monkeypatch.setattr(tri_mod, "load_prompt", _patched)

    client = TestClient(app)
    r = client.post("/api/agent/ask", json={"question": "Why?"})
    assert r.status_code == 200, r.text

    assert "triangulation_rules" in seen_names, seen_names
    # And the prompt body actually flows into the upstream messages list
    # as the system role.
    assert capture.system_prompts, capture.system_prompts
    assert capture.system_prompts[0]  # non-empty
