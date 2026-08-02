"""Baseline: one model call, no tools. If this wins, the suite is too easy."""

from __future__ import annotations

import time

from aeh.adapters.provider import ChatProvider, ProviderError
from aeh.errors import BudgetExceeded
from aeh.execution.budget import Budget
from aeh.execution.sandbox import Sandbox
from aeh.models import Step, Task, Trace

SYSTEM = (
    "You are a careful assistant. Answer the user directly. "
    "You do not have tools. If the task requires files, tools, or live data you "
    "cannot see, say so clearly rather than inventing an answer."
)


class SingleShotAdapter:
    name = "single_shot"

    def __init__(
        self,
        provider: ChatProvider,
        run_id: str = "run",
        attempt: int = 0,
        seed: int = 0,
    ) -> None:
        self.provider = provider
        self.run_id = run_id
        self.attempt = attempt
        self.seed = seed

    async def run(self, task: Task, sandbox: Sandbox, budget: Budget) -> Trace:
        _ = sandbox
        started = time.monotonic()
        steps: list[Step] = []
        final_output: str | None = None
        terminated_by = "completed"
        error: str | None = None
        try:
            budget.consume_step()
            t0 = time.monotonic()
            raw = await self.provider.chat(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": task.prompt},
                ]
            )
            latency_ms = (time.monotonic() - t0) * 1000.0
            usage = raw.get("usage") or {}
            inp = int(usage.get("prompt_tokens") or 0)
            out = int(usage.get("completion_tokens") or 0)
            budget.consume_tokens(inp + out)
            message = (raw.get("choices") or [{}])[0].get("message") or {}
            final_output = message.get("content")
            steps.append(
                Step(
                    index=0,
                    span_id="step-0",
                    model_input_tokens=inp,
                    model_output_tokens=out,
                    model_latency_ms=latency_ms,
                    reasoning_text=None,
                    raw_response=raw,
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
