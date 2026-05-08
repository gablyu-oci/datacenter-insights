"""Token-aware document chunking for AI Insights v2 Phase B.1.

Per the research memo §3 (``docs/ai_insights_v2_phases_bcd_research.md``):

  * Target ~300 tokens per chunk with 50-token overlap.
  * Prefer ``tiktoken`` ``cl100k_base`` for token-exact slicing.
  * Fall back to a word-count proxy (~0.75 words ≈ 1 token) when
    tiktoken is unavailable. Stable across reindexing runs is what
    matters; the absolute count is allowed to drift ±5-10%.
  * Track ``char_start`` / ``char_end`` so callers can highlight the
    exact source span later.
  * Idempotent — same input always produces the same chunks.

The function yields plain ``dict``s so callers can hand them straight to
SQLAlchemy ``insert(...).values()`` without an extra dataclass roundtrip.
"""
from __future__ import annotations

from typing import Iterable, Iterator


# ---------------------------------------------------------------------------
# Tokenizer plumbing
# ---------------------------------------------------------------------------

# Resolved at module-load time so a single import is shared. The tokenizer
# name is recorded on every chunk so a future encoder switch can be
# detected and trigger a reindex (per research memo §3 warning).
_TOKENIZER_NAME = "cl100k_base"

try:  # pragma: no cover - import branch is environmental
    import tiktoken

    _ENC = tiktoken.get_encoding(_TOKENIZER_NAME)

    def _encode(text: str) -> list[int]:
        return _ENC.encode(text)

    def _decode(tokens: list[int]) -> str:
        return _ENC.decode(tokens)

    def _tok_count(text: str) -> int:
        return len(_ENC.encode(text))

    _MODE = "tiktoken"

except Exception:  # pragma: no cover
    _MODE = "word"

    def _encode(text: str) -> list[int]:  # type: ignore[misc]
        # The fallback path doesn't go through encode/decode; this stub
        # exists so the module import succeeds when tiktoken is missing.
        raise RuntimeError("tiktoken not available — fallback path is in chunk_text")

    def _decode(tokens: list[int]) -> str:  # type: ignore[misc]
        raise RuntimeError("tiktoken not available — fallback path is in chunk_text")

    def _tok_count(text: str) -> int:
        # ~0.75 words per token is the well-known cl100k_base average for
        # English text. The reverse: tokens ≈ words / 0.75.
        words = text.split()
        return max(1, int(round(len(words) / 0.75))) if words else 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    *,
    target_tokens: int = 300,
    overlap: int = 50,
) -> Iterable[dict]:
    """Yield chunks of ``text`` shaped for the ``edgar_passages`` /
    ``permit_passages`` tables.

    Each yielded dict has the schema::

        {
            "ord": int,            # 0-based chunk index within the document
            "text": str,           # the chunk body
            "char_start": int,     # offset into the original ``text``
            "char_end": int,       # offset; ``char_end - char_start == len(chunk)``
            "token_count": int,    # tokenizer-counted token count
            "tokenizer": str,      # always ``cl100k_base`` so callers can
                                   # detect future encoder switches
        }

    Empty / whitespace-only input yields no chunks (no-op).

    The function is deterministic — feeding the same ``text`` produces
    identical output, byte-for-byte. This is the property the backfill
    script relies on for idempotent re-chunking.
    """
    if not text or not text.strip():
        return
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if target_tokens <= 0:
        raise ValueError("target_tokens must be > 0")
    if overlap >= target_tokens:
        raise ValueError("overlap must be < target_tokens")

    if _MODE == "tiktoken":
        yield from _chunk_with_tiktoken(text, target_tokens=target_tokens, overlap=overlap)
    else:
        yield from _chunk_word_fallback(text, target_tokens=target_tokens, overlap=overlap)


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


def _chunk_with_tiktoken(
    text: str,
    *,
    target_tokens: int,
    overlap: int,
) -> Iterator[dict]:
    """Token-exact slicing path using cl100k_base.

    We encode the full text once, slide a fixed-size window, decode each
    window, then locate the resulting substring in the original ``text``
    starting from a cursor — this gives us correct char offsets even
    when the BPE tokenizer's ``decode`` introduces minor whitespace
    normalisation.
    """
    toks = _encode(text)
    if not toks:
        return
    step = target_tokens - overlap
    char_cursor = 0
    ord_idx = 0
    n = len(toks)
    start = 0
    while start < n:
        window = toks[start : start + target_tokens]
        if not window:
            break
        body = _decode(window)
        # Locate the chunk in the original text starting from the cursor.
        # If decode produced a slightly different leading whitespace, fall
        # back to a stripped find; worst case char offsets approximate.
        idx = text.find(body, char_cursor)
        if idx < 0:
            stripped = body.strip()
            idx = text.find(stripped, char_cursor) if stripped else -1
            if idx < 0:
                idx = char_cursor
                body_len = len(body)
            else:
                body_len = len(stripped)
                body = stripped
        else:
            body_len = len(body)
        char_start = idx
        char_end = idx + body_len

        yield {
            "ord": ord_idx,
            "text": body,
            "char_start": char_start,
            "char_end": char_end,
            "token_count": len(window),
            "tokenizer": _TOKENIZER_NAME,
        }
        ord_idx += 1

        if start + target_tokens >= n:
            break
        # Advance the char cursor past at least the *step* portion of the
        # window so successive overlapping windows don't re-find the same
        # location.
        if step <= 0:
            break
        # Move cursor to right past the start-portion of this chunk.
        # For deterministic offsets the cursor advance is conservative
        # (forward-only).
        try:
            step_text = _decode(window[:step])
            advance = max(1, len(step_text))
        except Exception:  # pragma: no cover - defensive
            advance = max(1, body_len // 2)
        char_cursor = char_start + advance
        start += step


def _chunk_word_fallback(
    text: str,
    *,
    target_tokens: int,
    overlap: int,
) -> Iterator[dict]:
    """Word-count fallback when tiktoken is unavailable.

    We slide a word-count window over ``text``, then walk the original
    string to recover exact char offsets per chunk so the contract on
    ``char_start`` / ``char_end`` is identical to the tiktoken path.
    """
    # 1 token ≈ 0.75 words — invert to convert a token target into a
    # word window.
    target_words = max(1, int(round(target_tokens * 0.75)))
    overlap_words = max(0, int(round(overlap * 0.75)))
    step_words = max(1, target_words - overlap_words)

    # Build a list of (start_offset, end_offset, word_text) tuples by
    # walking the original string once. This preserves the original
    # whitespace exactly so reassembled offsets are precise.
    words: list[tuple[int, int, str]] = []
    i = 0
    n = len(text)
    while i < n:
        # Skip whitespace.
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        while i < n and not text[i].isspace():
            i += 1
        words.append((start, i, text[start:i]))

    if not words:
        return

    ord_idx = 0
    w = 0
    while w < len(words):
        window = words[w : w + target_words]
        if not window:
            break
        char_start = window[0][0]
        char_end = window[-1][1]
        body = text[char_start:char_end]
        token_count = max(1, int(round(len(window) / 0.75)))
        yield {
            "ord": ord_idx,
            "text": body,
            "char_start": char_start,
            "char_end": char_end,
            "token_count": token_count,
            "tokenizer": _TOKENIZER_NAME,
        }
        ord_idx += 1
        if w + target_words >= len(words):
            break
        w += step_words


__all__ = ["chunk_text"]
