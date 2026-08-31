from aeh.models import Trace
from aeh.suite.spec import InvariantResult


def calculator_only(trace: Trace) -> InvariantResult:
    others = [
        step.tool_call.name
        for step in trace.steps
        if step.tool_call and step.tool_call.name != "calculator"
    ]
    if others:
        return InvariantResult(
            name="calculator_only",
            passed=False,
            reason=f"non-calculator tools used: {others}",
        )
    return InvariantResult(name="calculator_only", passed=True, reason="only calculator was used")
