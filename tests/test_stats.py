import numpy as np
import pytest
from scipy.stats import t

from nbt.stats import mean_interval, non_overlapping, stable_seed, statistic_interval, t_interval


def test_bootstrap_repeats_and_keeps_serial_dependence():
    rng = np.random.default_rng(812)
    values = np.repeat(rng.normal(size=120), 16)
    seed = stable_seed("demo", "score", "all")
    blocked = mean_interval(values, 16, seed=seed)
    unblocked = mean_interval(values, 1, seed=seed)
    assert blocked == mean_interval(values, 16, seed=seed)
    assert blocked[1] - blocked[0] > 2 * (unblocked[1] - unblocked[0])
    assert stable_seed("ab", "c") != stable_seed("a", "bc")
    assert mean_interval(values[:31], 16) is None
    assert statistic_interval(31, 16, lambda rows: rows.mean()) is None


def test_circular_blocks_trim_last_block_and_skip_nan_statistics():
    values = np.arange(31, dtype=float)
    seed = 54
    direct = statistic_interval(len(values), 5, lambda rows: values[rows].mean(), seed=seed)
    assert mean_interval(values, 5, seed=seed) == pytest.approx(direct)
    sampled = []

    def statistic(rows):
        sampled.append(rows)
        return np.nan if len(sampled) % 2 else rows.mean()

    result = statistic_interval(len(values), 5, statistic, draws=20, seed=seed)
    assert all(len(row) == 31 for row in sampled)
    assert any(np.any(np.diff(row[:5]) == -30) for row in sampled)
    assert result == pytest.approx(np.quantile([row.mean() for row in sampled[1::2]], [0.025, 0.975]))
    assert statistic_interval(31, 5, lambda _: np.nan, draws=5) is None


def test_non_overlapping_and_t_interval():
    np.testing.assert_array_equal(non_overlapping([0, 5, 10, 25, 45, 50], 20), [0, 25, 45])
    assert t_interval([1]) is None
    assert t_interval([1, 3]) == pytest.approx([2 - t.ppf(0.975, 1), 2 + t.ppf(0.975, 1)])
