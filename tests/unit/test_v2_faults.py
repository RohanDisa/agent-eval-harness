import random
from pathlib import Path

import pytest
from suites.customer_support.tools.calculator import Calculator

from aeh.execution.sandbox import Sandbox
from aeh.tools.faults import FaultController
from aeh.tools.registry import ToolRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "500", "garbage"])
async def test_error_kind_marked_on_tool_call(tmp_path: Path, kind: str):
    registry = ToolRegistry(
        {"calculator": Calculator()},
        fault_profile={"calculator": {"fail_rate": 1.0, "error_kind": kind}},
        rng=random.Random(0),
    )
    call = await registry.invoke(
        "calculator", {"expression": "1+1"}, Sandbox(tmp_path), 0, allowed=["calculator"]
    )
    assert call.injected_fault == kind
    if kind == "garbage":
        assert call.result and "GARBAGE" in call.result
        assert not call.error
    else:
        assert call.error and "injected" in call.error


def test_faults_reproducible_by_seed():
    a = FaultController({"t": {"fail_rate": 0.5, "error_kind": "timeout"}}, random.Random(7))
    b = FaultController({"t": {"fail_rate": 0.5, "error_kind": "timeout"}}, random.Random(7))
    seq_a = [a.decide("t") for _ in range(20)]
    seq_b = [b.decide("t") for _ in range(20)]
    assert seq_a == seq_b
    assert any(seq_a) and not all(seq_a)


@pytest.mark.asyncio
async def test_burst_fails_contiguous_window(tmp_path: Path):
    registry = ToolRegistry(
        {"calculator": Calculator()},
        fault_profile={"calculator": {"fail_rate": 1.0, "error_kind": "500", "burst": 3}},
        rng=random.Random(0),
    )
    box = Sandbox(tmp_path)
    flags = []
    for i in range(5):
        call = await registry.invoke(
            "calculator", {"expression": "1+1"}, box, i, allowed=["calculator"]
        )
        flags.append(call.injected_fault)
    assert flags[:3] == ["500", "500", "500"]
    assert flags[3:] == [None, None]
