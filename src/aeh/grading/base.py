from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

from aeh.models import GradeResult, GraderSpec, Task, Trace


@runtime_checkable
class Grader(Protocol):
    name: str

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult: ...


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())


def final_text(trace: Trace) -> str:
    return trace.final_output or ""


def run_graders(
    graders: dict[str, Grader],
    task: Task,
    trace: Trace,
) -> list[GradeResult]:
    results: list[GradeResult] = []
    for spec in task.graders:
        grader = graders.get(spec.type)
        started = time.perf_counter()
        if grader is None:
            results.append(
                GradeResult(
                    grader=spec.type,
                    passed=False,
                    score=0.0,
                    detail=f"unknown grader '{spec.type}'",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    errored=True,
                )
            )
            continue
        try:
            result = grader.grade(spec, trace, task)
        except Exception as exc:  # recorded as harness error
            result = GradeResult(
                grader=spec.type,
                passed=False,
                score=0.0,
                detail=f"grader exception: {exc}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                errored=True,
            )
        if result.latency_ms == 0:
            result.latency_ms = (time.perf_counter() - started) * 1000.0
        results.append(result)
    return results


def spec_data(spec: GraderSpec) -> dict[str, Any]:
    return spec.model_dump()
