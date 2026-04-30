"""
Anomaly detector — Phase 2 (AC5).

For each tracked metric we maintain a trailing 12-week window. The detector
computes the mean and standard deviation of the prior 12 weeks (excluding the
current week), then flags the current week as anomalous if its z-score is
outside ±2σ. Results are upserted into the `anomalies` table keyed by
(metric_kind, dimension, period_end).

Metrics evaluated (Phase 2):
  - pjm_queue_mw       : sum of new PJM queue capacity_mw per ISO week
  - permit_filings_va  : count of new VA generator permits per ISO week
  - permit_filings_ny  : count of new NY Title V/State Facility filings
  - edgar_capacity_mw  : sum of edgar_extractions.capacity_mw per ISO week

Each metric is a (kind, dimension) pair; dimension is "ALL" for global
roll-ups but is set to a state code or fuel where applicable.

Public entry point:
    async def detect_anomalies(session) -> dict
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import Anomaly

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

WINDOW_WEEKS = 12          # baseline window
Z_THRESHOLD = 2.0          # ±2σ flag
MIN_BASELINE_OBS = 4       # below this, baseline is too small to trust
DEFAULT_LOOKBACK_WEEKS = 16  # how far back to evaluate (catches new anomalies
                             # if detector is offline a few weeks)


# ---------------------------------------------------------------------------
# Week bucketing — ISO week ending on Sunday
# ---------------------------------------------------------------------------

def _week_end(d: date) -> date:
    """Return the Sunday that ends the ISO week containing d."""
    # weekday(): Mon=0 .. Sun=6
    return d + timedelta(days=(6 - d.weekday()))


# ---------------------------------------------------------------------------
# Per-metric loaders. Each returns a dict {period_end_iso: value}.
# ---------------------------------------------------------------------------

async def _series_pjm_queue(session) -> dict[date, float]:
    """Sum of new PJM queue MW per week. PJM data lands in generator_permits
    with source='pjm'; the per-row date is issued_date (application date).
    """
    rows = await session.execute(text("""
        SELECT
          DATE_TRUNC('week',
                     COALESCE(issued_date, created_at::date))::date AS wk,
          COALESCE(SUM(rated_mw_total), 0) AS mw
        FROM generator_permits
        WHERE source = 'pjm'
          AND COALESCE(issued_date, created_at::date) IS NOT NULL
        GROUP BY 1
    """))
    out: dict[date, float] = {}
    for r in rows:
        wk_mon = r[0]
        if wk_mon is None:
            continue
        out[wk_mon + timedelta(days=6)] = float(r[1] or 0.0)
    return out


async def _series_permits(session, state_code: str) -> dict[date, float]:
    """Count of new generator permits per ISO week for a given state. Uses
    issued_date as the per-row date; falls back to created_at when missing.
    """
    rows = await session.execute(text("""
        SELECT
          DATE_TRUNC('week',
                     COALESCE(issued_date, created_at::date))::date AS wk,
          COUNT(*) AS n
        FROM generator_permits
        WHERE state_code = :sc
          AND COALESCE(issued_date, created_at::date) IS NOT NULL
        GROUP BY 1
    """), {"sc": state_code})
    out: dict[date, float] = {}
    for r in rows:
        if r[0] is None:
            continue
        out[r[0] + timedelta(days=6)] = float(r[1] or 0)
    return out


async def _series_edgar_mw(session) -> dict[date, float]:
    rows = await session.execute(text("""
        SELECT
          DATE_TRUNC('week',
                     COALESCE(filing_date, retrieved_at::date))::date AS wk,
          COALESCE(SUM(capacity_mw), 0) AS mw
        FROM edgar_extractions
        WHERE capacity_mw IS NOT NULL
          AND COALESCE(filing_date, retrieved_at::date) IS NOT NULL
        GROUP BY 1
    """))
    out: dict[date, float] = {}
    for r in rows:
        if r[0] is None:
            continue
        out[r[0] + timedelta(days=6)] = float(r[1] or 0.0)
    return out


# ---------------------------------------------------------------------------
# Core algorithm — trailing 12-week mean ± 2σ
# ---------------------------------------------------------------------------

def _evaluate_series(
    metric_kind: str,
    dimension: str,
    series: dict[date, float],
    *,
    today: Optional[date] = None,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
) -> list[dict]:
    """Return a list of anomaly dicts ready for insert. Skips weeks without
    a sufficient baseline (need MIN_BASELINE_OBS weeks of prior data)."""
    if not series:
        return []
    if today is None:
        today = date.today()
    end_of_this_week = _week_end(today)

    weeks_sorted = sorted(series.keys())
    findings: list[dict] = []

    # Evaluate the last `lookback_weeks` weeks ending on or before this week.
    cutoff = end_of_this_week - timedelta(weeks=lookback_weeks)
    for wk in weeks_sorted:
        if wk < cutoff or wk > end_of_this_week:
            continue
        # Build the trailing baseline: WINDOW_WEEKS prior weeks (strictly before wk).
        baseline_vals = [
            series[w] for w in weeks_sorted
            if w < wk and (wk - w).days <= WINDOW_WEEKS * 7
        ]
        if len(baseline_vals) < MIN_BASELINE_OBS:
            continue
        try:
            mean = statistics.fmean(baseline_vals)
            stdev = statistics.pstdev(baseline_vals)
        except statistics.StatisticsError:
            continue
        if stdev <= 0:
            continue
        value = series[wk]
        z = (value - mean) / stdev
        if abs(z) < Z_THRESHOLD:
            continue
        findings.append({
            "metric_kind": metric_kind,
            "dimension": dimension,
            "period_end": wk,
            "value": float(value),
            "baseline_mean": float(mean),
            "baseline_stddev": float(stdev),
            "z_score": float(z),
            "direction": "spike" if z > 0 else "drop",
            "sample_size": len(baseline_vals),
            "note": (
                f"{metric_kind}[{dimension}] week-ending {wk.isoformat()}: "
                f"value={value:.1f} vs baseline μ={mean:.1f} σ={stdev:.1f} "
                f"(z={z:+.2f}, n={len(baseline_vals)})"
            ),
        })
    return findings


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

async def _upsert(session, findings: Iterable[dict]) -> int:
    n = 0
    for f in findings:
        stmt = pg_insert(Anomaly.__table__).values(**f)
        stmt = stmt.on_conflict_do_update(
            index_elements=["metric_kind", "dimension", "period_end"],
            set_={
                "value": stmt.excluded.value,
                "baseline_mean": stmt.excluded.baseline_mean,
                "baseline_stddev": stmt.excluded.baseline_stddev,
                "z_score": stmt.excluded.z_score,
                "direction": stmt.excluded.direction,
                "sample_size": stmt.excluded.sample_size,
                "note": stmt.excluded.note,
                "detected_at": datetime.utcnow(),
            },
        )
        await session.execute(stmt)
        n += 1
    return n


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def detect_anomalies(session) -> dict:
    """Run all metric series through the ±2σ detector and persist findings.

    Returns a summary dict with metrics_evaluated and anomalies_recorded.
    Failures inside one series are logged but don't halt the others.
    """
    metrics_evaluated = 0
    all_findings: list[dict] = []

    # 1) PJM queue MW (global)
    try:
        s = await _series_pjm_queue(session)
        if s:
            metrics_evaluated += 1
            all_findings.extend(_evaluate_series("pjm_queue_mw", "ALL", s))
    except Exception as exc:
        logger.warning("anomaly.pjm_queue_failed: %s", exc)

    # 2) Permit filings — VA, NY (per-state)
    for sc in ("VA", "NY", "TX", "OH", "IA"):
        try:
            s = await _series_permits(session, sc)
            if s:
                metrics_evaluated += 1
                all_findings.extend(
                    _evaluate_series(f"permit_filings", sc, s)
                )
        except Exception as exc:
            logger.warning("anomaly.permits_%s_failed: %s", sc, exc)

    # 3) EDGAR capacity_mw (global)
    try:
        s = await _series_edgar_mw(session)
        if s:
            metrics_evaluated += 1
            all_findings.extend(_evaluate_series("edgar_capacity_mw", "ALL", s))
    except Exception as exc:
        logger.warning("anomaly.edgar_failed: %s", exc)

    recorded = await _upsert(session, all_findings)

    logger.info(
        "anomaly_detector: metrics_evaluated=%d findings=%d recorded=%d",
        metrics_evaluated, len(all_findings), recorded,
    )
    return {
        "metrics_evaluated": metrics_evaluated,
        "findings": len(all_findings),
        "anomalies_recorded": recorded,
    }
