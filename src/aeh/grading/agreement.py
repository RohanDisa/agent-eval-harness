"""Judge vs programmatic agreement. The highest-signal number in the project."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Confusion:
    tp: int
    tn: int
    fp: int
    fn: int

    @property
    def n(self) -> int:
        return self.tp + self.tn + self.fp + self.fn


@dataclass(frozen=True)
class AgreementReport:
    n: int
    raw_agreement: float
    kappa: float
    confusion: Confusion
    headline: str


def confusion_matrix(programmatic: list[bool], judge: list[bool]) -> Confusion:
    if len(programmatic) != len(judge):
        raise ValueError("paired labels must have the same length")
    tp = tn = fp = fn = 0
    for p, j in zip(programmatic, judge, strict=True):
        if p and j:
            tp += 1
        elif (not p) and (not j):
            tn += 1
        elif j and not p:
            fp += 1  # judge lenient
        else:
            fn += 1  # judge strict
    return Confusion(tp=tp, tn=tn, fp=fp, fn=fn)


def raw_agreement(matrix: Confusion) -> float:
    if matrix.n == 0:
        return 0.0
    return (matrix.tp + matrix.tn) / matrix.n


def cohens_kappa(matrix: Confusion) -> float:
    n = matrix.n
    if n == 0:
        return 0.0
    po = raw_agreement(matrix)
    p_prog_pos = (matrix.tp + matrix.fn) / n
    p_judge_pos = (matrix.tp + matrix.fp) / n
    pe = p_prog_pos * p_judge_pos + (1 - p_prog_pos) * (1 - p_judge_pos)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def agreement_report(programmatic: list[bool], judge: list[bool]) -> AgreementReport:
    matrix = confusion_matrix(programmatic, judge)
    kappa = cohens_kappa(matrix)
    raw = raw_agreement(matrix)
    if matrix.n == 0:
        headline = "no overlap set — judge was not compared to a programmatic grader"
    elif kappa < 0.7:
        headline = (
            f"Cohen's κ = {kappa:.2f} on n={matrix.n}. Below ~0.7 the judge is not trustworthy."
        )
    else:
        headline = f"Cohen's κ = {kappa:.2f} on n={matrix.n}."
    return AgreementReport(
        n=matrix.n,
        raw_agreement=raw,
        kappa=kappa,
        confusion=matrix,
        headline=headline,
    )


def paired_from_results(results: list) -> tuple[list[bool], list[bool]]:
    """For each attempt that has both a judge grade and at least one programmatic grade."""
    prog_labels: list[bool] = []
    judge_labels: list[bool] = []
    for result in results:
        grades = result.grades
        programmatic = [g for g in grades if g.grader != "judge" and not g.errored]
        judges = [g for g in grades if g.grader == "judge" and not g.errored]
        if not programmatic or not judges:
            continue
        prog_labels.append(all(g.passed for g in programmatic))
        judge_labels.append(all(g.passed for g in judges))
    return prog_labels, judge_labels
