from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from aeh.execution.runner import (
    SuiteRunner,
    dry_run_estimate,
    ensure_fixture_db,
    replay_and_regrade,
)
from aeh.grading.agreement import agreement_report, paired_from_results
from aeh.logging.tree_logger import CATEGORIES, TreeLogger
from aeh.metrics.aggregate import aggregate
from aeh.metrics.compare import compare_runs
from aeh.report.html import metrics_to_dict, render_report
from aeh.report.trace_tree import render_trace_tree
from aeh.storage.db import RunStore
from aeh.tasks.loader import REPO_ROOT, validate_suite

app = typer.Typer(help="Agent Eval Harness — a test runner for non-deterministic software.")
tasks_app = typer.Typer(help="Inspect and validate task suites.")
app.add_typer(tasks_app, name="tasks")
console = Console()


def _db(path: Path | None) -> RunStore:
    return RunStore(path or (REPO_ROOT / "runs.db"))


def _csv_set(value: str | None) -> set[str] | None:
    if not value:
        return None
    items = {part.strip() for part in value.split(",") if part.strip()}
    unknown = items - set(CATEGORIES)
    if unknown:
        console.print(f"unknown log categories: {sorted(unknown)}")
        raise typer.Exit(code=2)
    return items


def _print_summary(suite, as_json: bool) -> None:
    metrics = aggregate(suite)
    if as_json:
        console.print_json(
            data={"run_id": suite.run_id, "config": suite.config, **metrics_to_dict(metrics)}
        )
        return
    table = Table(title=f"run {suite.run_id}")
    table.add_column("category")
    table.add_column("success")
    table.add_column("wilson 95%")
    table.add_column("tasks")
    for cat, info in sorted(metrics.per_category.items()):
        table.add_row(
            cat,
            f"{info['rate'] * 100:.1f}%",
            f"[{info['wilson_lo'] * 100:.1f}, {info['wilson_hi'] * 100:.1f}]",
            str(info["n_tasks"]),
        )
    console.print(table)
    cps = f"${metrics.cost_per_success:.4f}" if metrics.cost_per_success is not None else "n/a"
    console.print(
        f"suite {metrics.suite_success_rate * 100:.1f}% "
        f"[{metrics.suite_wilson_lo * 100:.1f}, {metrics.suite_wilson_hi * 100:.1f}]  "
        f"n={metrics.n_tasks} tasks / {metrics.n_attempts} attempts  "
        f"cost/success={cps}  p95={metrics.p95_ms:.0f}ms  "
        f"harness_errors={metrics.harness_error_rate * 100:.1f}%"
    )
    if metrics.failures:
        console.print(f"failures: {metrics.failures}")
    if metrics.termination:
        console.print(f"terminated_by: {metrics.termination}")


@app.command()
def run(
    suite: str = typer.Option("smoke", help="Suite name, path, or entry point"),
    adapter: str = typer.Option("mock", help="mock | react | single_shot | replay"),
    model: str = typer.Option("gpt-4o-mini"),
    attempts: int = typer.Option(1, min=1),
    concurrency: int = typer.Option(2, min=1),
    tasks: str | None = typer.Option(None, help="Comma-separated task ids"),
    fault_profile: Path | None = typer.Option(None),
    seed: int = typer.Option(42),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_out: bool = typer.Option(False, "--json"),
    db: Path | None = typer.Option(None),
    mock_auto_satisfy: bool = typer.Option(True),
    log_level: str = typer.Option("progress", "--log-level"),
    log_only: str | None = typer.Option(None, "--log-only"),
    log_exclude: str | None = typer.Option(None, "--log-exclude"),
    log_format: str = typer.Option("pretty", "--log-format"),
    no_redact: bool = typer.Option(False, "--no-redact"),
) -> None:
    """Run a suite. --dry-run validates and estimates cost without calling a model."""
    ensure_fixture_db()
    task_ids = [t.strip() for t in tasks.split(",") if t.strip()] if tasks else None
    if dry_run:
        estimate = dry_run_estimate(suite, model, attempts, task_ids)
        if json_out:
            console.print_json(data=estimate)
        else:
            console.print(estimate)
        return
    profile = {}
    if fault_profile:
        import yaml

        profile = yaml.safe_load(fault_profile.read_text(encoding="utf-8")) or {}
    logger = TreeLogger(
        level="silent" if json_out and log_level == "progress" else log_level,
        categories=_csv_set(log_only),
        exclude=_csv_set(log_exclude),
        fmt=log_format,
    )
    runner = SuiteRunner(
        suite=suite,
        adapter_name=adapter,
        model=model,
        attempts=attempts,
        concurrency=concurrency,
        seed=seed,
        tasks_filter=task_ids,
        fault_profile=profile,
        db_path=db,
        mock_auto_satisfy=mock_auto_satisfy,
        logger=logger,
        redact=not no_redact,
    )
    use_bar = log_level == "progress" and log_format == "pretty" and not json_out
    if use_bar:
        with Progress(console=console, disable=False) as progress:
            bar = progress.add_task("running", total=1)

            def cb(done, total, task_id, attempt, success):
                progress.update(
                    bar,
                    total=total,
                    completed=done,
                    description=f"{task_id}#{attempt} {'ok' if success else 'fail'}",
                )

            suite_result = asyncio.run(runner.run(progress_cb=cb))
    else:
        suite_result = asyncio.run(runner.run())
    _print_summary(suite_result, json_out)


