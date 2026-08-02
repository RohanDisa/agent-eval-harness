"""Load a suite by filesystem path, installed entry point, or v1 directory name."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from pathlib import Path

from aeh.errors import TaskLoadError
from aeh.models import Task
from aeh.paths import REPO_ROOT
from aeh.suite.spec import EvalSuite
from aeh.suite.yaml_tasks import load_yaml_dir

ENTRY_POINT_GROUP = "aeh.suites"
_PLUGIN_MARKERS = ("suite.py",)


class YamlDirSuite:
    """v1 compatibility: a directory of YAML tasks plus an injected tool registry."""

    def __init__(
        self,
        name: str,
        directory: Path,
        *,
        repo_root: Path,
        tools: EvalSuite,
    ) -> None:
        self.name = name
        self.directory = directory
        self.repo_root = repo_root
        self._tools = tools

    def tasks(self) -> list[Task]:
        registry = self.tool_registry()
        return load_yaml_dir(
            self.directory,
            repo_root=self.repo_root,
            known_tools=set(registry.names()),
            known_invariants=set(self.invariants()),
            golden_ids=set(self.golden_traces()),
        )

    def tool_registry(self):
        return self._tools.tool_registry()

    def invariants(self):
        return self._tools.invariants()

    def golden_traces(self):
        return self._tools.golden_traces()


def _is_plugin_dir(path: Path) -> bool:
    return (path / "suite.py").is_file() or (
        (path / "__init__.py").is_file() and (path / "tools").is_dir()
    )


def _instantiate(module, source: Path) -> EvalSuite:
    factory = getattr(module, "get_suite", None)
    if callable(factory):
        loaded = factory()
    else:
        loaded = getattr(module, "suite", None)
        if loaded is None:
            cls = getattr(module, "SUITE_CLASS", None)
            loaded = cls() if cls is not None else None
    if loaded is None:
        raise TaskLoadError(f"{source} must define get_suite(), suite, or SUITE_CLASS")
    if not isinstance(loaded, EvalSuite):
        raise TaskLoadError(f"{source} did not produce an EvalSuite")
    return loaded


def _load_plugin_from_path(path: Path) -> EvalSuite:
    path = path.resolve()
    suite_py = path / "suite.py"
    if not suite_py.is_file() and not (path / "__init__.py").is_file():
        raise TaskLoadError(f"no suite.py in {path}")
    repo_candidate = path.parent.parent
    pkg_parent = path.parent
    if (pkg_parent / "__init__.py").is_file():
        if str(repo_candidate) not in sys.path:
            sys.path.insert(0, str(repo_candidate))
        mod_name = (
            f"{pkg_parent.name}.{path.name}.suite"
            if suite_py.is_file()
            else f"{pkg_parent.name}.{path.name}"
        )
        module = importlib.import_module(mod_name)
        return _instantiate(module, suite_py if suite_py.is_file() else path / "__init__.py")
    target = suite_py if suite_py.is_file() else path / "__init__.py"
    mod_name = f"aeh_suite_{path.name}"
    spec = importlib.util.spec_from_file_location(mod_name, target)
    if spec is None or spec.loader is None:
        raise TaskLoadError(f"cannot import suite from {target}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return _instantiate(module, target)


def _load_entry_point(name: str) -> EvalSuite | None:
    try:
        eps = importlib.metadata.entry_points()
    except importlib.metadata.PackageNotFoundError:
        return None
    group = (
        eps.select(group=ENTRY_POINT_GROUP)
        if hasattr(eps, "select")
        else eps.get(ENTRY_POINT_GROUP, [])
    )
    for ep in group:
        if ep.name == name:
            obj = ep.load()
            return obj() if isinstance(obj, type) else obj
    return None


def _builtin_tool_suite(repo_root: Path) -> EvalSuite:
    plugin = repo_root / "suites" / "customer_support"
    if _is_plugin_dir(plugin):
        return _load_plugin_from_path(plugin)
    raise TaskLoadError(f"customer_support suite plugin not found at {plugin}")


def load_eval_suite(ref: str, *, repo_root: Path | None = None) -> EvalSuite:
    """Resolve `--suite smoke`, `--suite ./suites/toy_math`, or an entry point name."""
    root = repo_root or REPO_ROOT
    path = Path(ref)
    if path.is_dir():
        if _is_plugin_dir(path):
            return _load_plugin_from_path(path)
        tools = _builtin_tool_suite(root)
        return YamlDirSuite(path.name, path, repo_root=root, tools=tools)

    via_ep = _load_entry_point(ref)
    if via_ep is not None:
        return via_ep

    named = root / "suites" / ref
    if named.is_dir():
        if _is_plugin_dir(named):
            return _load_plugin_from_path(named)
        tools = _builtin_tool_suite(root)
        return YamlDirSuite(ref, named, repo_root=root, tools=tools)

    raise TaskLoadError(f"suite not found: {ref}")


def discover_suites(*, repo_root: Path | None = None) -> list[EvalSuite]:
    root = repo_root or REPO_ROOT
    base = root / "suites"
    found: list[EvalSuite] = []
    if not base.is_dir():
        return found
    for child in sorted(p for p in base.iterdir() if p.is_dir()):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if child.name == "customer_support" and _is_plugin_dir(child):
            found.append(_load_plugin_from_path(child))
            continue
        if _is_plugin_dir(child):
            found.append(_load_plugin_from_path(child))
            continue
        yamls = [p for p in child.glob("*.yaml") if p.name not in {"scripts.yaml"}]
        if yamls:
            found.append(load_eval_suite(str(child), repo_root=root))
    return found


def tasks_from_suite_ref(ref: str | None = None, *, repo_root: Path | None = None) -> list[Task]:
    root = repo_root or REPO_ROOT
    if ref:
        return load_eval_suite(ref, repo_root=root).tasks()
    all_tasks: list[Task] = []
    seen: dict[str, str] = {}
    for suite in discover_suites(repo_root=root):
        for task in suite.tasks():
            if task.id in seen and seen[task.id] != suite.name:
                # customer_support re-exports core tasks — skip exact duplicates
                if {seen[task.id], suite.name} <= {"core", "customer_support"}:
                    continue
                raise TaskLoadError(
                    f"duplicate task id '{task.id}' in {seen[task.id]} and {suite.name}"
                )
            seen.setdefault(task.id, suite.name)
            all_tasks.append(task)
    return all_tasks
