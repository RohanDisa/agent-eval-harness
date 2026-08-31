from __future__ import annotations

from typing import Any

from aeh.errors import SandboxEscapeError
from aeh.execution.sandbox import Sandbox
from aeh.models import ToolResult

_PATH_PROP = {"type": "string", "description": "Path relative to the sandbox root."}


class FsRead:
    name = "fs_read"
    schema: dict[str, Any] = {
        "name": "fs_read",
        "description": "Read a text file from the sandbox working directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": _PATH_PROP},
            "required": ["path"],
        },
    }

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        path = str(args.get("path", ""))
        try:
            text = sandbox.read_text(path)
        except SandboxEscapeError as exc:
            return ToolResult(ok=False, error=str(exc))
        except FileNotFoundError:
            return ToolResult(ok=False, error=f"file not found: {path}")
        except OSError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output=text)


class FsWrite:
    name = "fs_write"
    schema: dict[str, Any] = {
        "name": "fs_write",
        "description": "Write a text file inside the sandbox working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": _PATH_PROP,
                "content": {"type": "string", "description": "File contents."},
            },
            "required": ["path", "content"],
        },
    }

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        path = str(args.get("path", ""))
        content = str(args.get("content", ""))
        try:
            sandbox.write_text(path, content)
        except SandboxEscapeError as exc:
            return ToolResult(ok=False, error=str(exc))
        except OSError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output=f"wrote {path}")


class FsList:
    name = "fs_list"
    schema: dict[str, Any] = {
        "name": "fs_list",
        "description": "List files under a sandbox directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {**_PATH_PROP, "default": "."}},
        },
    }

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        path = str(args.get("path", ".") or ".")
        try:
            entries = sandbox.list_files(path)
        except SandboxEscapeError as exc:
            return ToolResult(ok=False, error=str(exc))
        except FileNotFoundError:
            return ToolResult(ok=False, error=f"path not found: {path}")
        except OSError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output="\n".join(entries))
