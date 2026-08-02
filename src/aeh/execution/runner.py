"""Orchestrates suite → tasks → repeats. The harness owns budget, sandbox, and trace."""

from __future__ import annotations

import asyncio
import json
import random
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from aeh.adapters.mock import MockAdapter
from aeh.adapters.provider import ChatProvider
from aeh.adapters.react import ReactAdapter
from aeh.adapters.replay import ReplayAdapter
from aeh.adapters.single_shot import SingleShotAdapter
from aeh.errors import BudgetExceeded
from aeh.execution.budget import Budget
from aeh.execution.http_fixtures import start_fixture_server
from aeh.execution.sandbox import Sandbox, seed_setup
from aeh.grading.base import run_graders
from aeh.grading.contains import ContainsGrader, NotContainsGrader
from aeh.grading.exact import ExactGrader
from aeh.grading.file_state import FileStateGrader
from aeh.grading.json_schema import JsonSchemaGrader, NumericCloseGrader
from aeh.grading.judge import JudgeGrader
from aeh.grading.sql_result import SqlResultGrader, StepBudgetGrader, ToolSequenceGrader
from aeh.grading.tier1_invariants import run_invariants
from aeh.grading.tier2_golden import PROMPT_VERSION, compare_to_golden
from aeh.grading.tier3_human import needs_human_review, review_packet
from aeh.logging.redaction import redact_text, redact_trace
from aeh.logging.tree_logger import TreeLogger
from aeh.metrics.cost import PRICE_TABLE_DATE, PRICE_TABLE_VERSION, estimate_cost, tokens_from_trace
from aeh.metrics.failure_taxonomy import classify_failure
from aeh.models import GradeResult, RunResult, SuiteResult, Task, Trace
from aeh.paths import REPO_ROOT
from aeh.storage.db import RunStore
from aeh.suite.loader import load_eval_suite
from aeh.suite.spec import EvalSuite
from aeh.tools.registry import ToolRegistry


def git_sha(repo_root: Path | None = None) -> str:
    cwd = repo_root or REPO_ROOT
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


