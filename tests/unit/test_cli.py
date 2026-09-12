from pathlib import Path

from tests.golden.import_golden import import_golden
from typer.testing import CliRunner

from aeh.cli import app
from aeh.metrics.compare import compare_runs
from aeh.storage.db import RunStore

runner = CliRunner()


def test_tasks_validate():
    result = runner.invoke(app, ["tasks", "validate"])
    assert result.exit_code == 0
    assert "ok:" in result.stdout


def test_tasks_list():
    result = runner.invoke(app, ["tasks", "list", "--suite", "smoke"])
    assert result.exit_code == 0
    assert "echo-hello" in result.stdout


def test_dry_run():
    result = runner.invoke(app, ["run", "--suite", "smoke", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert "estimated_cost_usd" in result.stdout


def test_run_mock_smoke(tmp_path: Path):
    db = tmp_path / "runs.db"
    result = runner.invoke(
        app,
        [
            "run",
            "--suite",
            "smoke",
            "--adapter",
            "mock",
            "--attempts",
            "1",
            "--db",
            str(db),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "run_id" in result.stdout


def test_replay_and_report(tmp_path: Path, monkeypatch):
    db = tmp_path / "runs.db"
    import_golden(db)
    result = runner.invoke(app, ["replay", "--run-id", "golden-smoke", "--db", str(db), "--json"])
    assert result.exit_code == 0
    out = tmp_path / "report.html"
    result = runner.invoke(
        app, ["report", "--run-id", "golden-smoke", "--db", str(db), "--out", str(out)]
    )
    assert result.exit_code == 0
    assert out.is_file()


def test_compare_and_agreement(tmp_path: Path):
    db = tmp_path / "runs.db"
    import_golden(db)
    # compare a run to itself — everything unchanged
    result = runner.invoke(
        app, ["compare", "golden-smoke", "golden-smoke", "--db", str(db), "--json"]
    )
    assert result.exit_code == 0
    result = runner.invoke(
        app, ["judge-agreement", "--run-id", "golden-smoke", "--db", str(db), "--json"]
    )
    assert result.exit_code == 0


def test_compare_logic_used_by_cli():
    report = compare_runs({"t": (1, 2)}, {"t": (1, 2)}, run_a="a", run_b="b")
    assert report.unchanged == ["t"]


def test_store_list_runs(tmp_path: Path):
    db = tmp_path / "runs.db"
    import_golden(db)
    assert "golden-smoke" in RunStore(db).list_runs()


def test_run_toy_math_log_level_steps(tmp_path: Path):
    db = tmp_path / "runs.db"
    result = runner.invoke(
        app,
        [
            "run",
            "--suite",
            "./suites/toy_math",
            "--adapter",
            "mock",
            "--log-level",
            "steps",
            "--log-only",
            "tools",
            "--db",
            str(db),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "run_id" in result.stdout


def test_trace_command(tmp_path: Path):
    db = tmp_path / "runs.db"
    run = runner.invoke(
        app,
        ["run", "--suite", "smoke", "--adapter", "mock", "--db", str(db), "--json"],
    )
    assert run.exit_code == 0, run.stdout + run.stderr
    store = RunStore(db)
    run_id = store.list_runs()[-1]
    out = tmp_path / "trace.html"
    result = runner.invoke(
        app,
        [
            "trace",
            "--run-id",
            run_id,
            "--task",
            "echo-hello",
            "--attempt",
            "0",
            "--db",
            str(db),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert out.is_file()
    assert "Agent Eval Harness" in out.read_text(encoding="utf-8")
