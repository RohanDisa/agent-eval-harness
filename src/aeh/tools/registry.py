from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Mapping
from typing import Any

from aeh.execution.sandbox import Sandbox
from aeh.models import ToolCall
from aeh.tools.base import Tool
from aeh.tools.faults import FaultController

FaultSpec = dict[str, Any]


class ToolRegistry:
    def __init__(
        self,
        tools: Mapping[str, Tool] | None = None,
        fault_profile: Mapping[str, FaultSpec] | None = None,
        rng: random.Random | None = None,
        call_timeout_s: float = 10.0,
    ) -> None:
        self._tools: dict[str, Tool] = dict(tools or {})
        self.rng = rng or random.Random()
        self.call_timeout_s = call_timeout_s
        self._faults = FaultController(fault_profile, self.rng)

    @property
    def fault_profile(self) -> dict[str, Any]:
        return self._faults.profile

    @fault_profile.setter
    def fault_profile(self, value: Mapping[str, Any]) -> None:
        self._faults = FaultController(value, self.rng)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas_for(self, names: list[str]) -> list[dict[str, Any]]:
        return [self._tools[name].schema for name in names if name in self._tools]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def _call(
        self,
        *,
        index: int,
        name: str,
        args: dict[str, Any],
        started: float,
        started_at,
        span_id: str,
        error: str | None = None,
        result: str | None = None,
        hallucinated: bool = False,
        malformed: bool = False,
        injected_fault: str | None = None,
    ) -> ToolCall:
        return ToolCall(
            index=index,
            name=name,
            arguments=args,
            result=result,
            error=error,
            latency_ms=(time.time() - started) * 1000.0,
            started_at=started_at,
            hallucinated=hallucinated,
            malformed=malformed,
            span_id=span_id,
            injected_fault=injected_fault,
        )

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        sandbox: Sandbox,
        index: int,
        allowed: list[str] | None = None,
        parent_span_id: str | None = None,
    ) -> ToolCall:
        started = time.time()
        started_at = __import__("datetime").datetime.utcnow()
        span_id = uuid.uuid4().hex[:12]
        if allowed is not None and name not in allowed:
            call = self._call(
                index=index,
                name=name,
                args=args,
                started=started,
                started_at=started_at,
                span_id=span_id,
                error=f"hallucinated_tool: '{name}' is not in task.tools",
                hallucinated=True,
            )
            call.parent_span_id = parent_span_id
            return call
        tool = self._tools.get(name)
        if tool is None:
            call = self._call(
                index=index,
                name=name,
                args=args,
                started=started,
                started_at=started_at,
                span_id=span_id,
                error=f"hallucinated_tool: unknown tool '{name}'",
                hallucinated=True,
            )
            call.parent_span_id = parent_span_id
            return call
        extra = self._faults.extra_latency_ms(name)
        if extra:
            await asyncio.sleep(extra / 1000.0)
        kind = self._faults.decide(name)
        if kind:
            err, garbage = self._faults.apply_kind(kind, name)
            if kind == "timeout":
                call = self._call(
                    index=index,
                    name=name,
                    args=args,
                    started=started,
                    started_at=started_at,
                    span_id=span_id,
                    error=err,
                    injected_fault=kind,
                )
            elif kind == "garbage":
                call = self._call(
                    index=index,
                    name=name,
                    args=args,
                    started=started,
                    started_at=started_at,
                    span_id=span_id,
                    result=garbage,
                    injected_fault=kind,
                )
            else:
                call = self._call(
                    index=index,
                    name=name,
                    args=args,
                    started=started,
                    started_at=started_at,
                    span_id=span_id,
                    error=err,
                    injected_fault=kind,
                )
            call.parent_span_id = parent_span_id
            return call
        try:
            result = await asyncio.wait_for(tool.call(args, sandbox), timeout=self.call_timeout_s)
        except TimeoutError:
            call = self._call(
                index=index,
                name=name,
                args=args,
                started=started,
                started_at=started_at,
                span_id=span_id,
                error=f"tool '{name}' timed out after {self.call_timeout_s}s",
            )
            call.parent_span_id = parent_span_id
            return call
        except Exception as exc:  # noqa: BLE001
            call = self._call(
                index=index,
                name=name,
                args=args,
                started=started,
                started_at=started_at,
                span_id=span_id,
                error=str(exc),
            )
            call.parent_span_id = parent_span_id
            return call
        call = self._call(
            index=index,
            name=name,
            args=args,
            started=started,
            started_at=started_at,
            span_id=span_id,
            result=result.output if result.ok else None,
            error=None if result.ok else (result.error or "tool failed"),
        )
        call.parent_span_id = parent_span_id
        return call
