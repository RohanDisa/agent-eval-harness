from pathlib import Path

from aeh.models import GradeResult, RunResult, Task, ToolCall, Trace


def test_task_accepts_graders_alias_and_outcome_graders():
    via_alias = Task(
        id="a",
        suite="s",
        prompt="p",
        category="tool_use",
        difficulty=1,
        tools=[],
        graders=[{"type": "exact", "expected": "x"}],
        invariants=["rule"],
        golden_trace_id="g1",
    )
    via_name = Task(
        id="b",
        suite="s",
        prompt="p",
        category="tool_use",
        difficulty=1,
        tools=[],
        outcome_graders=[{"type": "exact", "expected": "x"}],
    )
    assert via_alias.outcome_graders[0].type == "exact"
    assert via_alias.graders[0].type == "exact"
    assert via_alias.invariants == ["rule"]
    assert via_alias.golden_trace_id == "g1"
    assert via_name.graders[0].type == "exact"


def test_v1_golden_traces_load_without_span_ids():
    folder = Path(__file__).resolve().parents[1] / "golden" / "traces"
    for path in folder.glob("*.json"):
        trace = Trace.model_validate_json(path.read_text(encoding="utf-8"))
        assert trace.task_id
        tree = trace.ensure_spans()
        assert tree
        assert all(step.span_id for step in trace.steps)


def test_grade_and_run_result_additive_fields():
    grade = GradeResult(grader="exact", passed=True, score=1.0, detail="ok", tier=2)
    result = RunResult(
        trace=Trace(
            run_id="r",
            task_id="t",
            attempt=0,
            seed=0,
            adapter="mock",
            model="mock",
            terminated_by="completed",
            wall_clock_ms=1.0,
        ),
        grades=[grade],
        success=True,
        needs_human_review=True,
    )
    assert result.needs_human_review
    assert result.grades[0].tier == 2
    call = ToolCall(index=0, name="calculator", injected_fault="timeout")
    assert call.injected_fault == "timeout"
    assert call.span_id == ""
