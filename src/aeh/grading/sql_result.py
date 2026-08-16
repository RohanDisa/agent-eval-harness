from __future__ import annotations

import sqlite3
from pathlib import Path

from aeh.grading.base import spec_data
from aeh.models import GradeResult, GraderSpec, Task, Trace


class SqlResultGrader:
    name = "sql_result"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = trace, task
        data = spec_data(spec)
        db_path = Path(data.get("db_path") or self.db_path or "")
        if not db_path:
            return GradeResult(
                grader=self.name, passed=False, score=0.0, detail="no fixture db configured"
            )
        query = str(data.get("query"))
        expected = data.get("expected")
        try:
            conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
            try:
                rows = [list(row) for row in conn.execute(query).fetchall()]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return GradeResult(grader=self.name, passed=False, score=0.0, detail=str(exc))
        passed = rows == expected
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=f"got {rows!r} expected {expected!r}",
        )


class StepBudgetGrader:
    name = "step_budget"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = task
        data = spec_data(spec)
        ceiling = int(data.get("max_steps"))
        used = len(trace.steps)
        passed = used <= ceiling
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=f"{used} steps (max {ceiling})",
        )


class ToolSequenceGrader:
    name = "tool_sequence"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = task
        data = spec_data(spec)
        called = [s.tool_call.name for s in trace.steps if s.tool_call]
        required = list(data.get("required") or [])
        forbidden = list(data.get("forbidden") or [])
        ordered = bool(data.get("ordered", False))
        missing = [name for name in required if name not in called]
        hit_forbidden = [name for name in forbidden if name in called]
        if ordered and required:
            idx = 0
            for name in called:
                if idx < len(required) and name == required[idx]:
                    idx += 1
            if idx != len(required):
                missing = required[idx:]
        passed = not missing and not hit_forbidden
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=f"called={called} missing={missing} forbidden={hit_forbidden}",
        )
