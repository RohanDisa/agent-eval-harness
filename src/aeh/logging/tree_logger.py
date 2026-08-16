"""User-controlled tree logger. Quiet by default. Tree-shaped. Redacted on write."""

from __future__ import annotations

import json
from typing import Any, TextIO

from rich.console import Console

LEVELS = ("silent", "progress", "steps", "calls", "trace")
CATEGORIES = ("tools", "model", "grading", "faults", "scheduler", "cost")


class TreeLogger:
    def __init__(
        self,
        level: str = "progress",
        categories: set[str] | None = None,
        exclude: set[str] | None = None,
        fmt: str = "pretty",
        stream: TextIO | None = None,
        console: Console | None = None,
    ) -> None:
        self.level = level if level in LEVELS else "progress"
        self.include = set(categories) if categories else set(CATEGORIES)
        if exclude:
            self.include -= set(exclude)
        self.fmt = fmt
        if console is not None:
            self.console = console
        elif stream is not None:
            self.console = Console(file=stream, highlight=False, no_color=True)
        else:
            self.console = Console()
        self._depth: dict[str, int] = {}

    def enabled(self, level: str, category: str) -> bool:
        if self.level == "silent":
            return False
        rank = LEVELS.index(self.level)
        need = LEVELS.index(level) if level in LEVELS else 1
        if rank < need:
            return False
        return category in self.include

    def emit(
        self,
        *,
        level: str,
        category: str,
        run_id: str,
        task_id: str,
        attempt: int,
        span_id: str = "",
        parent_span_id: str | None = None,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled(level, category):
            return
        if parent_span_id and parent_span_id in self._depth:
            depth = self._depth[parent_span_id] + 1
        elif parent_span_id:
            depth = 1
        else:
            depth = 0
        if span_id:
            self._depth[span_id] = depth
        record = {
            "run_id": run_id,
            "task_id": task_id,
            "attempt": attempt,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "category": category,
            "message": message,
            **(extra or {}),
        }
        if self.fmt == "jsonl":
            self.console.print(json.dumps(record, default=str), markup=False, highlight=False)
            return
        indent = "  " * depth
        self.console.print(
            f"{indent}[{category}] {task_id}#{attempt} {message}",
            markup=False,
            highlight=False,
        )
