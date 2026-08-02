"""YAML task files, validated against the suite that owns them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from aeh.errors import TaskLoadError
from aeh.models import GraderSpec, Task
from aeh.tasks.registry import KNOWN_GRADER_TYPES

SKIP_YAML_NAMES = {"scripts.yaml", "suite.yaml"}


def load_yaml_task(
    path: Path,
    *,
    repo_root: Path,
    known_tools: set[str],
    known_invariants: set[str] | None = None,
    golden_ids: set[str] | None = None,
) -> Task:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskLoadError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise TaskLoadError(f"{path}: task file must be a mapping")
    try:
        task = Task.model_validate(raw)
    except ValidationError as exc:
        raise TaskLoadError(f"{path}: {exc}") from exc
    _validate_task(
        task,
        path,
        repo_root,
        known_tools=known_tools,
        known_invariants=known_invariants or set(),
        golden_ids=golden_ids or set(),
    )
    return task


def load_yaml_dir(
    directory: Path,
    *,
    repo_root: Path,
    known_tools: set[str],
    known_invariants: set[str] | None = None,
    golden_ids: set[str] | None = None,
) -> list[Task]:
    if not directory.is_dir():
        raise TaskLoadError(f"suite directory not found: {directory}")
    paths = [
        p
        for p in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
        if p.name not in SKIP_YAML_NAMES
    ]
    if not paths:
        raise TaskLoadError(f"no task files in {directory}")
    tasks = [
        load_yaml_task(
            path,
            repo_root=repo_root,
            known_tools=known_tools,
            known_invariants=known_invariants,
            golden_ids=golden_ids,
        )
        for path in paths
    ]
    _assert_unique_ids(tasks, directory)
    return tasks


def _assert_unique_ids(tasks: list[Task], directory: Path) -> None:
    seen: dict[str, int] = {}
    for task in tasks:
        if task.id in seen:
            raise TaskLoadError(f"duplicate task id '{task.id}' in suite {directory}")
        seen[task.id] = 1


def _validate_task(
    task: Task,
    path: Path,
    repo_root: Path,
    *,
    known_tools: set[str],
    known_invariants: set[str],
    golden_ids: set[str],
) -> None:
    unknown_tools = [name for name in task.tools if name not in known_tools]
    if unknown_tools:
        raise TaskLoadError(f"{path}: unknown tool names: {unknown_tools}")
    graders = task.graders
    if not graders:
        raise TaskLoadError(f"{path}: task must declare at least one grader")
    for spec in graders:
        if spec.type not in KNOWN_GRADER_TYPES:
            raise TaskLoadError(f"{path}: unknown grader type '{spec.type}'")
        _validate_grader_config(spec, path)
    extra_invariants = getattr(task, "invariants", None) or []
    unknown_inv = [name for name in extra_invariants if name not in known_invariants]
    if unknown_inv:
        raise TaskLoadError(f"{path}: unknown invariant names: {unknown_inv}")
    golden_id = getattr(task, "golden_trace_id", None)
    if golden_id and golden_id not in golden_ids:
        raise TaskLoadError(f"{path}: missing golden trace '{golden_id}'")
    if task.setup:
        for dest, fixture in task.setup.files.items():
            fixture_path = _resolve_fixture(fixture, repo_root)
            if not fixture_path.is_file():
                raise TaskLoadError(f"{path}: missing fixture file '{fixture}' for '{dest}'")


def _resolve_fixture(fixture: str, repo_root: Path) -> Path:
    candidate = Path(fixture)
    if candidate.is_absolute():
        return candidate
    return (repo_root / fixture).resolve()


def _validate_grader_config(spec: GraderSpec, path: Path) -> None:
    data: dict[str, Any] = spec.model_dump()
    grader_type = data.pop("type")
    required: dict[str, list[str]] = {
        "exact": ["expected"],
        "contains": ["needle"],
        "not_contains": ["needle"],
        "numeric_close": ["expected"],
        "json_schema": ["schema"],
        "file_state": ["path"],
        "sql_result": ["query", "expected"],
        "step_budget": ["max_steps"],
        "tool_sequence": [],
        "judge": ["rubric"],
    }
    missing = [key for key in required.get(grader_type, []) if key not in data or data[key] is None]
    if missing:
        raise TaskLoadError(f"{path}: grader '{grader_type}' missing fields: {missing}")
    if grader_type == "tool_sequence" and not data.get("required") and not data.get("forbidden"):
        raise TaskLoadError(f"{path}: tool_sequence grader needs 'required' and/or 'forbidden'")
