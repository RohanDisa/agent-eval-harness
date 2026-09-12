from aeh.metrics.compare import benjamini_hochberg, compare_runs, two_proportion_pvalue


def test_two_proportion_identical_is_one():
    assert two_proportion_pvalue(5, 10, 5, 10) == 1.0


def test_two_proportion_known_separation():
    p = two_proportion_pvalue(9, 10, 1, 10)
    assert p < 0.01


def test_bh_known_values():
    # Classic example: p = [0.01, 0.04, 0.03, 0.20] alpha=0.05
    mask = benjamini_hochberg([0.01, 0.04, 0.03, 0.20], alpha=0.05)
    assert mask[0] is True
    assert mask[3] is False


def test_compare_flags_regression_only_when_significant_and_dropped():
    # 10/10 vs 2/10 is a real drop; 5/10 vs 4/10 is noise
    report = compare_runs(
        {"big": (10, 10), "tiny": (5, 10)},
        {"big": (2, 10), "tiny": (4, 10)},
        run_a="a",
        run_b="b",
        judge_a="m1",
        judge_b="m2",
        prompt_version_a="golden-divergence-v1",
        prompt_version_b="golden-divergence-v2",
    )
    assert "big" in report.regressed
    assert "tiny" in report.unchanged
    assert report.judge_model_changed
    assert report.warnings
    assert any("prompt version" in w.lower() for w in report.warnings)


def test_compare_improvement():
    report = compare_runs(
        {"x": (1, 10)},
        {"x": (9, 10)},
        run_a="a",
        run_b="b",
    )
    assert "x" in report.improved
