"""Pure function of Trace + grades. Priority order is the contract; tests lock it."""

from __future__ import annotations

import re

from aeh.models import FailureClass, GradeResult, Trace

_REFUSAL_PATTERNS = [
    r"\bi (can't|cannot|won't|will not|must decline|am unable|i'm unable)\b",
    r"\bi need (more )?(clarification|information)\b",
    r"\bplease clarify\b",
    r"\bi must refuse\b",
    r"\bnot able to (help|assist|do that)\b",
]


def classify_failure(trace: Trace, grades: list[GradeResult]) -> FailureClass | None:
    programmatic = [g for g in grades if g.grader != "judge"]
    success = (
        all(g.passed for g in programmatic)
        if programmatic
        else all(g.passed for g in grades if not g.errored)
    )
    if success and not any(g.errored for g in grades if g.grader != "judge"):
        return None

    tool_calls = [s.tool_call for s in trace.steps if s.tool_call]

    # 1. tool_error — a tool failed and the agent did not recover
    if any(tc.error and not tc.malformed and not tc.hallucinated for tc in tool_calls):
        return "tool_error"

    # 2. malformed_tool_call
    if any(tc.malformed or (tc.error or "").startswith("malformed_tool_call") for tc in tool_calls):
        return "malformed_tool_call"

    # 3. hallucinated_tool
    if any(
        tc.hallucinated or (tc.error or "").startswith("hallucinated_tool") for tc in tool_calls
    ):
        return "hallucinated_tool"
    allowed = set(trace.allowed_tools)
    if allowed and any(tc.name not in allowed for tc in tool_calls):
        return "hallucinated_tool"

    # 4. budget_exhausted
    if trace.terminated_by in {"max_steps", "timeout", "budget"}:
        return "budget_exhausted"

    # 5. wrong_answer — completed with non-empty output, graders failed
    output = (trace.final_output or "").strip()
    if trace.terminated_by == "completed" and output and not _looks_like_refusal(output):
        return "wrong_answer"

    # 6. no_answer
    if trace.terminated_by == "completed" and not output:
        return "no_answer"

    # 7. refusal — declined a task it should have done
    if _looks_like_refusal(output) and trace.task_category != "refusal":
        return "refusal"

    # 8. harness_error
    if trace.terminated_by == "error" or trace.error or any(g.errored for g in grades):
        return "harness_error"

    return "harness_error"


def _looks_like_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pat, lowered) for pat in _REFUSAL_PATTERNS)
