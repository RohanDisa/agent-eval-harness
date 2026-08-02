from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from aeh.execution.sandbox import Sandbox
from aeh.models import ToolResult


@runtime_checkable
class Tool(Protocol):
    name: str
    schema: dict[str, Any]

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult: ...
