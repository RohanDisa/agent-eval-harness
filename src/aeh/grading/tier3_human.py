"""Tier 3: flag for human review. Does not block. Does not decide pass/fail."""

from __future__ import annotations

from typing import Any

from aeh.grading.tier2_golden import parse_divergence
from aeh.models import GradeResult, Task, Trace

LOW_CONFIDENCE = 0.5


def needs_human_review(
    success: bool,
    task: Task,
    grades: list[GradeResult],
) -> bool:
    if success:
        return False
    tier2 = [g for g in grades if g.tier == 2]
    if not task.golden_trace_id:
        return True
    if not tier2:
        return True
    if any(g.errored for g in tier2):
        return True
    for g in tier2:
        parsed = parse_divergence(g)
        if parsed is None or float(parsed.get("confidence") or 0) < LOW_CONFIDENCE:
            return True
    return False


def review_packet(
    task: Task,
    trace: Trace,
    grades: list[GradeResult],
    viewer_hint: str = "",
) -> dict[str, Any]:
    tier1 = [g.detail for g in grades if g.tier == 1 and not g.passed]
    tier2 = next((g.detail for g in grades if g.tier == 2), None)
    return {
        "task_id": task.id,
        "prompt": task.prompt,
        "final_output": trace.final_output,
        "tier1_violations": tier1,
        "tier2_note": tier2,
        "trace_viewer": viewer_hint,
    }
