"""Synthetic recall@8 measurement for ``search_documents``.

Phase B.1 of AI Insights v2 (research memo §7).

Real recall@8 measurement requires real EDGAR + permit text in a real
Postgres database. This file does NOT measure that — it can't, because
the test environment is intentionally clean. What it DOES do:

  1. Skip cleanly if the migrations haven't been applied to the test DB.
  2. If the DB is reachable AND migration 017 has run AND we can write,
     seed N synthetic ``permit_passages`` rows whose text matches each
     claim's ``expected_passage_id`` token.
  3. Call ``search_documents(query=claim, k=8)`` for every pair and
     compute recall@8.
  4. Print the mean recall to test output.
  5. Assert mean recall ≥ 0.5 — a low bar because the synthetic seeds
     are contrived; real-world recall@8 will be measured on staging.

The 30-pair golden set lives at
``backend/tests/golden/document_retrieval_recall.jsonl`` (research memo
§7 schema).
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

GOLDEN_PATH = os.path.join(HERE, "golden", "document_retrieval_recall.jsonl")


def _load_golden():
    pairs = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            pairs.append(json.loads(line))
    return pairs


def _maybe_async_engine():
    try:
        from config import settings  # noqa: PLC0415
    except Exception as exc:
        return None, f"config import failed: {exc}"
    db_url = getattr(settings, "database_url", None)
    if not db_url:
        return None, "settings.database_url unset"
    try:
        from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415
        engine = create_async_engine(db_url, future=True)
    except Exception as exc:
        return None, f"create_async_engine failed: {exc}"
    return engine, db_url


async def _migration_017_applied(engine) -> bool:
    from sqlalchemy import text  # noqa: PLC0415
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'permit_passages'"
                )
            )
        ).first()
    return row is not None


def test_golden_set_loads_and_has_30_pairs():
    """Pure file test — runs even without a DB."""
    pairs = _load_golden()
    assert len(pairs) == 30
    # Required slices: count tags.
    tag_counts = {}
    for p in pairs:
        for tag in p.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    # Each scenario slice has 5 entries per the research memo.
    assert tag_counts.get("uncontracted", 0) >= 5
    assert tag_counts.get("offtake", 0) >= 5
    assert tag_counts.get("epa_echo", 0) >= 5
    assert tag_counts.get("abandoned", 0) >= 5
    assert tag_counts.get("amendment", 0) >= 5
    assert tag_counts.get("adversarial", 0) >= 5
    # 5 OOD claims have null expected_passage_id (abstention test).
    null_count = sum(1 for p in pairs if p.get("expected_passage_id") is None)
    assert null_count == 5


@pytest.mark.asyncio
async def test_synthetic_recall_at_8_against_seeded_passages():
    """End-to-end synthetic recall@8 against real BM25 backend.

    Skips if the DB isn't reachable / migration not applied. We seed
    permit_passages with text containing tokens that mirror each claim,
    then run search_documents and verify the seeded passage_id appears
    in the top-8 for that claim. The test prints mean recall@8 to stdout
    and asserts ≥ 0.5 (low bar because synthetic seeds may not perfectly
    BM25-favour the canonical passage on tied scores).
    """
    pairs = _load_golden()
    real_pairs = [p for p in pairs if p.get("expected_passage_id") is not None]
    ood_pairs = [p for p in pairs if p.get("expected_passage_id") is None]

    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    try:
        ok = False
        try:
            ok = await _migration_017_applied(engine)
        except Exception as exc:
            pytest.skip(f"DB unreachable: {exc}")
        if not ok:
            pytest.skip("migration 017 not applied to test DB")
    except Exception:
        await engine.dispose()
        raise

    from sqlalchemy import text as sa_text  # noqa: PLC0415
    from agents.insights.tools.search_documents import search_documents  # noqa: PLC0415

    seeded_ids: dict[str, str] = {}  # external_id -> uuid passage_id
    seed_tag = "synthrecall_" + uuid.uuid4().hex[:8]

    try:
        # Seed a passage for each non-OOD pair. We use the claim itself
        # as the body so BM25 has a slam-dunk match; this is intentional
        # — we're not measuring against real data, just confirming the
        # plumbing is wired right.
        async with engine.begin() as conn:
            for pair in real_pairs:
                src_doc = f"{seed_tag}_{pair['id']}"
                pid = (
                    await conn.execute(
                        sa_text(
                            "INSERT INTO permit_passages "
                            "(source_kind, source_doc_id, ord, text, char_start, "
                            " char_end, token_count, tokenizer) "
                            "VALUES ('generator_permit', :doc, 0, :text, 0, "
                            ":end, :tc, 'cl100k_base') "
                            "RETURNING passage_id"
                        ),
                        {
                            "doc": src_doc,
                            "text": pair["claim"],
                            "end": len(pair["claim"]),
                            "tc": max(1, len(pair["claim"].split())),
                        },
                    )
                ).scalar()
                seeded_ids[pair["expected_passage_id"]] = str(pid)

        # Compute recall@8.
        hits = 0
        for pair in real_pairs:
            out = await search_documents(
                pair["claim"], source="permits", k=8
            )
            assert out["ok"] is True, out
            top_ids = {p["citation"]["passage_id"] for p in out["passages"]}
            expected_uuid = seeded_ids[pair["expected_passage_id"]]
            if expected_uuid in top_ids:
                hits += 1
        recall = hits / max(1, len(real_pairs))
        print(f"\n[recall@8 synthetic] hits={hits}/{len(real_pairs)} mean={recall:.3f}")

        # Abstention check on OOD claims — they should retrieve few/no
        # high-score matches because none of the seeded text mentions
        # the OOD topics. We don't fail the test on OOD because BM25
        # may surface low-relevance passages; just print the diagnostic.
        ood_avg_top_score = 0.0
        for pair in ood_pairs:
            out = await search_documents(pair["claim"], source="permits", k=8)
            if out.get("ok") and out["passages"]:
                ood_avg_top_score += out["passages"][0]["score"]
        ood_avg_top_score /= max(1, len(ood_pairs))
        print(f"[abstention] mean_top_score_on_ood={ood_avg_top_score:.4f}")

        assert recall >= 0.5, (
            f"Synthetic recall@8 {recall:.3f} below 0.5 floor; check seeding."
        )

    finally:
        # Cleanup seeded rows.
        try:
            from sqlalchemy import text as sa_text2  # noqa: PLC0415
            async with engine.begin() as conn:
                await conn.execute(
                    sa_text2(
                        "DELETE FROM permit_passages WHERE source_doc_id LIKE :p"
                    ),
                    {"p": f"{seed_tag}_%"},
                )
        finally:
            await engine.dispose()
