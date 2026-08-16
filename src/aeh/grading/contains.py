from __future__ import annotations

import re

from aeh.grading.base import final_text, normalize_text, spec_data
from aeh.models import GradeResult, GraderSpec, Task, Trace


def _haystack(spec_dump: dict, trace: Trace) -> str:
    source = spec_dump.get("source", "output")
    if source == "output":
        text = final_text(trace)
    else:
        text = final_text(trace)
    if spec_dump.get("regex"):
        return text
    return normalize_text(text)


class ContainsGrader:
    name = "contains"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = task
        data = spec_data(spec)
        needle = str(data.get("needle", ""))
        text = final_text(trace)
        if data.get("regex"):
            flags = re.IGNORECASE if data.get("ignore_case", True) else 0
            passed = re.search(needle, text, flags) is not None
            detail = f"regex {needle!r} in {text!r}"
        else:
            passed = normalize_text(needle) in normalize_text(text)
            detail = f"needle {needle!r} in {text!r}"
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=detail,
        )


class NotContainsGrader:
    name = "not_contains"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        inner = ContainsGrader().grade(spec, trace, task)
        passed = not inner.passed
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=f"not_contains: {inner.detail}",
        )
