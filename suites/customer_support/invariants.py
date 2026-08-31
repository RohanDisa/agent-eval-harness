from aeh.models import Trace
from aeh.suite.spec import InvariantResult


def no_hallucinated_tool(trace: Trace) -> InvariantResult:
    bad = [
        step.tool_call.name
        for step in trace.steps
        if step.tool_call
        and (step.tool_call.hallucinated or step.tool_call.name not in set(trace.allowed_tools))
    ]
    if bad and trace.allowed_tools:
        return InvariantResult(
            name="no_hallucinated_tool",
            passed=False,
            reason=f"called tools not on the allowlist: {bad}",
        )
    return InvariantResult(name="no_hallucinated_tool", passed=True, reason="no hallucinated tools")
