from pathlib import Path

from aeh.grading.contains import ContainsGrader, NotContainsGrader
from aeh.grading.exact import ExactGrader
from aeh.grading.file_state import FileStateGrader
from aeh.grading.json_schema import JsonSchemaGrader, NumericCloseGrader
from aeh.grading.sql_result import SqlResultGrader, StepBudgetGrader, ToolSequenceGrader
from aeh.models import GraderSpec, Step, Task, ToolCall, Trace


def _task() -> Task:
    return Task(
        id="t",
        suite="s",
        prompt="p",
        category="tool_use",
        difficulty=1,
        tools=["calculator"],
        graders=[GraderSpec(type="exact", expected="yes")],
    )


def _trace(output: str | None = "yes", **kwargs) -> Trace:
    data = dict(
        run_id="r",
        task_id="t",
        attempt=0,
        seed=0,
        adapter="mock",
        model="m",
        steps=[],
        final_output=output,
        terminated_by="completed",
        wall_clock_ms=1,
        sandbox_final_state={"files": {}},
    )
    data.update(kwargs)
    return Trace(**data)


def test_exact_pass_fail():
    g = ExactGrader()
    spec = GraderSpec(type="exact", expected="Yes")
    assert g.grade(spec, _trace("YES"), _task()).passed
    assert not g.grade(spec, _trace("no"), _task()).passed


def test_contains_and_not_contains():
    spec = GraderSpec(type="contains", needle="apple")
    assert ContainsGrader().grade(spec, _trace("I like Apple pie"), _task()).passed
    assert NotContainsGrader().grade(spec, _trace("orange"), _task()).passed
    spec_re = GraderSpec(type="contains", needle="ap+le", regex=True)
    assert ContainsGrader().grade(spec_re, _trace("apple"), _task()).passed


def test_numeric_close():
    spec = GraderSpec(type="numeric_close", expected=10.0, tolerance=0.1)
    assert NumericCloseGrader().grade(spec, _trace("total 10.05"), _task()).passed
    assert not NumericCloseGrader().grade(spec, _trace("12"), _task()).passed
    assert not NumericCloseGrader().grade(spec, _trace("nope"), _task()).passed


def test_json_schema():
    spec = GraderSpec(
        type="json_schema",
        schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    )
    assert JsonSchemaGrader().grade(spec, _trace('{"ok": true}'), _task()).passed
    assert not JsonSchemaGrader().grade(spec, _trace("not-json"), _task()).passed
    assert not JsonSchemaGrader().grade(spec, _trace("{}"), _task()).passed


def test_file_state_variants():
    g = FileStateGrader()
    files = {"answer.txt": {"sha256": "abc", "size": 2, "text": "42.0"}}
    tr = _trace(sandbox_final_state={"files": files})
    assert g.grade(
        GraderSpec(type="file_state", path="answer.txt", matcher="exists"), tr, _task()
    ).passed
    assert g.grade(
        GraderSpec(
            type="file_state",
            path="answer.txt",
            matcher="numeric_close",
            expected=42,
            tolerance=0.1,
        ),
        tr,
        _task(),
    ).passed
    assert g.grade(
        GraderSpec(type="file_state", path="answer.txt", matcher="exact", expected="42.0"),
        tr,
        _task(),
    ).passed
    assert g.grade(
        GraderSpec(type="file_state", path="answer.txt", matcher="contains", expected="42"),
        tr,
        _task(),
    ).passed
    assert g.grade(
        GraderSpec(type="file_state", path="answer.txt", matcher="hash", expected="abc"),
        tr,
        _task(),
    ).passed
    assert g.grade(
        GraderSpec(type="file_state", path="missing.txt", matcher="absent"), tr, _task()
    ).passed
    assert not g.grade(
        GraderSpec(type="file_state", path="nope.txt", matcher="exists"), tr, _task()
    ).passed


def test_step_budget_and_tool_sequence():
    steps = [
        Step(index=0, tool_call=ToolCall(index=0, name="fs_read", arguments={}, latency_ms=1)),
        Step(index=1, tool_call=ToolCall(index=1, name="calculator", arguments={}, latency_ms=1)),
    ]
    tr = _trace(steps=steps)
    assert StepBudgetGrader().grade(GraderSpec(type="step_budget", max_steps=2), tr, _task()).passed
    assert (
        not StepBudgetGrader()
        .grade(GraderSpec(type="step_budget", max_steps=1), tr, _task())
        .passed
    )
    assert (
        ToolSequenceGrader()
        .grade(GraderSpec(type="tool_sequence", required=["fs_read", "calculator"]), tr, _task())
        .passed
    )
    assert (
        not ToolSequenceGrader()
        .grade(GraderSpec(type="tool_sequence", forbidden=["calculator"]), tr, _task())
        .passed
    )
    assert (
        ToolSequenceGrader()
        .grade(
            GraderSpec(type="tool_sequence", required=["fs_read", "calculator"], ordered=True),
            tr,
            _task(),
        )
        .passed
    )


def test_sql_result(fixture_db: Path):
    g = SqlResultGrader(fixture_db)
    spec = GraderSpec(type="sql_result", query="SELECT COUNT(*) FROM customers", expected=[[5]])
    assert g.grade(spec, _trace(), _task()).passed
    spec_bad = GraderSpec(type="sql_result", query="SELECT COUNT(*) FROM customers", expected=[[0]])
    assert not g.grade(spec_bad, _trace(), _task()).passed
