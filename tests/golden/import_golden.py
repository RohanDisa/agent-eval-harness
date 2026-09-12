"""Load committed golden traces into runs.db as run_id=golden-smoke."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aeh.models import GradeResult, RunResult, Trace  # noqa: E402
from aeh.storage.db import RunStore  # noqa: E402


def import_golden(db_path: Path | None = None, run_id: str = "golden-smoke") -> str:
    store = RunStore(db_path or (ROOT / "runs.db"))
    traces_dir = Path(__file__).parent / "traces"
    now = datetime.now(UTC)
    try:
        store.start_run(
            run_id,
            now,
            {
                "suite": "smoke",
                "adapter": "replay",
                "model": "mock",
                "attempts": 1,
                "price_table_version": "2026-09-01",
                "git_sha": "golden",
            },
        )
    except Exception:
        pass
    for path in sorted(traces_dir.glob("*.json")):
        trace = Trace.model_validate_json(path.read_text(encoding="utf-8"))
        trace.run_id = run_id
        store.write_result(
            RunResult(
                trace=trace,
                grades=[
                    GradeResult(grader="placeholder", passed=True, score=1.0, detail="imported")
                ],
                success=True,
            )
        )
    store.finish_run(run_id, now)
    return run_id


if __name__ == "__main__":
    print(import_golden())
