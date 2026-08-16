from __future__ import annotations

import re

from aeh.grading.base import spec_data
from aeh.grading.json_schema import parse_number
from aeh.models import GradeResult, GraderSpec, Task, Trace


class FileStateGrader:
    name = "file_state"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = task
        data = spec_data(spec)
        path = str(data.get("path"))
        files = (trace.sandbox_final_state or {}).get("files") or {}
        if path not in files and data.get("matcher") != "absent":
            return GradeResult(
                grader=self.name, passed=False, score=0.0, detail=f"missing file {path}"
            )
        matcher = data.get("matcher", "exists")
        content = data.get("content")
        # Content is stored at grade time by the runner when available.
        text = data.get("_actual_text")
        if text is None:
            text = (files.get(path) or {}).get("text")
        if matcher == "exists":
            return GradeResult(grader=self.name, passed=True, score=1.0, detail=f"{path} exists")
        if matcher == "absent":
            passed = path not in files
            return GradeResult(
                grader=self.name,
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=f"{path} should be absent",
            )
        if matcher == "hash":
            expected = str(data.get("expected") or data.get("sha256"))
            actual = (files.get(path) or {}).get("sha256")
            passed = actual == expected
            return GradeResult(
                grader=self.name,
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=f"hash {actual} vs {expected}",
            )
        if matcher == "numeric_close":
            if text is None:
                return GradeResult(
                    grader=self.name, passed=False, score=0.0, detail="no file text captured"
                )
            try:
                actual = parse_number(str(text))
            except ValueError as exc:
                return GradeResult(grader=self.name, passed=False, score=0.0, detail=str(exc))
            expected = float(data.get("expected"))
            tolerance = float(data.get("tolerance", 0.01))
            passed = abs(actual - expected) <= tolerance
            return GradeResult(
                grader=self.name,
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=f"{actual} vs {expected} ± {tolerance}",
            )
        if matcher in {"exact", "contains", "not_contains"}:
            if text is None:
                return GradeResult(
                    grader=self.name, passed=False, score=0.0, detail="no file text captured"
                )
            expected = str(data.get("expected", content or ""))
            if matcher == "exact":
                passed = text.strip() == expected.strip()
            elif matcher == "not_contains":
                passed = expected.lower() not in text.lower()
            else:
                passed = expected.lower() in text.lower()
            return GradeResult(
                grader=self.name,
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=f"{matcher}: {text!r} vs {expected!r}",
            )
        if matcher == "regex":
            if text is None:
                return GradeResult(
                    grader=self.name, passed=False, score=0.0, detail="no file text captured"
                )
            passed = re.search(str(data.get("expected", "")), text) is not None
            return GradeResult(
                grader=self.name,
                passed=passed,
                score=1.0 if passed else 0.0,
                detail=f"regex against {text!r}",
            )
        return GradeResult(
            grader=self.name, passed=False, score=0.0, detail=f"unknown matcher {matcher}"
        )
