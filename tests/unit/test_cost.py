from aeh.metrics.cost import PRICE_TABLE_VERSION, estimate_cost, prices_for, tokens_from_trace
from aeh.models import Step, Trace


def test_gpt4o_mini_known_tokens():
    # 1M in + 1M out → 0.15 + 0.60 = 0.75
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == 0.75
    # 2000 in, 500 out: 0.0003 + 0.0003 = 0.0006
    assert abs(estimate_cost("gpt-4o-mini", 2000, 500) - 0.0006) < 1e-12


def test_unknown_model_falls_back():
    assert prices_for("not-a-model") == prices_for("gpt-4o-mini")


def test_mock_is_free():
    assert estimate_cost("mock", 10_000, 10_000) == 0.0


def test_price_table_is_versioned():
    assert PRICE_TABLE_VERSION


def test_tokens_from_trace():
    trace = Trace(
        run_id="r",
        task_id="t",
        attempt=0,
        seed=0,
        adapter="x",
        model="m",
        steps=[
            Step(index=0, model_input_tokens=10, model_output_tokens=5),
            Step(index=1, model_input_tokens=3, model_output_tokens=2),
        ],
        terminated_by="completed",
        wall_clock_ms=1,
    )
    assert tokens_from_trace(trace) == (13, 7, 20)
