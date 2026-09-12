from pathlib import Path

from aeh.models import GradeResult, RunResult, Step, ToolCall, Trace
from aeh.report.trace_tree import render_trace_tree


def test_trace_tree_is_offline_and_highlights_divergence(tmp_path: Path):
    trace = Trace(
        run_id="r1",
        task_id="toy-add",
        attempt=0,
        seed=0,
        adapter="mock",
        model="mock",
        steps=[
            Step(
                index=0,
                span_id="step-0",
                model_latency_ms=4.0,
                model_input_tokens=3,
                model_output_tokens=2,
                reasoning_text="add them",
                tool_call=ToolCall(
                    index=0,
                    name="calculator",
                    arguments={"expression": "1+1"},
                    result="2",
                    injected_fault="500",
                    span_id="tool-0",
                    parent_span_id="step-0",
                    error="injected fault 500",
                ),
            )
        ],
        final_output="2",
        terminated_by="completed",
        wall_clock_ms=5.0,
        task_category="tool_use",
    )
    trace.ensure_spans()
    result = RunResult(
        trace=trace,
        grades=[
            GradeResult(
                grader="golden_divergence",
                passed=True,
                score=0.8,
                detail='{"divergence_step": 0, "reason": "wrong sum", "confidence": 0.8}',
                tier=2,
            )
        ],
        success=False,
        failure_class="wrong_answer",
    )
    out = tmp_path / "trace.html"
    html = render_trace_tree(result, out)
    assert out.is_file()
    assert "<script src=" not in html
    assert "mermaid" not in html.lower()
    assert "classList.toggle" in html
    assert "diverge" in html
    assert "fault:500" in html or "injected_fault" in html
    assert "localStorage" not in html
    assert "<svg" in html
    assert "marker-end" in html
    assert "url(#arrow)" in html
