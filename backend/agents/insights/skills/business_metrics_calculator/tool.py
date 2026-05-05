"""business_metrics_calculator — deterministic registered metrics.

Pure Python; no LLM call. Closed registry of metric names per system_fragment.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from ...specs.skill_context import SkillContext
from .inputs import BusinessMetricsCalculatorInputs
from .outputs import BreakdownEntry, BusinessMetricsCalculatorOutputs


def _coerce_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _apply_filters(
    rows: list[dict[str, Any]], filters: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if not filters:
        return rows
    out: list[dict[str, Any]] = []
    for r in rows:
        keep = True
        for k, v in filters.items():
            cell = r.get(k)
            if isinstance(v, list):
                if cell not in v:
                    keep = False
                    break
            else:
                if cell != v:
                    keep = False
                    break
        if keep:
            out.append(r)
    return out


def _sum_field(rows: Iterable[dict[str, Any]], *fields: str) -> tuple[float, int]:
    total = 0.0
    n = 0
    for r in rows:
        for f in fields:
            v = _coerce_float(r.get(f))
            if v is not None:
                total += v
                n += 1
                break
    return total, n


def _gw_total(rows: list[dict[str, Any]], notes: list[str]) -> tuple[float, int]:
    total, n = _sum_field(rows, "contracted_gw", "gw")
    if n == 0:
        notes.append("no rows had a numeric contracted_gw / gw column")
    return total, n


def _contracted_renewable_share(
    rows: list[dict[str, Any]], notes: list[str]
) -> tuple[float, int]:
    total = 0.0
    renew = 0.0
    n = 0
    for r in rows:
        v = _coerce_float(r.get("contracted_gw") or r.get("gw"))
        if v is None:
            continue
        n += 1
        total += v
        kind = (r.get("energy_type") or r.get("deal_type") or "").lower()
        if kind in {"renewable", "solar", "wind", "hydro", "geothermal"}:
            renew += v
    if total <= 0:
        notes.append("no positive contracted_gw rows; share=0")
        return 0.0, n
    return renew / total, n


def _gap_vs_implied(
    rows: list[dict[str, Any]], notes: list[str]
) -> tuple[float, int]:
    contracted, _ = _sum_field(rows, "contracted_gw", "gw")
    implied, _ = _sum_field(rows, "implied_gw")
    if implied == 0:
        notes.append("no implied_gw found; gap defaults to contracted total")
    return contracted - implied, len(rows)


def _deals_per_quarter(
    rows: list[dict[str, Any]], notes: list[str]
) -> tuple[float, int, list[BreakdownEntry]]:
    counts: dict[str, int] = defaultdict(int)
    n = 0
    for r in rows:
        q = r.get("quarter") or r.get("fiscal_quarter")
        if not q:
            continue
        counts[str(q)] += 1
        n += 1
    if not counts:
        notes.append("no rows had a quarter / fiscal_quarter field")
        return 0.0, 0, []
    breakdown = [
        BreakdownEntry(key=k, value=float(v))
        for k, v in sorted(counts.items())
    ]
    mean_per_q = sum(counts.values()) / len(counts)
    return mean_per_q, n, breakdown


async def run(
    inputs: BusinessMetricsCalculatorInputs,
    ctx: SkillContext | None = None,
) -> BusinessMetricsCalculatorOutputs:
    rows = _apply_filters(inputs.rows, inputs.filters)
    notes: list[str] = []

    if inputs.metric_name == "gw_total":
        v, n = _gw_total(rows, notes)
        return BusinessMetricsCalculatorOutputs(
            metric_name=inputs.metric_name, value=v, unit="GW", inputs_seen=n, notes=notes
        )
    if inputs.metric_name == "contracted_renewable_share":
        v, n = _contracted_renewable_share(rows, notes)
        return BusinessMetricsCalculatorOutputs(
            metric_name=inputs.metric_name, value=v, unit="pct", inputs_seen=n, notes=notes
        )
    if inputs.metric_name == "gap_vs_implied":
        v, n = _gap_vs_implied(rows, notes)
        return BusinessMetricsCalculatorOutputs(
            metric_name=inputs.metric_name, value=v, unit="GW", inputs_seen=n, notes=notes
        )
    if inputs.metric_name == "deals_per_quarter":
        v, n, breakdown = _deals_per_quarter(rows, notes)
        return BusinessMetricsCalculatorOutputs(
            metric_name=inputs.metric_name,
            value=v,
            unit="count",
            inputs_seen=n,
            breakdown=breakdown,
            notes=notes,
        )

    # Literal type narrows above; this is unreachable. Defensive fallback:
    raise ValueError(f"unknown_metric: {inputs.metric_name!r}")
