from pathlib import Path

import pytest

from aeh.execution.runner import SuiteRunner, ensure_fixture_db
from aeh.models import GraderSpec, Task
from aeh.tasks.loader import load_suite


@pytest.mark.asyncio
async def test_fault_injection_100_percent_is_tool_error(repo_root: Path, tmp_path: Path):
    ensure_fixture_db(repo_root)
    runner = SuiteRunner(
        suite="smoke",
        adapter_name="mock",
        model="mock",
        attempts=1,
        concurrency=2,
        repo_root=repo_root,
        db_path=tmp_path / "runs.db",
        tasks_filter=["add-two-numbers"],
        fault_profile={"calculator": {"fail_rate": 1.0}},
        mock_auto_satisfy=True,
    )
    suite = await runner.run()
    # auto_satisfy will call calculator; 100% fault → tool error on that call.
    # Success may still happen if the mock also writes the final number without needing the tool result.
    # Force a scripted run that depends on the tool:
    assert suite.results
    # At least the injected error is recorded on a tool call when the script invoked calculator.
    tool_errors = [
        r for r in suite.results if any(s.tool_call and s.tool_call.error for s in r.trace.steps)
    ]
    assert tool_errors


@pytest.mark.asyncio
async def test_concurrency_no_sandbox_leak(repo_root: Path, tmp_path: Path):
    ensure_fixture_db(repo_root)
    tasks = load_suite("core", repo_root=repo_root)
    ids = [t.id for t in tasks[:20]]
    runner = SuiteRunner(
        suite="core",
        adapter_name="mock",
        model="mock",
        attempts=1,
        concurrency=4,
        repo_root=repo_root,
        db_path=tmp_path / "runs.db",
        tasks_filter=ids,
        mock_auto_satisfy=True,
    )
    suite = await runner.run()
    assert len(suite.results) == 20
    roots = [r.trace.sandbox_final_state.get("root") for r in suite.results]
    assert len(set(roots)) == 20
    # sandboxes were cleaned up
    for root in roots:
        assert root and not Path(root).exists()


def test_task_model_accepts_grader_spec():
    t = Task(
        id="x",
        suite="s",
        prompt="p",
        category="tool_use",
        difficulty=1,
        tools=[],
        graders=[GraderSpec(type="exact", expected="z")],
    )
    assert t.id == "x"
