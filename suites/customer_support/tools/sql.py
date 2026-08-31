from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from aeh.execution.sandbox import Sandbox
from aeh.models import ToolResult


class SqlQuery:
    name = "sql"
    schema: dict[str, Any] = {
        "name": "sql",
        "description": "Run a read-only SQL query against the seeded fixture database.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    async def call(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        _ = sandbox
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, error="empty query")
        try:
            conn = self._connect()
        except sqlite3.Error as exc:
            return ToolResult(ok=False, error=f"sql open error: {exc}")
        try:
            cur = conn.execute(query)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
            rendered = [columns] + [list(row) for row in rows]
            return ToolResult(ok=True, output=repr(rendered))
        except sqlite3.Error as exc:
            return ToolResult(ok=False, error=f"sql error: {exc}")
        finally:
            conn.close()
