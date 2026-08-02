"""Re-emit a recorded trace. Zero network calls."""

from __future__ import annotations

from aeh.execution.budget import Budget
from aeh.execution.sandbox import Sandbox
from aeh.models import Task, Trace


class ReplayAdapter:
    name = "replay"

    def __init__(self, traces: dict[tuple[str, int], Trace] | None = None) -> None:
        self.traces = traces or {}
        self.model = "replay"

    def add(self, trace: Trace) -> None:
        self.traces[(trace.task_id, trace.attempt)] = trace

    async def run(self, task: Task, sandbox: Sandbox, budget: Budget) -> Trace:
        _ = sandbox, budget
        key = (task.id, 0)
        # Prefer exact attempt if the runner stamped it onto the adapter.
        for candidate in self.traces:
            if candidate[0] == task.id:
                key = candidate
                break
        stored = self.traces.get(key)
        if stored is None:
            return Trace(
                run_id="missing",
                task_id=task.id,
                attempt=0,
                seed=0,
                adapter=self.name,
                model=self.model,
                steps=[],
                final_output=None,
                terminated_by="error",
                wall_clock_ms=0.0,
                error=f"no recorded trace for task {task.id}",
                allowed_tools=list(task.tools),
                task_category=task.category,
            )
        replayed = stored.model_copy(deep=True)
        replayed.adapter = self.name
        return replayed
