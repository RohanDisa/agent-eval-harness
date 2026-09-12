from pathlib import Path

import pytest
from suites.customer_support.tools.sql import SqlQuery

from aeh.execution.sandbox import Sandbox


@pytest.mark.asyncio
async def test_insert_fails(fixture_db: Path, tmp_path: Path):
    tool = SqlQuery(fixture_db)
    result = await tool.call(
        {"query": "INSERT INTO regions(id, name, continent) VALUES (99,'x','y')"}, Sandbox(tmp_path)
    )
    assert result.ok is False
    assert result.error


@pytest.mark.asyncio
async def test_select_works(fixture_db: Path, tmp_path: Path):
    tool = SqlQuery(fixture_db)
    result = await tool.call({"query": "SELECT COUNT(*) FROM customers"}, Sandbox(tmp_path))
    assert result.ok is True
    assert "5" in result.output