def load_fault_profile(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("fault profile must be a mapping of tool_name -> spec")
    return data


def build_graders(fixture_db: Path, judge: JudgeGrader | None = None) -> dict[str, Any]:
    graders: dict[str, Any] = {
        "exact": ExactGrader(),
        "contains": ContainsGrader(),
        "not_contains": NotContainsGrader(),
        "numeric_close": NumericCloseGrader(),
        "json_schema": JsonSchemaGrader(),
        "file_state": FileStateGrader(),
        "sql_result": SqlResultGrader(fixture_db),
        "step_budget": StepBudgetGrader(),
        "tool_sequence": ToolSequenceGrader(),
    }
    if judge is not None:
        graders["judge"] = judge
    return graders


def success_from_grades(grades) -> bool:
    """Tier 0 only. Invariants and golden-trace notes never flip success."""
    tier0 = [g for g in grades if getattr(g, "tier", 0) == 0]
    programmatic = [g for g in tier0 if g.grader != "judge"]
    pool = programmatic or tier0
    if not pool:
        return True
    return all(g.passed and not g.errored for g in pool)


class SuiteRunner:
    def __init__(
        self,
        *,
        suite: str,
        adapter_name: str,
        model: str,
        attempts: int = 1,
        concurrency: int = 2,
        seed: int = 42,
        tasks_filter: list[str] | None = None,
        fault_profile: dict[str, Any] | None = None,
        repo_root: Path | None = None,
        db_path: Path | None = None,
        store: RunStore | None = None,
        provider: ChatProvider | None = None,
        judge_provider: ChatProvider | None = None,
        registry: ToolRegistry | None = None,
        replay_traces: dict[tuple[str, int], Trace] | None = None,
        mock_scripts: dict[str, list] | None = None,
        mock_auto_satisfy: bool = True,
        logger: TreeLogger | None = None,
        redact: bool = True,
    ) -> None:
        self.suite = suite
        self.adapter_name = adapter_name
        self.model = model
        self.attempts = attempts
        self.concurrency = concurrency
        self.seed = seed
        self.tasks_filter = tasks_filter
        self.fault_profile = fault_profile or {}
        self.repo_root = repo_root or REPO_ROOT
        self.store = store or RunStore(db_path or (self.repo_root / "runs.db"))
        self.provider = provider
        self.judge_provider = judge_provider
        self.fixture_db = self.repo_root / "fixtures" / "sql" / "fixture.db"
        self.registry = registry
        self.replay_traces = replay_traces
        self.mock_scripts = mock_scripts
        self.mock_auto_satisfy = mock_auto_satisfy
        self.logger = logger or TreeLogger()
        self.redact = redact
        self.run_id = str(uuid.uuid4())
        self._plugin: EvalSuite | None = None

    def suite_plugin(self) -> EvalSuite:
        if self._plugin is None:
            self._plugin = load_eval_suite(self.suite, repo_root=self.repo_root)
        return self._plugin

    def resolved_config(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "adapter": self.adapter_name,
            "model": self.model,
            "attempts": self.attempts,
            "concurrency": self.concurrency,
            "seed": self.seed,
            "tasks_filter": self.tasks_filter,
            "fault_profile": self.fault_profile,
            "price_table_version": PRICE_TABLE_VERSION,
            "price_table_date": PRICE_TABLE_DATE,
            "judge_model": self.judge_provider.model if self.judge_provider else None,
            "tier2_prompt_version": PROMPT_VERSION,
            "git_sha": git_sha(self.repo_root),
            "redact": self.redact,
        }

    def _registry(self, rng: random.Random) -> ToolRegistry:
        if self.registry is not None:
            return self.registry
        registry = self.suite_plugin().tool_registry()
        registry.fault_profile = self.fault_profile
        registry.rng = rng
        return registry

    def _adapter(self, attempt: int, rng: random.Random, registry: ToolRegistry):
        if self.adapter_name == "mock":
            return MockAdapter(
                scripts=self.mock_scripts,
                registry=registry,
                model=self.model,
                run_id=self.run_id,
                attempt=attempt,
                seed=self.seed + attempt,
                auto_satisfy=self.mock_auto_satisfy,
            )
        if self.adapter_name == "replay":
            adapter = ReplayAdapter(self.replay_traces)
            adapter.model = self.model
            return adapter
        provider = self.provider or ChatProvider(self.model)
        if self.adapter_name == "single_shot":
            return SingleShotAdapter(
                provider, run_id=self.run_id, attempt=attempt, seed=self.seed + attempt
            )
        if self.adapter_name == "react":
            return ReactAdapter(
                provider,
                registry,
                run_id=self.run_id,
                attempt=attempt,
                seed=self.seed + attempt,
            )
        raise ValueError(f"unknown adapter '{self.adapter_name}'")

    def estimate_tokens(self, tasks: list[Task]) -> dict[str, Any]:
        # Conservative dry-run estimate: 800 tokens in / 200 out per step, half of max_steps.
        per_attempt = []
        total_in = total_out = 0
        for task in tasks:
            steps = max(1, task.max_steps // 2)
            inp = 800 * steps
            out = 200 * steps
            total_in += inp * self.attempts
            total_out += out * self.attempts
            per_attempt.append(task.id)
        cost = estimate_cost(self.model, total_in, total_out)
        return {
            "tasks": len(tasks),
            "attempts": self.attempts,
            "estimated_input_tokens": total_in,
            "estimated_output_tokens": total_out,
            "estimated_cost_usd": round(cost, 4),
            "model": self.model,
            "price_table_version": PRICE_TABLE_VERSION,
        }

    async def run(self, progress_cb=None) -> SuiteResult:
        tasks = self.suite_plugin().tasks()
        if self.tasks_filter:
            wanted = set(self.tasks_filter)
            tasks = [t for t in tasks if t.id in wanted]
            missing = wanted - {t.id for t in tasks}
            if missing:
                raise ValueError(f"unknown task ids: {sorted(missing)}")
        started = datetime.now(UTC)
        config = self.resolved_config()
        self.store.start_run(self.run_id, started, config)
        sem = asyncio.Semaphore(self.concurrency)
        results: list[RunResult] = []
        total = len(tasks) * self.attempts
        done = 0
        lock = asyncio.Lock()

        async def one(task: Task, attempt: int) -> RunResult:
            nonlocal done
            async with sem:
                result = await self._run_attempt(task, attempt)
            async with lock:
                self.store.write_result(result)
                results.append(result)
                done += 1
                if progress_cb:
                    progress_cb(done, total, task.id, attempt, result.success)
            return result

        server = None
        if any("http_get" in t.tools for t in tasks):
            try:
                server, _thread = start_fixture_server(self.repo_root)
            except OSError:
                server = None
        try:
            async with asyncio.TaskGroup() as group:
                for task in tasks:
                    for attempt in range(self.attempts):
                        group.create_task(one(task, attempt))
        finally:
            if server is not None:
                server.shutdown()
        finished = datetime.now(UTC)
        self.store.finish_run(self.run_id, finished)
        results.sort(key=lambda r: (r.trace.task_id, r.trace.attempt))
        return SuiteResult(
            run_id=self.run_id,
            started_at=started,
            finished_at=finished,
            config=config,
            results=results,
        )

    async def _run_attempt(self, task: Task, attempt: int) -> RunResult:
        rng = random.Random(self.seed + 1009 * attempt + hash(task.id) % 10_000)
        registry = self._registry(rng)
        sandbox = Sandbox()
        budget = Budget(task.max_steps, task.max_tokens, task.timeout_s)
        adapter = self._adapter(attempt, rng, registry)
        judge = JudgeGrader(self.judge_provider) if self.judge_provider else JudgeGrader(None)
        graders = build_graders(self.fixture_db, judge=judge)
        error: str | None = None
        try:
            if task.setup and task.setup.files:
                seed_setup(sandbox, task.setup.files, self.repo_root)
            try:
                trace = await asyncio.wait_for(
                    adapter.run(task, sandbox, budget), timeout=task.timeout_s
                )
            except TimeoutError:
                trace = Trace(
                    run_id=self.run_id,
                    task_id=task.id,
                    attempt=attempt,
                    seed=self.seed + attempt,
                    adapter=self.adapter_name,
                    model=self.model,
                    steps=[],
                    final_output=None,
                    terminated_by="timeout",
                    wall_clock_ms=budget.elapsed_ms(),
                    allowed_tools=list(task.tools),
                    task_category=task.category,
                )
            except BudgetExceeded as exc:
                trace = Trace(
                    run_id=self.run_id,
                    task_id=task.id,
                    attempt=attempt,
                    seed=self.seed + attempt,
                    adapter=self.adapter_name,
                    model=self.model,
                    steps=[],
                    final_output=None,
                    terminated_by=exc.reason,  # type: ignore[arg-type]
                    wall_clock_ms=budget.elapsed_ms(),
                    allowed_tools=list(task.tools),
                    task_category=task.category,
                )
        except Exception as exc:  # harness bug
            error = str(exc)
            trace = Trace(
                run_id=self.run_id,
                task_id=task.id,
                attempt=attempt,
                seed=self.seed + attempt,
                adapter=self.adapter_name,
                model=self.model,
                steps=[],
                final_output=None,
                terminated_by="error",
                wall_clock_ms=budget.elapsed_ms(),
                error=error,
                allowed_tools=list(task.tools),
                task_category=task.category,
            )
        trace.sandbox_final_state = sandbox.snapshot()
        trace.run_id = self.run_id
        trace.attempt = attempt
        trace.allowed_tools = list(task.tools)
        trace.task_category = task.category
        trace.ensure_spans()
        grades = await self._grade_all(task, trace, graders, judge)
        success = success_from_grades(grades)
        grades = await self._apply_upper_tiers(task, trace, grades, success)
        review = needs_human_review(success, task, grades)
        if review:
            packet = review_packet(
                task,
                trace,
                grades,
                viewer_hint=f"aeh trace --run-id {self.run_id} --task {task.id} --attempt {attempt}",
            )
            grades.append(
                GradeResult(
                    grader="human_review",
                    passed=True,
                    score=0.0,
                    detail=json.dumps(packet),
                    tier=3,
                )
            )
        failure = None if success else classify_failure(trace, grades)
        inp, out, total = tokens_from_trace(trace)
        cost = estimate_cost(trace.model, inp, out) + sum(g.cost_usd for g in grades)
        self._log_attempt(task, attempt, trace, grades, success, cost)
        if self.redact:
            trace = redact_trace(trace)
            trace.ensure_spans()
        sandbox.cleanup()
        return RunResult(
            trace=trace,
            grades=grades,
            success=success,
            failure_class=failure,
            cost_usd=cost,
            total_tokens=total,
            needs_human_review=review,
        )

    async def _grade_all(
        self, task: Task, trace: Trace, graders: dict[str, Any], judge: JudgeGrader
    ) -> list[GradeResult]:
        grades: list[GradeResult] = []
        for spec in task.outcome_graders:
            if spec.type == "judge":
                result = await judge.grade_async(spec, trace, task)
                result.tier = 0
                grades.append(result)
            else:
                slice_task = task.model_copy(update={"outcome_graders": [spec]})
                for grade in run_graders({spec.type: graders[spec.type]}, slice_task, trace):
                    grade.tier = 0
                    grades.append(grade)
        return grades

    async def _apply_upper_tiers(
        self, task: Task, trace: Trace, grades: list[GradeResult], success: bool
    ) -> list[GradeResult]:
        plugin = self.suite_plugin()
        grades.extend(run_invariants(task.invariants, plugin.invariants(), trace))
        if not success and task.golden_trace_id:
            golden = plugin.golden_traces().get(task.golden_trace_id)
            if golden is not None:
                grades.append(await compare_to_golden(task, trace, golden, self.judge_provider))
        return grades

    def _log_attempt(
        self,
        task: Task,
        attempt: int,
        trace: Trace,
        grades: list[GradeResult],
        success: bool,
        cost: float,
    ) -> None:
        log = self.logger
        rid, tid = self.run_id, task.id
        status = "ok" if success else "fail"
        log.emit(
            level="progress",
            category="scheduler",
            run_id=rid,
            task_id=tid,
            attempt=attempt,
            message=f"{status} {trace.terminated_by}",
        )
        for step in trace.steps:
            tool = step.tool_call
            if tool:
                msg = f"step {step.index} {tool.name} {tool.latency_ms:.0f}ms"
                if log.enabled("calls", "tools"):
                    args = redact_text(str(tool.arguments)) if self.redact else str(tool.arguments)
                    result = tool.result or tool.error or ""
                    if self.redact:
                        result = redact_text(result)
                    msg = f"{msg} args={args} result={result}"
                log.emit(
                    level="steps",
                    category="tools",
                    run_id=rid,
                    task_id=tid,
                    attempt=attempt,
                    span_id=tool.span_id or step.span_id,
                    parent_span_id=tool.parent_span_id or step.parent_span_id,
                    message=msg,
                    extra={"latency_ms": tool.latency_ms, "tokens": 0},
                )
                if tool.injected_fault:
                    log.emit(
                        level="steps",
                        category="faults",
                        run_id=rid,
                        task_id=tid,
                        attempt=attempt,
                        span_id=tool.span_id,
                        parent_span_id=tool.parent_span_id,
                        message=f"injected {tool.injected_fault} on {tool.name}",
                    )
            tokens = step.model_input_tokens + step.model_output_tokens
            model_msg = f"step {step.index} model {step.model_latency_ms:.0f}ms {tokens} tok"
            if log.enabled("trace", "model") and step.reasoning_text:
                text = redact_text(step.reasoning_text) if self.redact else step.reasoning_text
                model_msg = f"{model_msg} {text}"
            log.emit(
                level="steps",
                category="model",
                run_id=rid,
                task_id=tid,
                attempt=attempt,
                span_id=step.span_id,
                parent_span_id=step.parent_span_id,
                message=model_msg,
                extra={"latency_ms": step.model_latency_ms, "tokens": tokens},
            )
        for grade in grades:
            log.emit(
                level="steps",
                category="grading",
                run_id=rid,
                task_id=tid,
                attempt=attempt,
                message=f"tier {grade.tier} {grade.grader} {'pass' if grade.passed else 'fail'}",
            )
        log.emit(
            level="steps",
            category="cost",
            run_id=rid,
            task_id=tid,
            attempt=attempt,
            message=f"${cost:.6f}",
        )


async def replay_and_regrade(
    store: RunStore,
    run_id: str,
    repo_root: Path | None = None,
) -> SuiteResult:
    """Re-grade recorded traces with zero network calls."""
    original = store.load_run(run_id)
    root = repo_root or REPO_ROOT
    plugin = load_eval_suite(original.config.get("suite", "core"), repo_root=root)
    tasks = {t.id: t for t in plugin.tasks()}
    fixture_db = root / "fixtures" / "sql" / "fixture.db"
    graders = build_graders(fixture_db)
    new_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    config = dict(original.config)
    config["adapter"] = "replay"
    config["replay_of"] = run_id
    store.start_run(new_id, started, config)
    results: list[RunResult] = []
    for result in original.results:
        task = tasks.get(result.trace.task_id)
        if task is None:
            continue
        trace = result.trace.model_copy(deep=True)
        trace.run_id = new_id
        grades = run_graders(graders, task, trace)
        for grade in grades:
            grade.tier = 0
        success = success_from_grades(grades)
        runner = SuiteRunner(
            suite=original.config.get("suite", "core"),
            adapter_name="replay",
            model=original.config.get("model", "mock"),
            repo_root=root,
            store=store,
            judge_provider=None,
        )
        runner._plugin = plugin
        grades = await runner._apply_upper_tiers(task, trace, grades, success)
        review = needs_human_review(success, task, grades)
        failure = None if success else classify_failure(trace, grades)
        inp, out, total = tokens_from_trace(trace)
        if original.config.get("redact", True):
            trace = redact_trace(trace)
            trace.ensure_spans()
        rerun = RunResult(
            trace=trace,
            grades=grades,
            success=success,
            failure_class=failure,
            cost_usd=estimate_cost(trace.model, inp, out),
            total_tokens=total,
            needs_human_review=review,
        )
        store.write_result(rerun)
        results.append(rerun)
    finished = datetime.now(UTC)
    store.finish_run(new_id, finished)
    return SuiteResult(
        run_id=new_id,
        started_at=started,
        finished_at=finished,
        config=config,
        results=results,
    )


def dry_run_estimate(
    suite: str,
    model: str,
    attempts: int,
    tasks_filter: list[str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or REPO_ROOT
    plugin = load_eval_suite(suite, repo_root=root)
    tasks = plugin.tasks()
    if tasks_filter:
        tasks = [t for t in tasks if t.id in set(tasks_filter)]
    runner = SuiteRunner(
        suite=suite, adapter_name="mock", model=model, attempts=attempts, repo_root=root
    )
    estimate = runner.estimate_tokens(tasks)
    estimate["config"] = {
        "suite": suite,
        "model": model,
        "attempts": attempts,
        "tasks": [t.id for t in tasks],
        "git_sha": git_sha(root),
        "price_table_version": PRICE_TABLE_VERSION,
        "price_table_date": PRICE_TABLE_DATE,
    }
    return estimate


def ensure_fixture_db(repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    db_path = root / "fixtures" / "sql" / "fixture.db"
    seed = root / "fixtures" / "sql" / "seed.sql"
    if db_path.exists() and seed.exists() and db_path.stat().st_mtime >= seed.stat().st_mtime:
        return db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3

    sql = seed.read_text(encoding="utf-8") if seed.exists() else "SELECT 1;"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    conn.commit()
    conn.close()
    return db_path
