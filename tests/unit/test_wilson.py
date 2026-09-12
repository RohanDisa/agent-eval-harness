from aeh.metrics.aggregate import percentile, wilson_interval


def test_wilson_hand_computed_k0_n10():
    point, lo, hi = wilson_interval(0, 10)
    assert point == 0.0
    # center = 1.9208/13.8416 ≈ 0.1388; half ≈ 0.1388 → lo≈0
    assert lo == pytest_approx(0.0, abs=1e-9)
    assert 0.25 < hi < 0.35


def test_wilson_hand_computed_kn_n10():
    point, lo, hi = wilson_interval(10, 10)
    assert point == 1.0
    assert 0.65 < lo < 0.80
    assert hi == pytest_approx(1.0, abs=1e-9)


def test_wilson_k5_n10():
    point, lo, hi = wilson_interval(5, 10)
    assert point == 0.5
    # Published Wilson 95% for 5/10 is about [0.236, 0.764]
    assert abs(lo - 0.23659) < 0.005
    assert abs(hi - 0.76341) < 0.005


def test_wilson_n_zero():
    point, lo, hi = wilson_interval(0, 0)
    assert point == 0.0
    assert lo == 0.0
    assert hi == 1.0


def test_percentile_edges():
    assert percentile([], 50) == 0.0
    assert percentile([3.0], 50) == 3.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 100) == 4.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5


def pytest_approx(value, abs):  # local helper name used above — use pytest.approx
    import pytest

    return pytest.approx(value, abs=abs)
