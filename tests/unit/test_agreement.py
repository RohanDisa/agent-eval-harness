from aeh.grading.agreement import (
    agreement_report,
    cohens_kappa,
    confusion_matrix,
    paired_from_results,
)
from aeh.models import GradeResult, RunResult, Trace


def test_perfect_agreement_kappa_one():
    matrix = confusion_matrix([True, True, False, False], [True, True, False, False])
    assert cohens_kappa(matrix) == 1.0
    report = agreement_report([True, False], [True, False])
    assert report.kappa == 1.0


def test_lenient_judge_shows_up_as_fp():
    matrix = confusion_matrix([False, False], [True, True])
    assert matrix.fp == 2
    assert matrix.fn == 0
    assert cohens_kappa(matrix) <= 0


def test_empty_overlap():
    report = agreement_report([], [])
    assert report.n == 0
    assert "no overlap" in report.headline


def test_paired_from_results():
    def run(prog: bool, judge: bool) -> RunResult:
        return RunResult(
            trace=Trace(
                run_id="r",
                task_id="t",
                attempt=0,
                seed=0,
                adapter="m",
                model="m",
                terminated_by="completed",
                wall_clock_ms=1,
            ),
            grades=[
                GradeResult(grader="exact", passed=prog, score=1.0 if prog else 0.0, detail=""),
                GradeResult(grader="judge", passed=judge, score=1.0 if judge else 0.0, detail=""),
            ],
            success=prog,
        )

    p, j = paired_from_results([run(True, False), run(True, True)])
    assert p == [True, True]
    assert j == [False, True]
