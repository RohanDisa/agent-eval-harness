"""Suite plugin contract. The engine is domain-agnostic; a suite is a plugin."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from aeh.models import Task, Trace
from aeh.tools.registry import ToolRegistry


class InvariantResult(BaseModel):
    name: str
    passed: bool
    reason: str


InvariantFn = Callable[[Trace], InvariantResult]


@runtime_checkable
class EvalSuite(Protocol):
    name: str

    def tasks(self) -> list[Task]: ...

    def tool_registry(self) -> ToolRegistry: ...

    def invariants(self) -> dict[str, InvariantFn]: ...

    def golden_traces(self) -> dict[str, Trace]: ...
