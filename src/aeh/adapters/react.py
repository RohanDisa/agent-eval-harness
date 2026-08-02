"""Plain thought / action / observation loop with provider function calling."""

from __future__ import annotations

import json
import time
from typing import Any

from aeh.adapters.provider import ChatProvider, ProviderError
from aeh.errors import BudgetExceeded
from aeh.execution.budget import Budget
from aeh.execution.sandbox import Sandbox
from aeh.models import Step, Task, Trace
from aeh.tools.registry import ToolRegistry

SYSTEM = (
    "You are an agent that solves tasks using the provided tools. "
    "Think briefly, call tools when needed, and finish with a concise final answer. "
    "Do not call tools that were not provided. If a tool fails, recover or stop. "
    "If the request is disallowed, unclear, or would cause harm, decline and ask "
    "for clarification instead of guessing."
)


class ReactAdapter:
    name = "react"

    def __init__(
        self,
        provider: ChatProvider,
        registry: ToolRegistry,
        run_id: str = "run",
        attempt: int = 0,
        seed: int = 0,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.run_id = run_id
        self.attempt = attempt
        self.seed = seed

    async def run(self, task: Task, sandbox: Sandbox, budget: Budget) -> Trace:
        started = time.monotonic()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": task.prompt},
        ]
        tools = self.registry.schemas_for(task.tools)
        steps: list[Step] = []
        final_output: str | None = None
        terminated_by = "completed"
        error: str | None = None
        try:
            while True:
                if budget.would_exceed_step():
                    terminated_by = "max_steps"
                    break
                if budget.would_exceed_tokens():
                    terminated_by = "budget"
                    break
                if budget.remaining_timeout() <= 0:
                    terminated_by = "timeout"
                    break
                budget.consume_step()
                t0 = time.monotonic()
                raw = await self.provider.chat(messages, tools=tools or None)
                latency_ms = (time.monotonic() - t0) * 1000.0
                usage = raw.get("usage") or {}
                inp = int(usage.get("prompt_tokens") or 0)
                out = int(usage.get("completion_tokens") or 0)
                budget.consume_tokens(inp + out)
                message = (raw.get("choices") or [{}])[0].get("message") or {}
                messages.append(message)
                tool_calls = message.get("tool_calls") or []
                turn_span = f"turn-{len(steps)}"
                if not tool_calls:
                    final_output = message.get("content")
                    steps.append(
                        Step(
                            index=len(steps),
                            span_id=turn_span,
                            model_input_tokens=inp,
                            model_output_tokens=out,
                            model_latency_ms=latency_ms,
                            reasoning_text=message.get("content"),
                            raw_response=raw,
                        )
                    )
                    break
                # One recorded step per tool call so traces stay replayable.
                for i, call in enumerate(tool_calls):
                    fn = call.get("function") or {}
                    name = str(fn.get("name") or "")
                    raw_args = fn.get("arguments") or "{}"
                    malformed = False
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                        if not isinstance(args, dict):
                            raise ValueError("arguments must be an object")
                    except (json.JSONDecodeError, ValueError, TypeError) as exc:
                        args = {"_raw": raw_args}
                        malformed = True
                        tool_call = await self._malformed(name, args, len(steps), str(exc))
                    else:
                        tool_call = await self.registry.invoke(
                            name,
                            args,
                            sandbox,
                            index=len(steps),
                            allowed=task.tools,
                            parent_span_id=turn_span,
                        )
                    if malformed:
                        tool_call.malformed = True
                        if not tool_call.error:
                            tool_call.error = "malformed_tool_call: arguments failed validation"
                    observation = tool_call.error or tool_call.result or ""
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") or f"call_{len(steps)}",
                            "content": observation,
                        }
                    )
                    steps.append(
                        Step(
                            index=len(steps),
                            span_id=f"{turn_span}-s{i}",
                            parent_span_id=turn_span,
                            model_input_tokens=inp if i == 0 else 0,
                            model_output_tokens=out if i == 0 else 0,
                            model_latency_ms=latency_ms if i == 0 else 0.0,
                            reasoning_text=message.get("content"),
                            tool_call=tool_call,
                            raw_response=raw
                            if i == 0
                            else {"shared_with_step": steps[-1].index if steps else 0},
                        )
                    )
        except BudgetExceeded as exc:
            terminated_by = exc.reason
        except ProviderError as exc:
            terminated_by = "error"
            error = str(exc)
        except Exception as exc:  # recorded
            terminated_by = "error"
            error = str(exc)
        return Trace(
            run_id=self.run_id,
            task_id=task.id,
            attempt=self.attempt,
            seed=self.seed,
            adapter=self.name,
            model=self.provider.model,
            steps=steps,
            final_output=final_output,
            terminated_by=terminated_by,  # type: ignore[arg-type]
            wall_clock_ms=(time.monotonic() - started) * 1000.0,
            error=error,
            allowed_tools=list(task.tools),
            task_category=task.category,
        )

    async def _malformed(self, name: str, args: dict[str, Any], index: int, detail: str):
        from datetime import datetime

        from aeh.models import ToolCall

        return ToolCall(
            index=index,
            name=name,
            arguments=args,
            error=f"malformed_tool_call: {detail}",
            latency_ms=0.0,
            started_at=datetime.utcnow(),
            malformed=True,
        )
