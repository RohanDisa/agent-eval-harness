from __future__ import annotations

from typing import Protocol, runtime_checkable

from aeh.execution.budget import Budget
from aeh.execution.sandbox import Sandbox
from aeh.models import Task, Trace


@runtime_checkable
class AgentAdapter(Protocol):
    name: str

    async def run(self, task: Task, sandbox: Sandbox, budget: Budget) -> Trace: ...
