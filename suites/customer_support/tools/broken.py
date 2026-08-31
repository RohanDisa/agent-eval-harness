from __future__ import annotations

from typing import Any

from aeh.execution.sandbox import Sandbox
from aeh.models import ToolResult


class BrokenTool:
    name = "broken_tool"
    schema: dict[str, Any] = {
        "name": "broken_tool",
        "description": "Deliberately unavailable tool. Always fails.",
        "parameters": {"type": "object", "properties": {}},
    }

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        _ = args, sandbox
        return ToolResult(ok=False, error="broken_tool is unavailable")
