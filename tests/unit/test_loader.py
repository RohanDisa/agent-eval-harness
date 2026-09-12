from pathlib import Path

import pytest
import yaml

from aeh.errors import TaskLoadError
from aeh.tasks.loader import load_suite, load_task, validate_suite


def _write(dir: Path, name: str, data: dict) -> Path:
    path = dir / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _base(**kwargs) -> dict:
    data = {
        "id": "t1",
        "suite": "tmp",
        "category": "tool_use",
        "difficulty": 1,
        "prompt": "hi",
        "tools": ["calculator"],
        "graders": [{"type": "exact", "expected": "x"}],
    }
    data.update(kwargs)
    return data


def test_unknown_tool(tmp_path: Path):
    path = _write(tmp_path, "a.yaml", _base(tools=["not_a_tool"]))
    with pytest.raises(TaskLoadError, match="unknown tool"):
        load_task(path, repo_root=tmp_path)


def test_unknown_grader(tmp_path: Path):
    path = _write(tmp_path, "a.yaml", _base(graders=[{"type": "magic"}]))
    with pytest.raises(TaskLoadError, match="unknown grader"):
        load_task(path, repo_root=tmp_path)


def test_missing_fixture(tmp_path: Path):
    path = _write(
        tmp_path,
        "a.yaml",
        _base(setup={"files": {"x.csv": "fixtures/missing.csv"}}),
    )
    with pytest.raises(TaskLoadError, match="missing fixture"):
        load_task(path, repo_root=tmp_path)


def test_duplicate_ids(tmp_path: Path):
    _write(tmp_path, "a.yaml", _base(id="same"))
    _write(tmp_path, "b.yaml", _base(id="same"))
    with pytest.raises(TaskLoadError, match="duplicate"):
        load_suite("tmp", suites_dir=tmp_path, repo_root=tmp_path)


def test_grader_config_missing_fields(tmp_path: Path):
    path = _write(tmp_path, "a.yaml", _base(graders=[{"type": "exact"}]))
    with pytest.raises(TaskLoadError, match="missing fields"):
        load_task(path, repo_root=tmp_path)


def test_tool_sequence_needs_lists(tmp_path: Path):
    path = _write(tmp_path, "a.yaml", _base(graders=[{"type": "tool_sequence"}]))
    with pytest.raises(TaskLoadError, match="tool_sequence"):
        load_task(path, repo_root=tmp_path)


def test_invalid_yaml(tmp_path: Path):
    path = tmp_path / "a.yaml"
    path.write_text(": : :", encoding="utf-8")
    with pytest.raises(TaskLoadError):
        load_task(path, repo_root=tmp_path)


def test_validate_real_suites(repo_root: Path):
    tasks = validate_suite(repo_root=repo_root)
    core = [t for t in tasks if t.suite == "core"]
    smoke = [t for t in tasks if t.suite == "smoke"]
    assert len(smoke) == 5
    assert len(core) >= 30
    cats = {t.category for t in core}
    assert {"retrieval", "multi_step", "tool_use", "refusal", "long_horizon"} <= cats


def test_whitespace_id_rejected(tmp_path: Path):
    path = _write(tmp_path, "a.yaml", _base(id="not a slug"))
    with pytest.raises(TaskLoadError):
        load_task(path, repo_root=tmp_path)
