import json

import pytest

from aeh.adapters.provider import ChatProvider
from aeh.grading.judge import JudgeGrader
from aeh.models import GraderSpec, Task, Trace


class FakeClient:
    def __init__(self, payloads: list[object]):
        self.payloads = list(payloads)
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        payload = self.payloads.pop(0)

        class Resp:
            def raise_for_status(self_inner):
                return None

            def json(self_inner):
                if isinstance(payload, Exception):
                    raise payload
                return payload

        return Resp()

    async def aclose(self):
        return None


def _task() -> Task:
    return Task(
        id="t",
        suite="s",
        prompt="say hi",
        category="refusal",
        difficulty=1,
        tools=[],
        graders=[GraderSpec(type="judge", rubric="be nice")],
    )


def _trace() -> Trace:
    return Trace(
        run_id="r",
        task_id="t",
        attempt=0,
        seed=0,
        adapter="mock",
        model="m",
        terminated_by="completed",
        wall_clock_ms=1,
        final_output="hello",
    )


def _completion(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


@pytest.mark.asyncio
async def test_judge_parses_valid_json():
    client = FakeClient([_completion(json.dumps({"passed": True, "score": 0.9, "reason": "ok"}))])
    provider = ChatProvider("gpt-4o-mini", api_key="x", client=client)  # type: ignore[arg-type]
    grade = await JudgeGrader(provider).grade_async(
        GraderSpec(type="judge", rubric="r"), _trace(), _task()
    )
    assert grade.passed and not grade.errored
    assert grade.score == 0.9


@pytest.mark.asyncio
async def test_judge_retries_then_errors():
    client = FakeClient([_completion("not-json"), _completion("still-bad")])
    provider = ChatProvider("gpt-4o-mini", api_key="x", client=client)  # type: ignore[arg-type]
    grade = await JudgeGrader(provider).grade_async(
        GraderSpec(type="judge", rubric="r"), _trace(), _task()
    )
    assert grade.errored
    assert grade.passed is False
    assert client.calls == 2


@pytest.mark.asyncio
async def test_judge_retry_recovers():
    client = FakeClient(
        [
            _completion("nope"),
            _completion(json.dumps({"passed": False, "score": 0.1, "reason": "x"})),
        ]
    )
    provider = ChatProvider("gpt-4o-mini", api_key="x", client=client)  # type: ignore[arg-type]
    grade = await JudgeGrader(provider).grade_async(
        GraderSpec(type="judge", rubric="r"), _trace(), _task()
    )
    assert not grade.errored
    assert grade.passed is False


@pytest.mark.asyncio
async def test_judge_without_provider_errors():
    grade = await JudgeGrader(None).grade_async(
        GraderSpec(type="judge", rubric="r"), _trace(), _task()
    )
    assert grade.errored
