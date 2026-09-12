from pathlib import Path

import pytest

from aeh.execution.runner import SuiteRunner, success_from_grades
from aeh.grading.tier1_invariants import run_invariants
from aeh.grading.tier2_golden import compare_to_golden
from aeh.grading.tier3_human import needs_human_review
from aeh.models import GradeResult, Step, Task, ToolCall, Trace
from aeh.suite.spec import InvariantResult


def _task(**kwargs) -> Task:
    data = {
        "id": "toy-add",
        "suite": "toy_math",
        "prompt": "19+23",
        "category": "tool_use",
        "difficulty": 1,
        "tools": ["calculator"],
        "outcome_graders": [{"type": "numeric_close", "expected": 42, "tolerance": 0.001}],
        "invariants": ["calculator_only"],
        "golden_trace_id": "toy-add",
    }
    data.update(kwargs)
    return Task(**data)


def _trace(final: str, extra_tool: str | None = None, expression: str = "21+21") -> Trace:
    steps = [
        Step(
            index=0,
            span_id="step-0",
            tool_call=ToolCall(
                index=0,
                name="calculator",
                arguments={"expression": expression},
                result=final,
                span_id="tool-0",
                parent_span_id="step-0",
            ),
        )
    ]
    if extra_tool:
        steps.append(
            Step(
                index=1,
                span_id="step-1",
                tool_call=ToolCall(
                    index=1,
                    name=extra_tool,
                    arguments={},
                    result="x",
                    hallucinated=True,
                    span_id="tool-1",
                    parent_span_id="step-1",
                ),
            )
        )
    return Trace(
        run_id="r",
        task_id="toy-add",
        attempt=0,
        seed=0,
        adapter="mock",
        model="mock",
        steps=steps,
        final_output=final,
        terminated_by="completed",
        wall_clock_ms=1.0,
        allowed_tools=["calculator"],
        task_category="tool_use",
    )


def test_invariant_pass_and_fail():
    from suites.toy_math.invariants import calculator_only

    ok = run_invariants(["calculator_only"], {"calculator_only": calculator_only}, _trace("42"))
    bad = run_invariants(
        ["calculator_only"],
        {"calculator_only": calculator_only},
        _trace("42", extra_tool="fs_write"),
    )
    assert ok[0].passed and ok[0].tier == 1
    assert bad[0].passed is False and bad[0].tier == 1


def test_unknown_invariant_errors():
    grades = run_invariants(["ghost"], {}, _trace("42"))
    assert grades[0].errored and grades[0].tier == 1


def test_success_ignores_tier1_and_tier2():
    grades = [
        GradeResult(grader="numeric_close", passed=True, score=1.0, detail="ok", tier=0),
        GradeResult(grader="calculator_only", passed=False, score=0.0, detail="broke", tier=1),
        GradeResult(grader="golden_divergence", passed=True, score=0.9, detail="{}", tier=2),
    ]
    assert success_from_grades(grades) is True


def test_successful_invariant_violation_still_reported():
    from suites.toy_math.invariants import calculator_only

    grades = [
        GradeResult(grader="numeric_close", passed=True, score=1.0, detail="ok", tier=0),
    ]
    grades.extend(
        run_invariants(
            ["calculator_only"],
            {"calculator_only": calculator_only},
            _trace("42", extra_tool="nuke"),
        )
    )
    assert success_from_grades(grades) is True
    assert any(g.tier == 1 and not g.passed for g in grades)


@pytest.mark.asyncio
async def test_tier2_does_not_flag_correct_but_different_as_failure():
    task = _task()
    different = _trace("42", expression="21+21")
    golden = _trace("42", expression="19+23")
    grade = await compare_to_golden(task, different, golden, None)
    assert grade.tier == 2
    assert grade.passed is True
    assert success_from_grades(
        [
            GradeResult(grader="numeric_close", passed=True, score=1.0, detail="ok", tier=0),
            grade,
        ]
    )


@pytest.mark.asyncio
async def test_tier2_localizes_failed_trace():
    class Scripted:
        model = "judge-test"

        async def chat(self, messages, tools=None):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"divergence_step": 0, "reason": "wrong sum", "confidence": 0.9}'
                            )
                        }
                    }
                ]
            }

    task = _task()
    failed = _trace("99", expression="1+1")
    golden = _trace("42", expression="19+23")
    grade = await compare_to_golden(task, failed, golden, Scripted())
    assert grade.errored is False
    assert grade.passed is True
    assert '"divergence_step": 0' in grade.detail
    assert (
        success_from_grades(
            [
                GradeResult(grader="numeric_close", passed=False, score=0.0, detail="no", tier=0),
                grade,
            ]
        )
        is False
    )


@pytest.mark.asyncio
async def test_tier2_retries_then_errors_on_bad_json():
    class Bad:
        model = "judge-test"

        async def chat(self, messages, tools=None):
            return {"choices": [{"message": {"content": "not-json"}}]}

    grade = await compare_to_golden(_task(), _trace("1"), _trace("42"), Bad())
    assert grade.errored and grade.tier == 2
    assert grade.passed is True


def test_tier3_flags_when_no_golden_or_low_confidence():
    task = _task(golden_trace_id=None)
    assert needs_human_review(False, task, []) is True
    task2 = _task()
    low = GradeResult(
        grader="golden_divergence",
        passed=True,
        score=0.1,
        detail='{"divergence_step": 0, "reason": "x", "confidence": 0.1}',
        tier=2,
    )
    assert needs_human_review(False, task2, [low]) is True
    assert needs_human_review(True, task2, []) is False


@pytest.mark.asyncio
async def test_runner_reports_invariant_on_successful_wrong_tool(repo_root: Path, tmp_path: Path):
    runner = SuiteRunner(
        suite=str(repo_root / "suites" / "toy_math"),
        adapter_name="mock",
        model="mock",
        attempts=1,
        repo_root=repo_root,
        db_path=tmp_path / "runs.db",
        tasks_filter=["toy-add"],
        mock_auto_satisfy=False,
        mock_scripts={
            "toy-add": [
                {"tool": "fs_write", "arguments": {"path": "x", "content": "y"}},
                {"final": "42"},
            ]
        },
        redact=False,
    )
    suite = await runner.run()
    result = suite.results[0]
    assert result.success is True
    assert any(g.tier == 1 and not g.passed for g in result.grades)


def test_invariant_fn_shape():
    def always_ok(trace: Trace) -> InvariantResult:
        return InvariantResult(name="always_ok", passed=True, reason="ok")

    assert always_ok(_trace("42")).passed
