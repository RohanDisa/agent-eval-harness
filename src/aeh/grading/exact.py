from __future__ import annotations

from aeh.grading.base import final_text, normalize_text, spec_data
from aeh.models import GradeResult, GraderSpec, Task, Trace


class ExactGrader:
    name = "exact"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = task
        data = spec_data(spec)
        expected = normalize_text(str(data.get("expected", "")))
        actual = normalize_text(final_text(trace))
        passed = actual == expected
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=f"expected={expected!r} actual={actual!r}",
        )
