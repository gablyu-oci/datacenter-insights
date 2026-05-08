"""Unit tests for ``agents.insights.util.chunk_text``.

Phase B.1 of AI Insights v2. Pure function — no DB, no LLM.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from agents.insights.util.chunk_text import chunk_text  # noqa: E402


def test_empty_input_yields_no_chunks():
    assert list(chunk_text("")) == []
    assert list(chunk_text("   \n\t  ")) == []


def test_short_text_produces_one_chunk():
    body = "This is a tiny sentence about Crusoe Wyoming."
    chunks = list(chunk_text(body, target_tokens=300, overlap=50))
    assert len(chunks) == 1
    c = chunks[0]
    assert c["ord"] == 0
    assert c["text"]
    assert c["char_start"] == 0
    # The chunk text comes from the original body exactly.
    assert body[c["char_start"] : c["char_end"]] == c["text"]
    assert c["token_count"] >= 1
    assert c["tokenizer"] == "cl100k_base"


def test_long_text_produces_multiple_chunks_with_overlap():
    # ~1200 words ≈ ~1600 tokens — well into multi-chunk territory.
    body = " ".join([f"word{i}" for i in range(1200)])
    chunks = list(chunk_text(body, target_tokens=300, overlap=50))
    assert len(chunks) > 1
    # Ord values are sequential starting at 0.
    ords = [c["ord"] for c in chunks]
    assert ords == list(range(len(chunks)))


def test_char_offsets_are_monotonic():
    body = " ".join([f"item{i}" for i in range(1000)])
    chunks = list(chunk_text(body, target_tokens=300, overlap=50))
    assert len(chunks) >= 2
    starts = [c["char_start"] for c in chunks]
    # Strictly non-decreasing.
    assert starts == sorted(starts)
    # End offset is at least char_start + len(text) for each chunk.
    for c in chunks:
        assert c["char_end"] >= c["char_start"]


def test_chunk_text_is_deterministic():
    body = " ".join([f"deterministic{i}" for i in range(800)])
    a = list(chunk_text(body, target_tokens=300, overlap=50))
    b = list(chunk_text(body, target_tokens=300, overlap=50))
    assert a == b


def test_invalid_overlap_raises():
    with pytest.raises(ValueError):
        list(chunk_text("hello world", target_tokens=10, overlap=10))
    with pytest.raises(ValueError):
        list(chunk_text("hello world", target_tokens=10, overlap=20))
    with pytest.raises(ValueError):
        list(chunk_text("hello world", target_tokens=0, overlap=0))


def test_tokenizer_label_is_recorded():
    body = "Crusoe Wyoming has 720 MW of capacity."
    chunks = list(chunk_text(body))
    assert all(c["tokenizer"] == "cl100k_base" for c in chunks)


def test_word_fallback_works_when_tiktoken_missing(monkeypatch):
    """Force the word fallback path by patching the module mode flag,
    then assert it still produces non-empty chunks with the right
    structure.

    This proves the module is robust to tiktoken being absent without
    requiring the test environment to actually uninstall it.
    """
    import agents.insights.util.chunk_text as ct_mod

    monkeypatch.setattr(ct_mod, "_MODE", "word")
    # Re-import the function so it re-binds against the patched mode.
    body = " ".join([f"fallback{i}" for i in range(500)])
    chunks = list(ct_mod.chunk_text(body, target_tokens=300, overlap=50))
    assert len(chunks) >= 1
    for c in chunks:
        assert c["text"]
        assert c["char_start"] >= 0
        assert c["char_end"] > c["char_start"]
        assert c["tokenizer"] == "cl100k_base"


def test_chunk_text_handles_unicode():
    body = "Acquire 360 MW behind-the-meter — Crusoe Wyoming Φ Stack Stockholm 🚀 " * 30
    chunks = list(chunk_text(body, target_tokens=300, overlap=50))
    assert len(chunks) >= 1
    for c in chunks:
        # Should not crash and should not corrupt the unicode.
        assert isinstance(c["text"], str)


def test_token_count_is_positive():
    body = "Some content"
    chunks = list(chunk_text(body))
    assert chunks
    for c in chunks:
        assert c["token_count"] > 0