@app.command()
def replay(
    run_id: str = typer.Option(..., "--run-id"),
    db: Path | None = typer.Option(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Re-grade recorded traces. No network."""
    store = _db(db)
    ensure_fixture_db()
    suite_result = asyncio.run(replay_and_regrade(store, run_id))
    _print_summary(suite_result, json_out)


@app.command()
def report(
    run_id: str = typer.Option(..., "--run-id"),
    out: Path = typer.Option(Path("report.html"), "--out"),
    db: Path | None = typer.Option(None),
) -> None:
    store = _db(db)
    suite_result = store.load_run(run_id)
    render_report(suite_result, out)
    console.print(f"wrote {out}")


@app.command()
def compare(
    run_a: str = typer.Argument(...),
    run_b: str = typer.Argument(...),
    db: Path | None = typer.Option(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    store = _db(db)
    counts_a = store.task_counts(run_a)
    counts_b = store.task_counts(run_b)
    cfg_a = store.run_config(run_a)
    cfg_b = store.run_config(run_b)
    suite_a = store.load_run(run_a)
    suite_b = store.load_run(run_b)
    m_a = aggregate(suite_a)
    m_b = aggregate(suite_b)
    report_ = compare_runs(
        counts_a,
        counts_b,
        run_a=run_a,
        run_b=run_b,
        cost_a=m_a.total_cost,
        cost_b=m_b.total_cost,
        p95_a=m_a.p95_ms,
        p95_b=m_b.p95_ms,
        judge_a=cfg_a.get("judge_model"),
        judge_b=cfg_b.get("judge_model"),
        prompt_version_a=cfg_a.get("tier2_prompt_version"),
        prompt_version_b=cfg_b.get("tier2_prompt_version"),
    )
    if json_out:
        console.print_json(data=report_.to_dict())
        return
    console.print(f"improved: {report_.improved or '—'}")
    console.print(f"regressed: {report_.regressed or '—'}")
    console.print(f"unchanged: {len(report_.unchanged)} tasks")
    console.print(f"cost Δ ${report_.cost_delta:.4f}  p95 Δ {report_.p95_delta_ms:.0f}ms")
    for warning in report_.warnings:
        console.print(f"[yellow]{warning}[/yellow]")


@app.command("judge-agreement")
def judge_agreement(
    run_id: str = typer.Option(..., "--run-id"),
    db: Path | None = typer.Option(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    store = _db(db)
    suite_result = store.load_run(run_id)
    prog, judge = paired_from_results(suite_result.results)
    report_ = agreement_report(prog, judge)
    payload = {
        "n": report_.n,
        "raw_agreement": report_.raw_agreement,
        "kappa": report_.kappa,
        "confusion": report_.confusion.__dict__,
        "headline": report_.headline,
    }
    if json_out:
        console.print_json(data=payload)
        return
    console.print(report_.headline)
    console.print(payload)


@app.command()
def trace(
    run_id: str = typer.Option(..., "--run-id"),
    task: str = typer.Option(..., "--task"),
    attempt: int = typer.Option(0, "--attempt"),
    out: Path = typer.Option(Path("trace.html"), "--out"),
    db: Path | None = typer.Option(None),
) -> None:
    """Write a self-contained HTML span tree for one recorded attempt."""
    store = _db(db)
    result = store.load_attempt(run_id, task, attempt)
    render_trace_tree(result, out)
    console.print(f"wrote {out}")


@tasks_app.command("list")
def tasks_list(suite: str | None = typer.Option(None)) -> None:
    tasks = validate_suite(suite) if suite else validate_suite()
    table = Table(title="tasks")
    table.add_column("id")
    table.add_column("suite")
    table.add_column("category")
    table.add_column("difficulty")
    table.add_column("tools")
    for task in tasks:
        table.add_row(
            task.id, task.suite, task.category, str(task.difficulty), ",".join(task.tools)
        )
    console.print(table)
    console.print(f"{len(tasks)} tasks")


@tasks_app.command("validate")
def tasks_validate(suite: str | None = typer.Option(None)) -> None:
    tasks = validate_suite(suite)
    console.print(f"ok: {len(tasks)} tasks validated")


if __name__ == "__main__":
    app()
