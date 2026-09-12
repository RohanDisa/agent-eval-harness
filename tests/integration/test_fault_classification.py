from pathlib import Path

import pytest
from suites.customer_support.tools import default_registry

from aeh.adapters.mock import MockAdapter
from aeh.execution.budget import Budget
from aeh.execution.runner import build_graders, success_from_grades
from aeh.execution.sandbox import Sandbox
from aeh.grading.base import run_graders
from aeh.metrics.failure_taxonomy import classify_failure
from aeh.models import Task


@pytest.mark.asyncio
async def test_100_percent_fault_is_tool_error(fixture_db: Path, tmp_path: Path):
    task = Task(
        id="boom",
        suite="s",
        prompt="add",
        category="tool_use",
        difficulty=1,
        tools=["calculator"],
        graders=[{"type": "numeric_close", "expected": 42, "tolerance": 0.1}],
    )
    rng = __import__("random").Random(0)
    registry = default_registry(
        fixture_db=fixture_db,
        fault_profile={"calculator": {"fail_rate": 1.0}},
        rng=rng,
    )
    adapter = MockAdapter(
        scripts={"boom": [{"tool": "calculator", "arguments": {"expression": "1+1"}}]},
        registry=registry,
        auto_satisfy=False,
    )
    trace = await adapter.run(task, Sandbox(tmp_path), Budget(5, 1000, 5))
    grades = run_graders(build_graders(fixture_db), task, trace)
    assert success_from_grades(grades) is False
    assert classify_failure(trace, grades) == "tool_error"
