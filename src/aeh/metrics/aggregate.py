"""Wilson score interval and suite-level aggregation.

Suite success rate is the unweighted mean of per-task rates, not the pooled
attempt count. Pooling lets a task with more attempts dominate.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from aeh.models import RunResult, SuiteResult

Z_95 = 1.96


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float, float]:
    """Return (point_estimate k/n, lower, upper) using the Wilson score interval."""
    if n <= 0:
        return 0.0, 0.0, 1.0
    point = k / n
    center = (k + z**2 / 2) / (n + z**2)
    half = (z / (n + z**2)) * math.sqrt(k * (n - k) / n + z**2 / 4)
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return point, lo, hi


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if p <= 0:
        return ordered[0]
    if p >= 100:
        return ordered[-1]
    idx = (len(ordered) - 1) * (p / 100.0)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[lo]
    frac = idx - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


@dataclass
class TaskMetrics:
    task_id: str
    category: str
    n: int
    k: int
    rate: float
    wilson_lo: float
    wilson_hi: float
    mean_steps: float
    mean_steps_success: float
    mean_steps_failure: float
    mean_tool_calls_success: float
    total_cost: float
    cost_per_success: float | None
    p50_ms: float
    p95_ms: float
    p99_ms: float
    dominant_failure: str | None
    total_tokens: int


@dataclass
class SuiteMetrics:
    run_id: str
    n_tasks: int
    n_attempts: int
    suite_success_rate: float
    suite_wilson_lo: float
    suite_wilson_hi: float
    total_cost: float
    cost_per_completed_task: float
    cost_per_success: float | None
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_model_latency_ms: float
    mean_tool_latency_ms: float
    mean_steps_success: float
    mean_steps_failure: float
    termination: dict[str, int]
    failures: dict[str, int]
    harness_error_rate: float
    judge_parse_failures: int
    tasks_skipped: int
    per_task: list[TaskMetrics] = field(default_factory=list)
    per_category: dict[str, dict[str, Any]] = field(default_factory=dict)


def _tool_count(result: RunResult) -> int:
    return sum(1 for step in result.trace.steps if step.tool_call)


def _steps(result: RunResult) -> int:
    return len(result.trace.steps)


def aggregate(suite: SuiteResult) -> SuiteMetrics:
    by_task: dict[str, list[RunResult]] = defaultdict(list)
    for result in suite.results:
        by_task[result.trace.task_id].append(result)

    per_task: list[TaskMetrics] = []
    task_rates: list[float] = []
    task_ks: list[int] = []
    task_ns: list[int] = []
    all_wall: list[float] = []
    model_lat: list[float] = []
    tool_lat: list[float] = []
    successes: list[RunResult] = []
    failures: list[RunResult] = []
    termination: dict[str, int] = defaultdict(int)
    fail_counts: dict[str, int] = defaultdict(int)
    harness_errors = 0
    judge_parse_failures = 0

    for task_id, rows in sorted(by_task.items()):
        k = sum(1 for r in rows if r.success)
        n = len(rows)
        rate, lo, hi = wilson_interval(k, n)
        task_rates.append(rate)
        task_ks.append(k)
        task_ns.append(n)
        walls = [r.trace.wall_clock_ms for r in rows]
        all_wall.extend(walls)
        steps_s = [_steps(r) for r in rows if r.success]
        steps_f = [_steps(r) for r in rows if not r.success]
        tools_s = [_tool_count(r) for r in rows if r.success]
        cost = sum(r.cost_usd for r in rows)
        tokens = sum(r.total_tokens for r in rows)
        fail_classes = [r.failure_class for r in rows if r.failure_class]
        dominant = max(set(fail_classes), key=fail_classes.count) if fail_classes else None
        category = rows[0].trace.task_category or ""
        per_task.append(
            TaskMetrics(
                task_id=task_id,
                category=category,
                n=n,
                k=k,
                rate=rate,
                wilson_lo=lo,
                wilson_hi=hi,
                mean_steps=sum(_steps(r) for r in rows) / n,
                mean_steps_success=(sum(steps_s) / len(steps_s)) if steps_s else 0.0,
                mean_steps_failure=(sum(steps_f) / len(steps_f)) if steps_f else 0.0,
                mean_tool_calls_success=(sum(tools_s) / len(tools_s)) if tools_s else 0.0,
                total_cost=cost,
                cost_per_success=(cost / k) if k else None,
                p50_ms=percentile(walls, 50),
                p95_ms=percentile(walls, 95),
                p99_ms=percentile(walls, 99),
                dominant_failure=dominant,
                total_tokens=tokens,
            )
        )
        for r in rows:
            termination[r.trace.terminated_by] += 1
            if r.success:
                successes.append(r)
            else:
                failures.append(r)
                if r.failure_class:
                    fail_counts[r.failure_class] += 1
                if r.failure_class == "harness_error":
                    harness_errors += 1
            for step in r.trace.steps:
                model_lat.append(step.model_latency_ms)
                if step.tool_call:
                    tool_lat.append(step.tool_call.latency_ms)
            for g in r.grades:
                if g.grader == "judge" and g.errored:
                    judge_parse_failures += 1

    n_tasks = len(per_task)
    suite_rate = sum(task_rates) / n_tasks if n_tasks else 0.0
    # Interval around the unweighted mean of task rates, using mean n as a conservative n.
    mean_n = int(round(sum(task_ns) / n_tasks)) if n_tasks else 0
    mean_k = int(round(suite_rate * mean_n)) if mean_n else 0
    _, suite_lo, suite_hi = wilson_interval(mean_k, mean_n) if mean_n else (0.0, 0.0, 1.0)
    # Re-center the interval on the unweighted mean.
    if mean_n:
        point, lo, hi = wilson_interval(mean_k, mean_n)
        width_lo, width_hi = point - lo, hi - point
        suite_lo = max(0.0, suite_rate - width_lo)
        suite_hi = min(1.0, suite_rate + width_hi)

    total_cost = sum(r.cost_usd for r in suite.results)
    n_success = len(successes)
    n_attempts = len(suite.results)
    per_category: dict[str, dict[str, Any]] = {}
    by_cat: dict[str, list[TaskMetrics]] = defaultdict(list)
    for tm in per_task:
        by_cat[tm.category or "unknown"].append(tm)
    for cat, items in by_cat.items():
        rates = [t.rate for t in items]
        mean_rate = sum(rates) / len(rates)
        mean_n_cat = int(round(sum(t.n for t in items) / len(items)))
        mean_k_cat = int(round(mean_rate * mean_n_cat)) if mean_n_cat else 0
        _, lo, hi = wilson_interval(mean_k_cat, mean_n_cat) if mean_n_cat else (0.0, 0.0, 1.0)
        if mean_n_cat:
            point, lo0, hi0 = wilson_interval(mean_k_cat, mean_n_cat)
            lo = max(0.0, mean_rate - (point - lo0))
            hi = min(1.0, mean_rate + (hi0 - point))
        per_category[cat] = {
            "n_tasks": len(items),
            "rate": mean_rate,
            "wilson_lo": lo,
            "wilson_hi": hi,
        }

    return SuiteMetrics(
        run_id=suite.run_id,
        n_tasks=n_tasks,
        n_attempts=n_attempts,
        suite_success_rate=suite_rate,
        suite_wilson_lo=suite_lo,
        suite_wilson_hi=suite_hi,
        total_cost=total_cost,
        cost_per_completed_task=(total_cost / n_attempts) if n_attempts else 0.0,
        cost_per_success=(total_cost / n_success) if n_success else None,
        p50_ms=percentile(all_wall, 50),
        p95_ms=percentile(all_wall, 95),
        p99_ms=percentile(all_wall, 99),
        mean_model_latency_ms=(sum(model_lat) / len(model_lat)) if model_lat else 0.0,
        mean_tool_latency_ms=(sum(tool_lat) / len(tool_lat)) if tool_lat else 0.0,
        mean_steps_success=(
            sum(_steps(r) for r in successes) / len(successes) if successes else 0.0
        ),
        mean_steps_failure=(sum(_steps(r) for r in failures) / len(failures) if failures else 0.0),
        termination=dict(termination),
        failures=dict(fail_counts),
        harness_error_rate=(harness_errors / n_attempts) if n_attempts else 0.0,
        judge_parse_failures=judge_parse_failures,
        tasks_skipped=0,
        per_task=per_task,
        per_category=per_category,
    )
