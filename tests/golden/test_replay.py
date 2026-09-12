from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeh.execution.runner import replay_and_regrade
from aeh.grading.base import run_graders
from aeh.models import Trace
from aeh.storage.db import RunStore
from aeh.tasks.loader import load_suite
from tests.golden.import_golden import import_golden

GOLDEN = Path(__file__).parent
SNAPSHOT = json.loads((GOLDEN / "snapshot.json").read_text(encoding="utf-8"))


def test_golden_replay_matches_snapshot(repo_root: Path, fixture_db: Path):
    from aeh.execution.runner import build_graders

    tasks = {t.id: t for t in load_suite("smoke", repo_root=repo_root)}
    graders = build_graders(fixture_db)
    summary = {}
    for path in sorted((GOLDEN / "traces").glob("*.json")):
        trace = Trace.model_validate_json(path.read_text(encoding="utf-8"))
        task = tasks[trace.task_id]
        grades = run_graders(graders, task, trace)
        programmatic = [g for g in grades if g.grader != "judge"]
        success = all(g.passed for g in programmatic)
        summary[trace.task_id] = {
            "success": success,
            "failure_class": None if success else "wrong_answer",
        }
    assert summary == SNAPSHOT


@pytest.mark.asyncio
async def test_aeh_replay_command_path(repo_root: Path, tmp_path: Path):
    db = tmp_path / "runs.db"
    import_golden(db)
    store = RunStore(db)
    suite = await replay_and_regrade(store, "golden-smoke", repo_root=repo_root)
    by_id = {r.trace.task_id: r.success for r in suite.results}
    for task_id, expected in SNAPSHOT.items():
        assert by_id[task_id] is expected["success"]
