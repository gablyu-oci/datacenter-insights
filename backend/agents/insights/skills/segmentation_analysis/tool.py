"""segmentation_analysis — categorical cut + outlier detection.

Pure Python; no LLM call.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from ...specs.skill_context import SkillContext
from .inputs import SegmentationAnalysisInputs
from .outputs import Segment, SegmentationAnalysisOutputs

_OUTPUT_CAP = 50


async def run(
    inputs: SegmentationAnalysisInputs,
    ctx: SkillContext | None = None,
) -> SegmentationAnalysisOutputs:
    rows = inputs.rows
    notes: list[str] = []

    # Bucket rows by the group_by field, skipping null groups.
    buckets: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    skipped_null = 0
    for r in rows:
        g = r.get(inputs.group_by)
        if g is None or g == "":
            skipped_null += 1
            continue
        key = str(g)
        counts[key] += 1
        if inputs.agg == "count":
            continue
        if inputs.metric_field is None:
            continue
        v = r.get(inputs.metric_field)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            buckets[key].append(float(v))

    if skipped_null:
        notes.append(f"skipped {skipped_null} rows with null {inputs.group_by!r}")

    # Compute per-segment value
    segments_raw: list[tuple[str, int, float]] = []  # (name, n, value)
    for key, n in counts.items():
        if n < inputs.min_segment_size:
            continue
        if inputs.agg == "count":
            value = float(n)
        elif inputs.agg == "sum":
            value = sum(buckets[key]) if buckets[key] else 0.0
        else:  # avg
            value = (sum(buckets[key]) / len(buckets[key])) if buckets[key] else 0.0
        segments_raw.append((key, n, value))

    # Total
    if inputs.agg == "count":
        total_value = float(sum(n for _, n, _ in segments_raw))
    elif inputs.agg == "sum":
        total_value = sum(v for _, _, v in segments_raw)
    else:  # avg of segment means is misleading; use weighted mean
        weighted_num = sum(v * n for _, n, v in segments_raw)
        weighted_den = sum(n for _, n, _ in segments_raw)
        total_value = weighted_num / weighted_den if weighted_den else 0.0

    # Sort + cap
    segments_raw.sort(key=lambda t: t[2], reverse=True)
    if len(segments_raw) > _OUTPUT_CAP:
        notes.append(f"truncated tail of {len(segments_raw) - _OUTPUT_CAP} segments")
        segments_raw = segments_raw[:_OUTPUT_CAP]

    # Outliers via z-score across segment values
    values = [v for _, _, v in segments_raw]
    mean_v = statistics.fmean(values) if values else 0.0
    std_v = statistics.pstdev(values) if len(values) > 1 else 0.0

    segs: list[Segment] = []
    outliers: list[Segment] = []
    denom_total = total_value if total_value not in (0.0,) else 0.0
    for name, n, v in segments_raw:
        share = (v / denom_total) if denom_total else 0.0
        z: float | None = None
        if std_v > 0:
            z = (v - mean_v) / std_v
        seg = Segment(
            name=name,
            n_rows=n,
            value=v,
            share_of_total=max(0.0, min(1.0, share)),
            z_score=z,
        )
        segs.append(seg)
        if z is not None and abs(z) > 2.0:
            outliers.append(seg)

    return SegmentationAnalysisOutputs(
        segments=segs,
        outlier_segments=outliers,
        total_value=total_value,
        notes=notes,
    )
