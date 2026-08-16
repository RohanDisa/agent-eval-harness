from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from aeh.grading.agreement import agreement_report, paired_from_results
from aeh.grading.tier2_golden import parse_divergence
from aeh.metrics.aggregate import SuiteMetrics, aggregate
from aeh.models import RunResult, SuiteResult

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("ascii")
    import matplotlib.pyplot as plt

    plt.close(fig)
    return f"data:image/png;base64,{encoded}"


def _charts(metrics: SuiteMetrics) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    charts: dict[str, str] = {}
    cats = list(metrics.per_category.keys())
    if cats:
        rates = [metrics.per_category[c]["rate"] for c in cats]
        lo = [metrics.per_category[c]["wilson_lo"] for c in cats]
        hi = [metrics.per_category[c]["wilson_hi"] for c in cats]
        err = [
            [max(0.0, r - low) for r, low in zip(rates, lo, strict=True)],
            [max(0.0, h - r) for r, h in zip(rates, hi, strict=True)],
        ]
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.bar(cats, rates, yerr=err, capsize=4, color="#3b6d9a")
        ax.set_ylim(0, 1)
        ax.set_ylabel("success rate")
        ax.set_title("Per-category success rate (Wilson 95%)")
        charts["category"] = _png(fig)

    if metrics.failures:
        fig, ax = plt.subplots(figsize=(7, 3.5))
        labels = list(metrics.failures.keys())
        values = [metrics.failures[k] for k in labels]
        ax.barh(labels, values, color="#b4554a")
        ax.set_title("Failure taxonomy")
        charts["failures"] = _png(fig)

    if metrics.per_task:
        fig, ax = plt.subplots(figsize=(6, 4))
        xs = [t.rate for t in metrics.per_task]
        ys = [t.total_cost for t in metrics.per_task]
        ax.scatter(xs, ys, c="#3b6d9a")
        ax.set_xlabel("success rate")
        ax.set_ylabel("cost (USD)")
        ax.set_title("Cost versus success (one point per task)")
        charts["scatter"] = _png(fig)
    return charts


def _injected_count(result: RunResult) -> int:
    return sum(1 for step in result.trace.steps if step.tool_call and step.tool_call.injected_fault)


def v2_extras(suite: SuiteResult) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    failed = 0
    localized = 0
    review = 0
    buckets: dict[int, list[bool]] = {}
    for result in suite.results:
        if result.needs_human_review:
            review += 1
        for grade in result.grades:
            if grade.tier == 1 and not grade.passed:
                violations.append(
                    {
                        "task_id": result.trace.task_id,
                        "attempt": result.trace.attempt,
                        "success": result.success,
                        "grader": grade.grader,
                        "detail": grade.detail,
                    }
                )
        if not result.success:
            failed += 1
            notes = [g for g in result.grades if g.tier == 2]
            if any(
                parse_divergence(g) and parse_divergence(g).get("divergence_step") is not None
                for g in notes
            ):
                localized += 1
        n_faults = _injected_count(result)
        buckets.setdefault(n_faults, []).append(result.success)
    recovery = []
    for n in sorted(buckets):
        rows = buckets[n]
        recovery.append({"injected_faults": n, "n": len(rows), "rate": sum(rows) / len(rows)})
    return {
        "tier1_violations": violations,
        "tier2_failed": failed,
        "tier2_localized": localized,
        "needs_human_review": review,
        "recovery": recovery,
    }


def _recovery_chart(recovery: list[dict[str, Any]]) -> str | None:
    if len(recovery) < 2:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [row["injected_faults"] for row in recovery]
    ys = [row["rate"] for row in recovery]
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(xs, ys, marker="o", color="#3b6d9a")
    ax.set_ylim(0, 1)
    ax.set_xlabel("injected faults on the attempt")
    ax.set_ylabel("success rate")
    ax.set_title("Recovery curve (uniform random failure is the weaker model)")
    return _png(fig)


def render_report(suite: SuiteResult, out_path: Path | None = None) -> str:
    metrics = aggregate(suite)
    prog, judge = paired_from_results(suite.results)
    agree = agreement_report(prog, judge)
    extras = v2_extras(suite)
    charts = _charts(metrics)
    recovery = _recovery_chart(extras["recovery"])
    if recovery:
        charts["recovery"] = recovery
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("report.html.j2")
    html = template.render(
        suite=suite,
        metrics=metrics,
        agree=agree,
        charts=charts,
        config=suite.config,
        extras=extras,
    )
    if out_path:
        out_path.write_text(html, encoding="utf-8")
    return html


def metrics_to_dict(metrics: SuiteMetrics) -> dict[str, Any]:
    return {
        "run_id": metrics.run_id,
        "n_tasks": metrics.n_tasks,
        "n_attempts": metrics.n_attempts,
        "suite_success_rate": metrics.suite_success_rate,
        "suite_wilson": [metrics.suite_wilson_lo, metrics.suite_wilson_hi],
        "total_cost": metrics.total_cost,
        "cost_per_completed_task": metrics.cost_per_completed_task,
        "cost_per_success": metrics.cost_per_success,
        "p50_ms": metrics.p50_ms,
        "p95_ms": metrics.p95_ms,
        "failures": metrics.failures,
        "termination": metrics.termination,
        "harness_error_rate": metrics.harness_error_rate,
        "per_category": metrics.per_category,
        "per_task": [t.__dict__ for t in metrics.per_task],
    }
