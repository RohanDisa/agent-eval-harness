"""Did this change make things better, or is the difference noise?"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def _phi(z: float) -> float:
    """Standard normal CDF via erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_proportion_pvalue(k1: int, n1: int, k2: int, n2: int) -> float:
    if n1 <= 0 or n2 <= 0:
        return 1.0
    p1 = k1 / n1
    p2 = k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (p1 - p2) / se
    return 2.0 * (1.0 - _phi(abs(z)))


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """Return a mask of discoveries after BH correction."""
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    rejected = [False] * m
    max_i = -1
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= (rank / m) * alpha:
            max_i = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= max_i:
            rejected[idx] = True
    return rejected


@dataclass
class TaskDelta:
    task_id: str
    k_a: int
    n_a: int
    k_b: int
    n_b: int
    rate_a: float
    rate_b: float
    pvalue: float
    significant: bool
    verdict: str  # improved | regressed | unchanged


@dataclass
class CompareReport:
    run_a: str
    run_b: str
    improved: list[str]
    regressed: list[str]
    unchanged: list[str]
    cost_delta: float
    p95_delta_ms: float
    judge_model_changed: bool
    warnings: list[str] = field(default_factory=list)
    tasks: list[TaskDelta] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_a": self.run_a,
            "run_b": self.run_b,
            "improved": self.improved,
            "regressed": self.regressed,
            "unchanged": self.unchanged,
            "cost_delta": self.cost_delta,
            "p95_delta_ms": self.p95_delta_ms,
            "judge_model_changed": self.judge_model_changed,
            "warnings": self.warnings,
            "tasks": [t.__dict__ for t in self.tasks],
        }


def compare_runs(
    counts_a: dict[str, tuple[int, int]],
    counts_b: dict[str, tuple[int, int]],
    *,
    run_a: str,
    run_b: str,
    cost_a: float = 0.0,
    cost_b: float = 0.0,
    p95_a: float = 0.0,
    p95_b: float = 0.0,
    judge_a: str | None = None,
    judge_b: str | None = None,
    prompt_version_a: str | None = None,
    prompt_version_b: str | None = None,
    alpha: float = 0.05,
) -> CompareReport:
    shared = sorted(set(counts_a) & set(counts_b))
    pvalues: list[float] = []
    raw: list[TaskDelta] = []
    for task_id in shared:
        k_a, n_a = counts_a[task_id]
        k_b, n_b = counts_b[task_id]
        p = two_proportion_pvalue(k_a, n_a, k_b, n_b)
        rate_a = k_a / n_a if n_a else 0.0
        rate_b = k_b / n_b if n_b else 0.0
        pvalues.append(p)
        raw.append(
            TaskDelta(
                task_id=task_id,
                k_a=k_a,
                n_a=n_a,
                k_b=k_b,
                n_b=n_b,
                rate_a=rate_a,
                rate_b=rate_b,
                pvalue=p,
                significant=False,
                verdict="unchanged",
            )
        )
    discoveries = benjamini_hochberg(pvalues, alpha=alpha)
    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []
    for delta, sig in zip(raw, discoveries, strict=True):
        delta.significant = sig
        dropped = delta.rate_b < delta.rate_a
        rose = delta.rate_b > delta.rate_a
        if sig and dropped:
            delta.verdict = "regressed"
            regressed.append(delta.task_id)
        elif sig and rose:
            delta.verdict = "improved"
            improved.append(delta.task_id)
        else:
            delta.verdict = "unchanged"
            unchanged.append(delta.task_id)
    warnings: list[str] = []
    judge_changed = bool(judge_a and judge_b and judge_a != judge_b)
    if judge_changed:
        warnings.append(
            f"Judge model changed ({judge_a} → {judge_b}); comparison across runs is invalid "
            "for any task graded by the judge."
        )
    if prompt_version_a and prompt_version_b and prompt_version_a != prompt_version_b:
        warnings.append(
            f"Tier-2 prompt version changed ({prompt_version_a} → {prompt_version_b}); "
            "divergence notes are not comparable across these runs."
        )
    return CompareReport(
        run_a=run_a,
        run_b=run_b,
        improved=improved,
        regressed=regressed,
        unchanged=unchanged,
        cost_delta=cost_b - cost_a,
        p95_delta_ms=p95_b - p95_a,
        judge_model_changed=judge_changed,
        warnings=warnings,
        tasks=raw,
    )
