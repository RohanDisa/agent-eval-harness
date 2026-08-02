"""v1 YAML loader. Thin wrapper over the suite-aware loader."""

from __future__ import annotations

from pathlib import Path

from aeh.errors import TaskLoadError
from aeh.models import Task
from aeh.paths import REPO_ROOT

__all__ = ["REPO_ROOT", "load_suite", "load_task", "validate_suite"]
from aeh.suite.yaml_tasks import load_yaml_dir, load_yaml_task
from aeh.tasks.registry import KNOWN_TOOLS


def _repo_root() -> Path:
    return REPO_ROOT


def load_task(path: Path, *, repo_root: Path | None = None) -> Task:
    root = repo_root or _repo_root()
    return load_yaml_task(path, repo_root=root, known_tools=set(KNOWN_TOOLS))


def load_suite(
    suite: str, *, suites_dir: Path | None = None, repo_root: Path | None = None
) -> list[Task]:
    root = repo_root or _repo_root()
    directory = suites_dir or (root / "suites" / suite)
    if not directory.is_dir():
        raise TaskLoadError(f"suite directory not found: {directory}")
    return load_yaml_dir(directory, repo_root=root, known_tools=set(KNOWN_TOOLS))


def validate_suite(
    suite: str | None = None, *, suites_dir: Path | None = None, repo_root: Path | None = None
) -> list[Task]:
    from aeh.suite.loader import tasks_from_suite_ref

    root = repo_root or _repo_root()
    if suites_dir is not None:
        if suite:
            return load_suite(suite, suites_dir=suites_dir, repo_root=root)
        return load_suite("tmp", suites_dir=suites_dir, repo_root=root)
    return tasks_from_suite_ref(suite, repo_root=root)
