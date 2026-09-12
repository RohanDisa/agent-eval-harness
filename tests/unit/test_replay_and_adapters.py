from pathlib import Path

import pytest
from suites.customer_support.tools import default_registry

from aeh.adapters.provider import ChatProvider, ProviderError
from aeh.adapters.react import ReactAdapter
from aeh.adapters.replay import ReplayAdapter
from aeh.adapters.single_shot import SingleShotAdapter
from aeh.execution.budget import Budget
from aeh.execution.sandbox import Sandbox
from aeh.models import Step, Task, Trace


def _task() -> Task:
    return Task(
        id="echo-hello",
        suite="smoke",
        prompt="say hello",
        category="tool_use",
        difficulty=1,
        tools=["calculator"],
        graders=[{"type": "exact", "expected": "hello"}],
    )


def _trace() -> Trace:
    return Trace(
        run_id="orig",
        task_id="echo-hello",
        attempt=0,
        seed=1,
        adapter="react",
        model="gpt-4o-mini",
        steps=[
            Step(
                index=0,
                model_input_tokens=4,
                model_output_tokens=2,
                raw_response={"id": "x", "choices": []},
            )
        ],
        final_output="hello",
        terminated_by="completed",
        wall_clock_ms=12.0,
        allowed_tools=["calculator"],
        task_category="tool_use",
    )


@pytest.mark.asyncio
async def test_replay_zero_network_and_preserves_raw(tmp_path: Path):
    stored = _trace()
    adapter = ReplayAdapter({("echo-hello", 0): stored})
    replayed = await adapter.run(_task(), Sandbox(tmp_path), Budget(5, 1000, 5))
    assert replayed.steps[0].raw_response == stored.steps[0].raw_response
    assert replayed.final_output == "hello"
    assert replayed.adapter == "replay"


@pytest.mark.asyncio
async def test_replay_missing_trace(tmp_path: Path):
    adapter = ReplayAdapter({})
    replayed = await adapter.run(_task(), Sandbox(tmp_path), Budget(5, 1000, 5))
    assert replayed.terminated_by == "error"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    async def post(self, *args, **kwargs):
        return _Resp(self.payloads.pop(0))

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_single_shot(tmp_path: Path):
    client = _Client(
        [
            {
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }
        ]
    )
    adapter = SingleShotAdapter(ChatProvider("gpt-4o-mini", api_key="k", client=client))  # type: ignore[arg-type]
    trace = await adapter.run(_task(), Sandbox(tmp_path), Budget(3, 1000, 5))
    assert trace.final_output == "hello"
    assert trace.steps[0].raw_response["choices"]
    assert trace.terminated_by == "completed"


@pytest.mark.asyncio
async def test_react_tool_then_final(tmp_path: Path, fixture_db: Path):
    tool_resp = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "function": {
                                "name": "calculator",
                                "arguments": '{"expression": "1+1"}',
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5},
    }
    final_resp = {
        "choices": [{"message": {"content": "2"}}],
        "usage": {"prompt_tokens": 6, "completion_tokens": 1},
    }
    client = _Client([tool_resp, final_resp])
    registry = default_registry(fixture_db=fixture_db)
    adapter = ReactAdapter(ChatProvider("gpt-4o-mini", api_key="k", client=client), registry)  # type: ignore[arg-type]
    trace = await adapter.run(_task(), Sandbox(tmp_path), Budget(5, 5000, 5))
    assert trace.final_output == "2"
    assert trace.steps[0].tool_call is not None
    assert trace.steps[0].tool_call.name == "calculator"
    assert trace.steps[0].raw_response  # replayable


@pytest.mark.asyncio
async def test_react_malformed_args(tmp_path: Path, fixture_db: Path):
    bad = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"id": "1", "function": {"name": "calculator", "arguments": "not-json"}}
                    ]
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    done = {
        "choices": [{"message": {"content": "x"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    client = _Client([bad, done])
    adapter = ReactAdapter(
        ChatProvider("gpt-4o-mini", api_key="k", client=client),  # type: ignore[arg-type]
        default_registry(fixture_db=fixture_db),
    )
    trace = await adapter.run(_task(), Sandbox(tmp_path), Budget(5, 5000, 5))
    assert trace.steps[0].tool_call and trace.steps[0].tool_call.malformed


@pytest.mark.asyncio
async def test_provider_error():
    class Boom:
        async def post(self, *args, **kwargs):
            import httpx

            raise httpx.ConnectError("nope")

        async def aclose(self):
            return None

    provider = ChatProvider("gpt-4o-mini", api_key="k", client=Boom())  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        await provider.chat([{"role": "user", "content": "hi"}])
