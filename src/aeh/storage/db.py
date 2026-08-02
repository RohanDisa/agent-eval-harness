from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from aeh.models import GradeResult, RunResult, SuiteResult, Trace

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    config_json TEXT NOT NULL,
    price_table_version TEXT,
    git_sha TEXT
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    success INTEGER NOT NULL,
    failure_class TEXT,
    cost_usd REAL NOT NULL,
    total_tokens INTEGER NOT NULL,
    wall_clock_ms REAL NOT NULL,
    terminated_by TEXT NOT NULL,
    needs_human_review INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS traces (
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    trace_json TEXT NOT NULL,
    PRIMARY KEY (run_id, task_id, attempt)
);
CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    grader TEXT NOT NULL,
    passed INTEGER NOT NULL,
    score REAL NOT NULL,
    detail TEXT,
    tier INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_results_run_task ON results(run_id, task_id);
"""


class RunStore:
    def __init__(self, path: Path | str = "runs.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        result_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(results)")}
        if "needs_human_review" not in result_cols:
            self.conn.execute(
                "ALTER TABLE results ADD COLUMN needs_human_review INTEGER NOT NULL DEFAULT 0"
            )
        grade_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(grades)")}
        if "tier" not in grade_cols:
            self.conn.execute("ALTER TABLE grades ADD COLUMN tier INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> RunStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def start_run(self, run_id: str, started_at: datetime, config: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO runs(run_id, started_at, config_json, price_table_version, git_sha) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                started_at.isoformat(),
                json.dumps(config),
                config.get("price_table_version"),
                config.get("git_sha"),
            ),
        )
        self.conn.commit()

    def finish_run(self, run_id: str, finished_at: datetime) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ? WHERE run_id = ?",
            (finished_at.isoformat(), run_id),
        )
        self.conn.commit()

    def write_result(self, result: RunResult) -> None:
        t = result.trace
        self.conn.execute(
            "INSERT INTO results(run_id, task_id, attempt, success, failure_class, cost_usd, "
            "total_tokens, wall_clock_ms, terminated_by, needs_human_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                t.run_id,
                t.task_id,
                t.attempt,
                int(result.success),
                result.failure_class,
                result.cost_usd,
                result.total_tokens,
                t.wall_clock_ms,
                t.terminated_by,
                int(result.needs_human_review),
            ),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO traces(run_id, task_id, attempt, trace_json) VALUES (?, ?, ?, ?)",
            (t.run_id, t.task_id, t.attempt, t.model_dump_json()),
        )
        for grade in result.grades:
            self.conn.execute(
                "INSERT INTO grades(run_id, task_id, attempt, grader, passed, score, detail, tier) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    t.run_id,
                    t.task_id,
                    t.attempt,
                    grade.grader,
                    int(grade.passed),
                    grade.score,
                    grade.detail,
                    grade.tier,
                ),
            )
        self.conn.commit()

    def load_run(self, run_id: str) -> SuiteResult:
        run = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(f"run not found: {run_id}")
        rows = self.conn.execute(
            "SELECT * FROM results WHERE run_id = ? ORDER BY task_id, attempt", (run_id,)
        ).fetchall()
        results: list[RunResult] = []
        for row in rows:
            trace_row = self.conn.execute(
                "SELECT trace_json FROM traces WHERE run_id = ? AND task_id = ? AND attempt = ?",
                (run_id, row["task_id"], row["attempt"]),
            ).fetchone()
            trace = Trace.model_validate_json(trace_row["trace_json"]) if trace_row else None
            if trace is None:
                continue
            if not trace.span_tree:
                trace.ensure_spans()
            grade_rows = self.conn.execute(
                "SELECT grader, passed, score, detail, tier FROM grades "
                "WHERE run_id = ? AND task_id = ? AND attempt = ?",
                (run_id, row["task_id"], row["attempt"]),
            ).fetchall()
            grades = [
                GradeResult(
                    grader=g["grader"],
                    passed=bool(g["passed"]),
                    score=g["score"],
                    detail=g["detail"] or "",
                    tier=g["tier"] if "tier" in g.keys() else 0,
                )
                for g in grade_rows
            ]
            review = row["needs_human_review"] if "needs_human_review" in row.keys() else 0
            results.append(
                RunResult(
                    trace=trace,
                    grades=grades,
                    success=bool(row["success"]),
                    failure_class=row["failure_class"],
                    cost_usd=row["cost_usd"],
                    total_tokens=row["total_tokens"],
                    needs_human_review=bool(review),
                )
            )
        started = datetime.fromisoformat(run["started_at"])
        finished = datetime.fromisoformat(run["finished_at"] or run["started_at"])
        return SuiteResult(
            run_id=run_id,
            started_at=started,
            finished_at=finished,
            config=json.loads(run["config_json"]),
            results=results,
        )

    def load_traces(self, run_id: str) -> list[Trace]:
        rows = self.conn.execute(
            "SELECT trace_json FROM traces WHERE run_id = ? ORDER BY task_id, attempt",
            (run_id,),
        ).fetchall()
        traces = [Trace.model_validate_json(r["trace_json"]) for r in rows]
        for trace in traces:
            if not trace.span_tree:
                trace.ensure_spans()
        return traces

    def load_attempt(self, run_id: str, task_id: str, attempt: int) -> RunResult:
        suite = self.load_run(run_id)
        for result in suite.results:
            if result.trace.task_id == task_id and result.trace.attempt == attempt:
                return result
        raise KeyError(f"no result {run_id}/{task_id}#{attempt}")

    def task_counts(self, run_id: str) -> dict[str, tuple[int, int]]:
        rows = self.conn.execute(
            "SELECT task_id, SUM(success) AS k, COUNT(*) AS n FROM results "
            "WHERE run_id = ? GROUP BY task_id",
            (run_id,),
        ).fetchall()
        return {r["task_id"]: (int(r["k"]), int(r["n"])) for r in rows}

    def run_config(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT config_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row["config_json"])

    def list_runs(self) -> list[str]:
        rows = self.conn.execute("SELECT run_id FROM runs ORDER BY started_at").fetchall()
        return [r["run_id"] for r in rows]
