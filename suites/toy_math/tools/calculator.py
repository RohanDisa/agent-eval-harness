from __future__ import annotations

import ast
import operator
from typing import Any

from aeh.execution.sandbox import Sandbox
from aeh.models import ToolResult

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("expression is not a plain arithmetic formula")


class Calculator:
    name = "calculator"
    schema: dict[str, Any] = {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression (+ - * / ** %).",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    }

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        _ = sandbox
        expression = str(args.get("expression", ""))
        try:
            tree = ast.parse(expression, mode="eval")
            value = _eval(tree)
        except Exception as exc:
            return ToolResult(ok=False, error=f"calculator error: {exc}")
        if value == int(value):
            return ToolResult(ok=True, output=str(int(value)))
        return ToolResult(ok=True, output=repr(value))
