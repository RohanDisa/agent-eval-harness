from __future__ import annotations

import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aeh.paths import REPO_ROOT
from aeh.tools.registry import ToolRegistry
from suites.customer_support.tools.broken import BrokenTool
from suites.customer_support.tools.calculator import Calculator
from suites.customer_support.tools.filesystem import FsList, FsRead, FsWrite
from suites.customer_support.tools.http import HttpGet
from suites.customer_support.tools.sql import SqlQuery


def default_registry(
    *,
    fixture_db: Path | None = None,
    fault_profile: Mapping[str, Any] | None = None,
    rng: random.Random | None = None,
    http_tool: HttpGet | None = None,
) -> ToolRegistry:
    db = fixture_db or (REPO_ROOT / "fixtures" / "sql" / "fixture.db")
    registry = ToolRegistry(fault_profile=fault_profile, rng=rng)
    registry.register(FsRead())
    registry.register(FsWrite())
    registry.register(FsList())
    registry.register(http_tool or HttpGet())
    registry.register(Calculator())
    registry.register(SqlQuery(db))
    registry.register(BrokenTool())
    return registry
