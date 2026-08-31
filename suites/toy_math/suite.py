from __future__ import annotations

from pathlib import Path

from aeh.models import Step, Task, ToolCall, Trace
from aeh.paths import REPO_ROOT
from aeh.suite.spec import InvariantFn
from aeh.suite.yaml_tasks import load_yaml_dir
from aeh.tools.registry import ToolRegistry
from suites.toy_math.invariants import calculator_only
from suites.toy_math.tools.calculator import Calculator


class ToyMathSuite:
    name = "toy_math"

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.tasks_dir = Path(__file__).resolve().parent

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
        registry = ToolRegistry()
        registry.register(Calculator())
        return registry

    def invariants(self) -> dict[str, InvariantFn]:
        return {"calculator_only": calculator_only}

    def golden_traces(self) -> dict[str, Trace]:
        return {
            "toy-add": Trace(
                run_id="golden",
                task_id="toy-add",
                attempt=0,
                seed=0,
                adapter="mock",
                model="golden",
                steps=[
                    Step(
                        index=0,
                        span_id="step-0",
                        tool_call=ToolCall(
                            index=0,
                            name="calculator",
                            arguments={"expression": "19+23"},
                            result="42",
                            span_id="tool-0",
                            parent_span_id="step-0",
                        ),
                    )
                ],
                final_output="42",
                terminated_by="completed",
                wall_clock_ms=1.0,
                allowed_tools=["calculator"],
                task_category="tool_use",
            )
        }


def get_suite() -> ToyMathSuite:
    return ToyMathSuite()


suite = ToyMathSuite()
SUITE_CLASS = ToyMathSuite
