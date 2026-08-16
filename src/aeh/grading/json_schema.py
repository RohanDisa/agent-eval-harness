from __future__ import annotations

import json
import re
from typing import Any

from aeh.grading.base import final_text, spec_data
from aeh.models import GradeResult, GraderSpec, Task, Trace


def parse_number(text: str) -> float:
    cleaned = text.strip().replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        raise ValueError(f"no number in {text!r}")
    return float(match.group(0))


class NumericCloseGrader:
    name = "numeric_close"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = task
        data = spec_data(spec)
        expected = float(data.get("expected"))
        tolerance = float(data.get("tolerance", 1e-6))
        try:
            actual = parse_number(final_text(trace))
        except ValueError as exc:
            return GradeResult(grader=self.name, passed=False, score=0.0, detail=str(exc))
        passed = abs(actual - expected) <= tolerance
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail=f"expected {expected} ± {tolerance}, got {actual}",
        )


def _validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    if expected_type in type_map and not isinstance(instance, type_map[expected_type]):
        if not (expected_type == "number" and isinstance(instance, bool)):
            errors.append(f"{path}: expected {expected_type}")
            return errors
    if expected_type == "object" and isinstance(instance, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing {key}")
        props = schema.get("properties") or {}
        extra_ok = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                errors.extend(_validate(value, props[key], f"{path}.{key}"))
            elif extra_ok is False:
                errors.append(f"{path}: unexpected {key}")
    if expected_type == "array" and isinstance(instance, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(_validate(item, item_schema, f"{path}[{i}]"))
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum")
    return errors


class JsonSchemaGrader:
    name = "json_schema"

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        _ = task
        data = spec_data(spec)
        text = final_text(trace).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return GradeResult(
                grader=self.name, passed=False, score=0.0, detail=f"invalid json: {exc}"
            )
        errors = _validate(parsed, data.get("schema") or {})
        passed = not errors
        return GradeResult(
            grader=self.name,
            passed=passed,
            score=1.0 if passed else 0.0,
            detail="ok" if passed else "; ".join(errors),
        )
