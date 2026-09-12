import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aeh.metrics.aggregate import wilson_interval
from aeh.metrics.failure_taxonomy import classify_failure
from aeh.models import GradeResult, Trace

pytest.importorskip("hypothesis")


@given(n=st.integers(min_value=1, max_value=50), k_frac=st.floats(0, 1))
@settings(max_examples=40)
def test_wilson_bounds(n, k_frac):
    k = int(round(k_frac * n))
    k = min(n, max(0, k))
    point, lo, hi = wilson_interval(k, n)
    assert 0.0 <= lo <= hi <= 1.0
    assert lo <= point <= hi or (point in {0.0, 1.0})
    assert lo <= k / n <= hi or abs((k / n) - point) < 1e-12
    # Wilson always contains the MLE for n>=1
    assert lo - 1e-12 <= (k / n) <= hi + 1e-12


@given(
    terminated=st.sampled_from(["completed", "max_steps", "timeout", "budget", "error"]),
    output=st.sampled_from([None, "", "answer", "I cannot do that"]),
)
@settings(max_examples=30)
def test_classifier_is_total(terminated, output):
    trace = Trace(
        run_id="r",
        task_id="t",
        attempt=0,
        seed=0,
        adapter="m",
        model="m",
        terminated_by=terminated,
        wall_clock_ms=1,
        final_output=output,
        task_category="tool_use",
        allowed_tools=["calculator"],
    )
    grades = [GradeResult(grader="exact", passed=False, score=0.0, detail="x")]
    label = classify_failure(trace, grades)
    assert label in {
        "tool_error",
        "malformed_tool_call",
        "hallucinated_tool",
        "budget_exhausted",
        "wrong_answer",
        "no_answer",
        "refusal",
        "harness_error",
    }
