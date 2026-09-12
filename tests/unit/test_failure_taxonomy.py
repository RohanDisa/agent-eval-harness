from datetime import datetime

from aeh.metrics.failure_taxonomy import classify_failure
from aeh.models import GradeResult, Step, ToolCall, Trace


def _trace(**kwargs) -> Trace:
    base = dict(
        run_id="r",
        task_id="t",
        attempt=0,
        seed=0,
        adapter="mock",
        model="m",
        steps=[],
        final_output="answer",
        terminated_by="completed",
        wall_clock_ms=1,
        allowed_tools=["calculator"],
        task_category="tool_use",
    )
    base.update(kwargs)
    return Trace(**base)


def _fail() -> list[GradeResult]:
    return [GradeResult(grader="exact", passed=False, score=0.0, detail="no")]


def _tc(**kwargs) -> ToolCall:
    data = dict(
        index=0, name="calculator", arguments={}, latency_ms=1.0, started_at=datetime.utcnow()
    )
    data.update(kwargs)
    return ToolCall(**data)


def test_success_is_none():
    assert (
        classify_failure(
            _trace(), [GradeResult(grader="exact", passed=True, score=1.0, detail="ok")]
        )
        is None
    )


def test_tool_error():
    t = _trace(steps=[Step(index=0, tool_call=_tc(error="boom"))])
    assert classify_failure(t, _fail()) == "tool_error"


def test_malformed():
    t = _trace(steps=[Step(index=0, tool_call=_tc(malformed=True, error="malformed_tool_call: x"))])
    assert classify_failure(t, _fail()) == "malformed_tool_call"


def test_hallucinated():
    t = _trace(
        steps=[
            Step(
                index=0,
                tool_call=_tc(name="nuke", hallucinated=True, error="hallucinated_tool: nuke"),
            )
        ]
    )
    assert classify_failure(t, _fail()) == "hallucinated_tool"


def test_hallucinated_via_allowed_list():
    t = _trace(steps=[Step(index=0, tool_call=_tc(name="nuke"))], allowed_tools=["calculator"])
    assert classify_failure(t, _fail()) == "hallucinated_tool"


def test_budget():
    t = _trace(terminated_by="max_steps")
    assert classify_failure(t, _fail()) == "budget_exhausted"


def test_wrong_answer():
    t = _trace(final_output="nope")
    assert classify_failure(t, _fail()) == "wrong_answer"


def test_no_answer():
    t = _trace(final_output="")
    assert classify_failure(t, _fail()) == "no_answer"


def test_refusal():
    t = _trace(final_output="I cannot do that. Please clarify.", task_category="tool_use")
    assert classify_failure(t, _fail()) == "refusal"


def test_harness_error():
    t = _trace(terminated_by="error", error="boom", final_output=None)
    assert classify_failure(t, _fail()) == "harness_error"


def test_priority_tool_error_beats_budget():
    t = _trace(
        terminated_by="max_steps",
        steps=[Step(index=0, tool_call=_tc(error="timeout"))],
    )
    assert classify_failure(t, _fail()) == "tool_error"


def test_priority_malformed_beats_hallucinated():
    t = _trace(
        steps=[
            Step(
                index=0,
                tool_call=_tc(
                    name="nuke", malformed=True, hallucinated=True, error="malformed_tool_call: x"
                ),
            )
        ]
    )
    assert classify_failure(t, _fail()) == "malformed_tool_call"
