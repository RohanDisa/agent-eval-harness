"""Tier 1: suite-supplied pure functions of a Trace. No I/O. Order-independent."""

from __future__ import annotations

from aeh.models import GradeResult, Trace
from aeh.suite.spec import InvariantFn


def run_invariants(
    names: list[str],
    invariants: dict[str, InvariantFn],
    trace: Trace,
) -> list[GradeResult]:
    results: list[GradeResult] = []
    for name in names:
        fn = invariants.get(name)
        if fn is None:
            results.append(
                GradeResult(
                    grader=name,
                    passed=False,
                    score=0.0,
                    detail=f"unknown invariant '{name}'",
                    errored=True,
                    tier=1,
                )
            )
            continue
        outcome = fn(trace)
        results.append(
            GradeResult(
                grader=outcome.name or name,
                passed=outcome.passed,
                score=1.0 if outcome.passed else 0.0,
                detail=outcome.reason,
                tier=1,
            )
        )
    return results
