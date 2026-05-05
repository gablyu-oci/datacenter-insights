"""programmatic_eda — descriptive stats, dtype, null density, skew flags."""
from __future__ import annotations

from typing import Any

from .._shared import basic_stats, numeric_columns
from ...specs.skill_context import SkillContext
from .inputs import ProgrammaticEdaInputs
from .outputs import ColumnStat, ProgrammaticEdaOutputs


def _dtype_of(values: list[Any]) -> str:
    has_int = has_float = has_str = has_bool = False
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            has_bool = True
        elif isinstance(v, int):
            has_int = True
        elif isinstance(v, float):
            has_float = True
        else:
            has_str = True
    if has_str:
        return "string"
    if has_float:
        return "float"
    if has_int:
        return "int"
    if has_bool:
        return "bool"
    return "unknown"


async def run(inputs: ProgrammaticEdaInputs, ctx: SkillContext | None = None) -> ProgrammaticEdaOutputs:
    rows = inputs.rows[: inputs.sample_size]
    n_rows = len(rows)
    if n_rows == 0:
        return ProgrammaticEdaOutputs(
            n_rows=0,
            n_cols=0,
            grain=inputs.grain,
            columns=[],
            top_issues=["empty_input"],
        )

    cols = list(rows[0].keys()) if rows else []
    if inputs.columns:
        cols = [c for c in cols if c in inputs.columns]

    column_stats: list[ColumnStat] = []
    issues: list[str] = []
    for c in cols:
        vals = [r.get(c) for r in rows]
        non_null = [v for v in vals if v is not None]
        null_pct = 1.0 - (len(non_null) / max(1, len(vals)))
        distinct = len({repr(v) for v in non_null})
        dtype = _dtype_of(non_null)

        stats: dict[str, Any] = {}
        skew_flag = False
        if dtype in ("int", "float") and non_null:
            numeric_vals = [float(v) for v in non_null if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if numeric_vals:
                s = basic_stats(numeric_vals)
                stats = s
                # crude skew flag: median far from mean.
                if s.get("stdev", 0) and abs(s["mean"] - s["median"]) > 0.5 * s["stdev"]:
                    skew_flag = True

        if null_pct > 0.5:
            issues.append(f"{c}: high null density ({null_pct:.0%})")
        elif null_pct > 0.3:
            issues.append(f"{c}: moderate null density ({null_pct:.0%})")
        if distinct == 1 and len(non_null) > 0:
            issues.append(f"{c}: zero-variance constant")

        column_stats.append(
            ColumnStat(
                name=c,
                dtype=dtype,
                null_pct=null_pct,
                distinct=distinct,
                stats=stats,
                skew_flag=skew_flag,
            )
        )

    return ProgrammaticEdaOutputs(
        n_rows=n_rows,
        n_cols=len(column_stats),
        grain=inputs.grain,
        columns=column_stats,
        top_issues=issues[:10],
    )


# Touch the helper to avoid an unused-import lint flag.
_ = numeric_columns
