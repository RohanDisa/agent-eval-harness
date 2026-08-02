"""Scripted adapter for tests. Never talks to a network."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from aeh.execution.budget import Budget
from aeh.execution.sandbox import Sandbox
from aeh.models import Step, Task, ToolCall, Trace
from aeh.tools.registry import ToolRegistry

ScriptedStep = dict[str, Any]
ScriptFn = Callable[[Task, Sandbox, Budget], Trace]


class MockAdapter:
    name = "mock"

    def __init__(
        self,
        scripts: Mapping[str, list[ScriptedStep]] | None = None,
        registry: ToolRegistry | None = None,
        model: str = "mock",
        run_id: str = "run",
        attempt: int = 0,
        seed: int = 0,
        auto_satisfy: bool = False,
    ) -> None:
        self.scripts = dict(scripts or {})
        self.registry = registry
        self.model = model
        self.run_id = run_id
        self.attempt = attempt
        self.seed = seed
        self.auto_satisfy = auto_satisfy

    async def run(self, task: Task, sandbox: Sandbox, budget: Budget) -> Trace:
        script = self.scripts.get(task.id)
        if script is not None:
            return await self._play(task, sandbox, budget, script)
        if self.auto_satisfy:
            return await self._satisfy(task, sandbox, budget)
        return Trace(
            run_id=self.run_id,
            task_id=task.id,
            attempt=self.attempt,
            seed=self.seed,
            adapter=self.name,
            model=self.model,
            steps=[],
            final_output="mock-complete",
            terminated_by="completed",
            wall_clock_ms=budget.elapsed_ms(),
            allowed_tools=list(task.tools),
            task_category=task.category,
        )

    async def _play(
        self, task: Task, sandbox: Sandbox, budget: Budget, script: list[ScriptedStep]
    ) -> Trace:
        steps: list[Step] = []
        final_output: str | None = None
        terminated_by = "completed"
        error: str | None = None
        try:
            for raw in script:
                if budget.would_exceed_step():
                    terminated_by = "max_steps"
                    break
                budget.consume_step()
                tokens = int(raw.get("tokens", 10))
                budget.consume_tokens(tokens)
                tool_call = None
                step_span = f"step-{len(steps)}"
                if "tool" in raw and self.registry is not None:
                    tool_call = await self.registry.invoke(
                        raw["tool"],
                        dict(raw.get("arguments") or {}),
                        sandbox,
                        index=len(steps),
                        allowed=task.tools,
                        parent_span_id=step_span,
                    )
                elif "tool" in raw:
                    tool_call = ToolCall(
                        index=len(steps),
                        name=raw["tool"],
                        arguments=dict(raw.get("arguments") or {}),
                        result=str(raw.get("result", "")),
                        latency_ms=0.0,
                    )
                if "write" in raw:
                    sandbox.write_text(raw["write"]["path"], raw["write"]["content"])
                if "final" in raw:
                    final_output = str(raw["final"])
                steps.append(
                    Step(
                        index=len(steps),
                        model_input_tokens=tokens // 2,
                        model_output_tokens=tokens - tokens // 2,
                        model_latency_ms=float(raw.get("latency_ms", 1.0)),
                        reasoning_text=raw.get("reasoning"),
                        tool_call=tool_call,
                        raw_response={"scripted": True, "payload": raw},
                        span_id=step_span,
                    )
                )
        except Exception as exc:  # recorded
            from aeh.errors import BudgetExceeded

            if isinstance(exc, BudgetExceeded):
                terminated_by = exc.reason
            else:
                terminated_by = "error"
                error = str(exc)
        return Trace(
            run_id=self.run_id,
            task_id=task.id,
            attempt=self.attempt,
            seed=self.seed,
            adapter=self.name,
            model=self.model,
            steps=steps,
            final_output=final_output,
            terminated_by=terminated_by,  # type: ignore[arg-type]
            wall_clock_ms=budget.elapsed_ms(),
            error=error,
            allowed_tools=list(task.tools),
            task_category=task.category,
        )

    async def _satisfy(self, task: Task, sandbox: Sandbox, budget: Budget) -> Trace:
        """Best-effort satisfaction of programmatic graders so the harness can be tested."""
        final_output = "ok"
        file_contents: dict[str, str] = {}
        tool_calls: list[dict[str, Any]] = []
        for spec in task.graders:
            data = spec.model_dump()
            kind = data.get("type")
            if kind == "exact":
                final_output = str(data.get("expected", final_output))
            elif kind == "contains":
                needle = str(data.get("needle", final_output))
                if data.get("regex"):
                    if task.category == "refusal":
                        final_output = "I cannot do that. Please clarify a legitimate request."
                    else:
                        final_output = needle
                else:
                    final_output = needle
            elif kind == "numeric_close":
                final_output = str(data.get("expected", final_output))
            elif kind == "json_schema":
                final_output = json.dumps(_instance_for_schema(data.get("schema") or {}))
            elif kind == "file_state":
                path = str(data.get("path"))
                expected = data.get("expected", "ok")
                matcher = data.get("matcher", "exact")
                current = file_contents.get(path, "")
                if matcher == "numeric_close":
                    file_contents[path] = str(expected)
                elif matcher == "hash":
                    file_contents[path] = current or "placeholder"
                elif matcher == "not_contains":
                    file_contents[path] = current or "ok"
                elif matcher == "contains":
                    piece = str(expected)
                    file_contents[path] = (current + "\n" + piece).strip()
                elif matcher == "regex":
                    file_contents[path] = current or "item-1\nitem-12"
                else:
                    file_contents[path] = str(expected)
            elif kind == "tool_sequence":
                for name in data.get("required") or []:
                    tool_calls.append({"tool": name, "arguments": {}})
            elif kind == "judge" and task.category == "refusal":
                final_output = "I must decline this request and ask for clarification."
        if task.category == "refusal" and not any(g.type == "exact" for g in task.graders):
            final_output = "I cannot do that. Please clarify a legitimate request."

        script: list[ScriptedStep] = []
        for name_args in tool_calls:
            script.append(name_args)
        for path, content in file_contents.items():
            script.append(
                {
                    "write": {"path": path, "content": content},
                    "tool": "fs_write",
                    "arguments": {"path": path, "content": content},
                }
            )
        script.append({"final": final_output})
        return await self._play(task, sandbox, budget, script)


def _instance_for_schema(schema: dict[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    t = schema.get("type", "object")
    if t == "object":
        props = schema.get("properties") or {}
        required = schema.get("required") or list(props)
        return {key: _instance_for_schema(props.get(key, {})) for key in required}
    if t == "array":
        return [_instance_for_schema(schema.get("items") or {})]
    if t == "string":
        return schema.get("examples", ["ok"])[0] if schema.get("examples") else "ok"
    if t == "number" or t == "integer":
        return schema.get("minimum", 0)
    if t == "boolean":
        return True
    return None
