"""Tier 2: localize divergence from one known-good trajectory. Never flips success."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from aeh.adapters.provider import ChatProvider, ProviderError
from aeh.models import GradeResult, Task, Trace

PROMPT_VERSION = "golden-divergence-v1"

SYSTEM = (
    "Here is a known-good trajectory and a failed one for the same task. "
    "Identify where the failed run's reasoning or decisions meaningfully diverged "
    "from a correct approach. Ignore differences in order of independent steps, "
    "phrasing, or tool sequencing that do not affect correctness. "
    "Name the earliest decision that put the run on a wrong path, and why. "
    'Reply with ONLY JSON: {"divergence_step": <int or null>, "reason": <str>, '
    '"confidence": <float 0-1>}.'
)


class DivergencePayload(BaseModel):
    divergence_step: int | None
    reason: str
    confidence: float


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _summarize(trace: Trace) -> str:
    lines = [f"terminated_by={trace.terminated_by} output={trace.final_output!r}"]
    for step in trace.steps:
        tc = step.tool_call
        if tc:
            lines.append(
                f"step {step.index}: tool {tc.name} args={tc.arguments} "
                f"err={tc.error} result={(tc.result or '')[:200]}"
            )
        else:
            lines.append(f"step {step.index}: say {(step.reasoning_text or '')[:200]}")
    return "\n".join(lines)


async def compare_to_golden(
    task: Task,
    failed: Trace,
    golden: Trace,
    provider: ChatProvider | None,
) -> GradeResult:
    if provider is None:
        return GradeResult(
            grader="golden_divergence",
            passed=True,
            score=0.0,
            detail="tier 2 skipped: no judge provider",
            errored=True,
            tier=2,
        )
    user = (
        f"Task: {task.prompt}\n\nKNOWN GOOD:\n{_summarize(golden)}\n\nFAILED:\n{_summarize(failed)}"
    )
    last = "parse failed"
    for _ in range(2):
        try:
            raw = await provider.chat(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user},
                ]
            )
        except ProviderError as exc:
            last = str(exc)
            continue
        content = ((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        try:
            payload = DivergencePayload.model_validate(_extract_json(content))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            last = f"invalid tier2 JSON: {exc}"
            continue
        conf = min(1.0, max(0.0, float(payload.confidence)))
        return GradeResult(
            grader="golden_divergence",
            passed=True,
            score=conf,
            detail=json.dumps(
                {
                    "divergence_step": payload.divergence_step,
                    "reason": payload.reason,
                    "confidence": conf,
                    "prompt_version": PROMPT_VERSION,
                }
            ),
            tier=2,
        )
    return GradeResult(
        grader="golden_divergence",
        passed=True,
        score=0.0,
        detail=last,
        errored=True,
        tier=2,
    )


def parse_divergence(grade: GradeResult) -> dict[str, Any] | None:
    if grade.tier != 2 or grade.errored:
        return None
    try:
        return json.loads(grade.detail)
    except json.JSONDecodeError:
        return None
