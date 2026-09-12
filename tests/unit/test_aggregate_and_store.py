from datetime import UTC, datetime
from pathlib import Path

from aeh.metrics.aggregate import aggregate
from aeh.models import GradeResult, RunResult, SuiteResult, Trace
from aeh.report.html import render_report
from aeh.storage.db import RunStore


def _result(task_id: str, success: bool, attempt: int = 0, category: str = "tool_use") -> RunResult:
    return RunResult(
        trace=Trace(
            run_id="r1",
            task_id=task_id,
            attempt=attempt,
            seed=0,
            adapter="mock",
            model="mock",
            terminated_by="completed",
            wall_clock_ms=100.0 + attempt,
            task_category=category,
            final_output="x" if success else "y",
        ),
        grades=[
            GradeResult(grader="exact", passed=success, score=1.0 if success else 0.0, detail="")
        ],
        success=success,
        failure_class=None if success else "wrong_answer",
        cost_usd=0.01,
        total_tokens=10,
    )


def test_suite_rate_is_unweighted_mean():
    # task A 2/2, task B 0/2 → unweighted mean 0.5, not pooled 2/4 (same here)
    # Make unequal attempts: A 5/5, B 0/1 → unweighted 0.5, pooled 5/6 ≈ 0.83
    results = [_result("a", True, i) for i in range(5)] + [_result("b", False, 0, "retrieval")]
    suite = SuiteResult(
        run_id="r1",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        config={
            "git_sha": "abc",
            "adapter": "mock",
            "model": "mock",
            "attempts": 5,
            "price_table_version": "2026-09-01",
            "price_table_date": "2026-09-01",
        },
        results=results,
    )
    metrics = aggregate(suite)
    assert abs(metrics.suite_success_rate - 0.5) < 1e-9
    assert metrics.n_tasks == 2


def test_store_roundtrip(tmp_path: Path):
    store = RunStore(tmp_path / "runs.db")
    now = datetime.now(UTC)
    store.start_run("r1", now, {"git_sha": "x", "price_table_version": "v"})
    result = _result("t", True)
    store.write_result(result)
    store.finish_run("r1", now)
    loaded = store.load_run("r1")
    assert loaded.results[0].success
    assert store.task_counts("r1")["t"] == (1, 1)
    html = render_report(loaded)
    assert "r1" in html
    assert "measurement health" in html.lower() or "Harness error" in html
    assert "Tier-1 invariant violations" in html
    assert "Tier-2 localization" in html


def test_old_schema_rows_still_load(tmp_path: Path):
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            config_json TEXT NOT NULL,
            price_table_version TEXT,
            git_sha TEXT
        );
        CREATE TABLE results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            success INTEGER NOT NULL,
            failure_class TEXT,
            cost_usd REAL NOT NULL,
            total_tokens INTEGER NOT NULL,
            wall_clock_ms REAL NOT NULL,
            terminated_by TEXT NOT NULL
        );
        CREATE TABLE traces (
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            trace_json TEXT NOT NULL,
            PRIMARY KEY (run_id, task_id, attempt)
        );
        CREATE TABLE grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            grader TEXT NOT NULL,
            passed INTEGER NOT NULL,
            score REAL NOT NULL,
            detail TEXT
        );
        """
    )
    trace = _result("legacy", True).trace
    conn.execute(
        "INSERT INTO runs(run_id, started_at, finished_at, config_json) VALUES (?,?,?,?)",
        ("legacy", datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), "{}"),
    )
    conn.execute(
        "INSERT INTO results(run_id, task_id, attempt, success, failure_class, cost_usd, "
        "total_tokens, wall_clock_ms, terminated_by) VALUES (?,?,?,?,?,?,?,?,?)",
        ("legacy", "legacy", 0, 1, None, 0.01, 10, 100.0, "completed"),
    )
    conn.execute(
        "INSERT INTO traces(run_id, task_id, attempt, trace_json) VALUES (?,?,?,?)",
        ("legacy", "legacy", 0, trace.model_dump_json()),
    )
    conn.execute(
        "INSERT INTO grades(run_id, task_id, attempt, grader, passed, score, detail) "
        "VALUES (?,?,?,?,?,?,?)",
        ("legacy", "legacy", 0, "exact", 1, 1.0, ""),
    )
    conn.commit()
    conn.close()
    loaded = RunStore(path).load_run("legacy")
    assert loaded.results[0].success
    assert loaded.results[0].needs_human_review is False
    assert loaded.results[0].grades[0].tier == 0
