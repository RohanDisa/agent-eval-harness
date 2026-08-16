"""LLM-as-judge. Parse strict JSON, retry once, then mark errored — never silently pass."""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from aeh.adapters.provider import ChatProvider, ProviderError
from aeh.grading.base import spec_data
from aeh.models import GradeResult, GraderSpec, Task, Trace

JUDGE_SYSTEM = (
    "You grade an agent's attempt against a rubric. "
    "Reply with ONLY a JSON object: "
    '{"passed": <bool>, "score": <float 0-1>, "reason": <string>}. '
    "No markdown."
)


class JudgePayload(BaseModel):
    passed: bool
    score: float
    reason: str


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


class JudgeGrader:
    name = "judge"

    def __init__(self, provider: ChatProvider | None = None) -> None:
        self.provider = provider

    async def grade_async(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        data = spec_data(spec)
        rubric = str(data.get("rubric", ""))
        started = time.perf_counter()
        if self.provider is None:
            return GradeResult(
                grader=self.name,
                passed=False,
                score=0.0,
                detail="judge provider not configured",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                errored=True,
            )
        user = (
            f"Task prompt:\n{task.prompt}\n\n"
            f"Rubric:\n{rubric}\n\n"
            f"Final output:\n{trace.final_output!r}\n\n"
            f"Terminated by: {trace.terminated_by}\n"
        )
        last_error = "parse failed"
        for _attempt in range(2):
            try:
                raw = await self.provider.chat(
                    [
                        {"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": user},
                    ]
                )
            except ProviderError as exc:
                last_error = str(exc)
                continue
            content = ((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            usage = raw.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            try:
                payload = JudgePayload.model_validate(_extract_json(content))
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                last_error = f"invalid judge JSON: {exc}"
                continue
            score = min(1.0, max(0.0, float(payload.score)))
            return GradeResult(
                grader=self.name,
                passed=payload.passed,
                score=score,
                detail=payload.reason,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                cost_usd=0.0,
            )
        _ = tokens_in, tokens_out
        return GradeResult(
            grader=self.name,
            passed=False,
            score=0.0,
            detail=last_error,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            errored=True,
        )

    def grade(self, spec: GraderSpec, trace: Trace, task: Task) -> GradeResult:
        """Sync shim used when no event loop is running the async path."""
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.grade_async(spec, trace, task))
        return GradeResult(
            grader=self.name,
            passed=False,
            score=0.0,
            detail="judge.grade() called from a running loop; use grade_async",
            errored=True,
        )
