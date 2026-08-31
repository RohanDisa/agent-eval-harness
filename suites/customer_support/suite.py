"""Plugin suite that owns the v1 workspace tools (fs, http, sql, calculator)."""

from __future__ import annotations

from pathlib import Path

from aeh.models import Task, Trace
from aeh.paths import REPO_ROOT
from aeh.suite.spec import InvariantFn
from aeh.suite.yaml_tasks import load_yaml_dir
from aeh.tools.registry import ToolRegistry
from suites.customer_support.invariants import no_hallucinated_tool
from suites.customer_support.tools import default_registry


class CustomerSupportSuite:
    name = "customer_support"

    def __init__(self, repo_root: Path | None = None, tasks_dir: Path | None = None) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.tasks_dir = tasks_dir or (self.repo_root / "suites" / "core")

    def tasks(self) -> list[Task]:
        registry = self.tool_registry()
        return load_yaml_dir(
            self.tasks_dir,
            repo_root=self.repo_root,
            known_tools=set(registry.names()),
            known_invariants=set(self.invariants()),
            golden_ids=set(self.golden_traces()),
        )

    def tool_registry(self) -> ToolRegistry:
        return default_registry(fixture_db=self.repo_root / "fixtures" / "sql" / "fixture.db")

    def invariants(self) -> dict[str, InvariantFn]:
        return {"no_hallucinated_tool": no_hallucinated_tool}

    def golden_traces(self) -> dict[str, Trace]:
        return {}


def get_suite() -> CustomerSupportSuite:
    return CustomerSupportSuite()


suite = CustomerSupportSuite()
SUITE_CLASS = CustomerSupportSuite
