import ast
from pathlib import Path

import pytest
import yaml

from aeh.errors import TaskLoadError
from aeh.suite.loader import discover_suites, load_eval_suite
from aeh.suite.yaml_tasks import load_yaml_task


def test_both_suites_load_through_one_loader(repo_root: Path):
    cs = load_eval_suite("customer_support", repo_root=repo_root)
    toy = load_eval_suite(str(repo_root / "suites" / "toy_math"), repo_root=repo_root)
    assert cs.name == "customer_support"
    assert toy.name == "toy_math"
    assert len(cs.tasks()) >= 30
    assert len(toy.tasks()) == 3
    assert "calculator" in toy.tool_registry().names()
    assert "sql" in cs.tool_registry().names()
    assert "calculator" not in {"sql"}  # domains differ
    assert "sql" not in toy.tool_registry().names()


def test_discover_includes_v1_and_plugins(repo_root: Path):
    names = {s.name for s in discover_suites(repo_root=repo_root)}
    assert {"customer_support", "toy_math", "core", "smoke"} <= names


def test_unknown_invariant_rejected(tmp_path: Path, repo_root: Path):
    path = tmp_path / "a.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "id": "t1",
                "suite": "tmp",
                "category": "tool_use",
                "difficulty": 1,
                "prompt": "hi",
                "tools": ["calculator"],
                "invariants": ["not_a_real_rule"],
                "graders": [{"type": "exact", "expected": "x"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TaskLoadError, match="unknown invariant"):
        load_yaml_task(
            path,
            repo_root=repo_root,
            known_tools={"calculator"},
            known_invariants={"calculator_only"},
        )


def test_missing_golden_rejected(tmp_path: Path, repo_root: Path):
    path = tmp_path / "a.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "id": "t1",
                "suite": "tmp",
                "category": "tool_use",
                "difficulty": 1,
                "prompt": "hi",
                "tools": ["calculator"],
                "golden_trace_id": "ghost",
                "graders": [{"type": "exact", "expected": "x"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TaskLoadError, match="missing golden"):
        load_yaml_task(path, repo_root=repo_root, known_tools={"calculator"}, golden_ids=set())


def test_engine_does_not_import_suite_tools():
    src = Path(__file__).resolve().parents[2] / "src" / "aeh"
    forbidden = (
        "suites.customer_support",
        "suites.toy_math",
        "from aeh.tools.calculator",
        "from aeh.tools.filesystem",
        "from aeh.tools.http",
        "from aeh.tools.sql",
    )
    concrete_names = {
        "Calculator",
        "FsRead",
        "FsWrite",
        "FsList",
        "HttpGet",
        "SqlQuery",
        "BrokenTool",
    }
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path}: {token}")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and "aeh.tools" in (node.module or "")
            ):
                for alias in node.names:
                    if alias.name in concrete_names:
                        offenders.append(f"{path}: imports {alias.name}")
    assert offenders == []
