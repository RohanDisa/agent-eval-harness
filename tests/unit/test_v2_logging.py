from io import StringIO
from pathlib import Path

import pytest

from aeh.execution.runner import SuiteRunner
from aeh.logging.redaction import redact_text, redact_trace
from aeh.logging.tree_logger import TreeLogger
from aeh.models import Step, ToolCall, Trace
from aeh.storage.db import RunStore


def test_tree_logger_nests_by_depth():
    buf = StringIO()
    log = TreeLogger(level="steps", fmt="pretty", stream=buf)
    log.emit(
        level="steps",
        category="tools",
        run_id="r",
        task_id="t",
        attempt=0,
        span_id="parent",
        parent_span_id=None,
        message="root call",
    )
    log.emit(
        level="steps",
        category="tools",
        run_id="r",
        task_id="t",
        attempt=0,
        span_id="child",
        parent_span_id="parent",
        message="nested call",
    )
    text = buf.getvalue()
    lines = [line for line in text.splitlines() if "call" in line]
    assert lines[0].startswith("[tools]")
    assert lines[1].startswith("  [tools]")


def test_jsonl_and_level_filters():
    buf = StringIO()
    log = TreeLogger(level="steps", categories={"tools"}, fmt="jsonl", stream=buf)
    log.emit(
        level="steps",
        category="tools",
        run_id="r",
        task_id="t",
        attempt=0,
        span_id="s",
        message="tool line",
    )
    log.emit(
        level="steps",
        category="model",
        run_id="r",
        task_id="t",
        attempt=0,
        message="hidden",
    )
    log.emit(
        level="trace",
        category="tools",
        run_id="r",
        task_id="t",
        attempt=0,
        message="too verbose",
    )
    out = buf.getvalue()
    assert "tool line" in out
    assert "hidden" not in out
    assert "too verbose" not in out
    assert '"run_id": "r"' in out


def test_silent_emits_nothing():
    buf = StringIO()
    log = TreeLogger(level="silent", stream=buf)
    log.emit(
        level="progress", category="scheduler", run_id="r", task_id="t", attempt=0, message="x"
    )
    assert buf.getvalue() == ""


def test_redaction_scrubs_pii():
    text = "email me at ada@example.com card 4111 1111 1111 1111 token=hunter2"
    clean = redact_text(text)
    assert "ada@example.com" not in clean
    assert "4111" not in clean
    trace = Trace(
        run_id="r",
        task_id="t",
        attempt=0,
        seed=0,
        adapter="mock",
        model="mock",
        steps=[
            Step(
                index=0,
                reasoning_text="send to ada@example.com",
                tool_call=ToolCall(
                    index=0,
                    name="http_get",
                    arguments={"url": "https://x.test/?email=ada@example.com"},
                    result="api_key=sk-secret",
                ),
            )
        ],
        final_output="ada@example.com",
        terminated_by="completed",
        wall_clock_ms=1.0,
    )
    redacted = redact_trace(trace)
    blob = redacted.model_dump_json()
    assert "ada@example.com" not in blob
    assert "sk-secret" not in blob


@pytest.mark.asyncio
async def test_persisted_trace_has_no_seeded_pii(repo_root: Path, tmp_path: Path):
    db = tmp_path / "runs.db"
    runner = SuiteRunner(
        suite="smoke",
        adapter_name="mock",
        model="mock",
        attempts=1,
        repo_root=repo_root,
        db_path=db,
        tasks_filter=["echo-hello"],
        mock_auto_satisfy=False,
        mock_scripts={"echo-hello": [{"final": "hello from ada@example.com"}]},
        redact=True,
    )
    suite = await runner.run()
    stored = RunStore(db).load_run(suite.run_id)
    blob = stored.results[0].trace.model_dump_json()
    assert "ada@example.com" not in blob
    assert "[redacted-email]" in blob
