from pathlib import Path

import pytest

from aeh.execution.runner import SuiteRunner, ensure_fixture_db
from aeh.report.html import render_report
from aeh.storage.db import RunStore


@pytest.mark.asyncio
async def test_smoke_end_to_end(repo_root: Path, tmp_path: Path):
    ensure_fixture_db(repo_root)
    db = tmp_path / "runs.db"
    runner = SuiteRunner(
        suite="smoke",
        adapter_name="mock",
        model="mock",
        attempts=1,
        concurrency=2,
        seed=1,
        repo_root=repo_root,
        db_path=db,
        mock_auto_satisfy=True,
    )
    suite = await runner.run()
    assert len(suite.results) == 5
    store = RunStore(db)
    loaded = store.load_run(suite.run_id)
    assert len(loaded.results) == 5
    html = render_report(loaded, tmp_path / "report.html")
    assert (tmp_path / "report.html").is_file()
    assert suite.run_id in html
    traces = store.load_traces(suite.run_id)
    assert traces
    # every trace is replay-complete: raw_response present on model steps
    for trace in traces:
        for step in trace.steps:
            assert isinstance(step.raw_response, dict)
