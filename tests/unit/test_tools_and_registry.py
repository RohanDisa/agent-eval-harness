from pathlib import Path

import pytest
from suites.customer_support.tools import default_registry
from suites.customer_support.tools.calculator import Calculator
from suites.customer_support.tools.filesystem import FsList, FsRead, FsWrite

from aeh.execution.sandbox import Sandbox
from aeh.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_fs_tools_and_escape(tmp_path: Path):
    box = Sandbox(tmp_path)
    write = FsWrite()
    read = FsRead()
    listing = FsList()
    ok = await write.call({"path": "a.txt", "content": "hi"}, box)
    assert ok.ok
    got = await read.call({"path": "a.txt"}, box)
    assert got.output == "hi"
    listed = await listing.call({"path": "."}, box)
    assert "a.txt" in listed.output
    denied = await read.call({"path": "../../etc/passwd"}, box)
    assert denied.ok is False


@pytest.mark.asyncio
async def test_calculator():
    calc = Calculator()
    box = Sandbox()
    try:
        result = await calc.call({"expression": "(2+3)*4"}, box)
        assert result.ok and result.output == "20"
        bad = await calc.call({"expression": "__import__('os')"}, box)
        assert bad.ok is False
    finally:
        box.cleanup()


@pytest.mark.asyncio
async def test_fault_injection_always_fails(tmp_path: Path, fixture_db: Path):
    rng = __import__("random").Random(0)
    registry = default_registry(
        fixture_db=fixture_db,
        fault_profile={"calculator": {"fail_rate": 1.0, "latency_ms": 1}},
        rng=rng,
    )
    call = await registry.invoke(
        "calculator", {"expression": "1+1"}, Sandbox(tmp_path), index=0, allowed=["calculator"]
    )
    assert call.error and "injected" in call.error


@pytest.mark.asyncio
async def test_hallucinated_tool(tmp_path: Path, fixture_db: Path):
    registry = default_registry(fixture_db=fixture_db)
    call = await registry.invoke("nuke", {}, Sandbox(tmp_path), index=0, allowed=["calculator"])
    assert call.hallucinated


@pytest.mark.asyncio
async def test_tool_timeout(tmp_path: Path):
    class Slow:
        name = "slow"
        schema = {"name": "slow", "parameters": {"type": "object", "properties": {}}}

        async def call(self, args, sandbox):
            import asyncio

            await asyncio.sleep(1)
            from aeh.models import ToolResult

            return ToolResult(ok=True, output="late")

    registry = ToolRegistry({"slow": Slow()}, call_timeout_s=0.01)
    call = await registry.invoke("slow", {}, Sandbox(tmp_path), 0, allowed=["slow"])
    assert call.error and "timed out" in call.error
