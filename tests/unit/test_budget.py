import asyncio

import pytest

from aeh.adapters.mock import MockAdapter
from aeh.errors import BudgetExceeded
from aeh.execution.budget import Budget
from aeh.execution.sandbox import Sandbox
from aeh.models import Task
from aeh.tasks.registry import KNOWN_TOOLS


def _task(**kwargs) -> Task:
    data = dict(
        id="t",
        suite="s",
        prompt="p",
        category="tool_use",
        difficulty=1,
        tools=["calculator"],
        graders=[{"type": "exact", "expected": "x"}],
        max_steps=2,
        max_tokens=20,
        timeout_s=1,
    )
    data.update(kwargs)
    return Task(**data)


def test_step_ceiling_sets_reason():
    b = Budget(max_steps=1, max_tokens=1000, timeout_s=10)
    b.consume_step()
    with pytest.raises(BudgetExceeded) as exc:
        b.consume_step()
    assert exc.value.reason == "max_steps"


def test_token_ceiling_sets_reason():
    b = Budget(max_steps=10, max_tokens=5, timeout_s=10)
    with pytest.raises(BudgetExceeded) as exc:
        b.consume_tokens(6)
    assert exc.value.reason == "budget"


@pytest.mark.asyncio
async def test_timeout_sets_reason(tmp_path):
    b = Budget(max_steps=10, max_tokens=1000, timeout_s=0.0)
    assert b.exceeded() == "timeout"


@pytest.mark.asyncio
async def test_mock_hits_max_steps(tmp_path):
    adapter = MockAdapter(
        scripts={"t": [{"final": "a"}, {"final": "b"}, {"final": "c"}]},
        run_id="r",
    )
    budget = Budget(max_steps=2, max_tokens=10_000, timeout_s=5)
    trace = await adapter.run(_task(), Sandbox(tmp_path), budget)
    assert trace.terminated_by == "max_steps"


@pytest.mark.asyncio
async def test_mock_hits_token_budget(tmp_path):
    adapter = MockAdapter(
        scripts={"t": [{"tokens": 50, "final": "a"}]},
        run_id="r",
    )
    budget = Budget(max_steps=5, max_tokens=10, timeout_s=5)
    trace = await adapter.run(_task(), Sandbox(tmp_path), budget)
    assert trace.terminated_by == "budget"


def test_known_tools_include_broken():
    assert "broken_tool" in KNOWN_TOOLS


@pytest.mark.asyncio
async def test_wait_for_timeout_helper():
    async def sleepy():
        await asyncio.sleep(0.2)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(sleepy(), timeout=0.01)
