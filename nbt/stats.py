import zlib

import numpy as np
from scipy.stats import t


def stable_seed(*parts):
    return zlib.crc32("\0".join(map(str, parts)).encode("utf-8"))


def _quantiles(values, level):
    tail = (1 - level) / 2
    return tuple(np.quantile(values, [tail, 1 - tail])) if len(values) else None


def mean_interval(values, block_length, level=0.95, draws=2000, seed=0):
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2 * block_length:
        return None
    whole, remainder = divmod(n, block_length)
    prefix = np.r_[0, np.cumsum(np.r_[values, values[:block_length - 1]])]
    blocks = prefix[block_length:block_length + n] - prefix[:n]
    partial = prefix[remainder:remainder + n] - prefix[:n]
    rng = np.random.default_rng(seed)
    means = np.empty(draws)
    # 抽出回数が多くても、インデックスの一時配列を小さく保つ。
    for start in range(0, draws, 1024):
        batch = means[start:start + 1024]
        positions = rng.integers(n, size=(len(batch), whole + bool(remainder)))
        batch[:] = blocks[positions[:, :whole]].sum(axis=1)
        if remainder:
            batch += partial[positions[:, -1]]
    return _quantiles(means / n, level)


def statistic_interval(n, block_length, statistic, level=0.95, draws=2000, seed=0):
    if n < 2 * block_length:
        return None
    rng = np.random.default_rng(seed)
    offsets = np.arange(block_length)
    positions = rng.integers(n, size=(draws, (n + block_length - 1) // block_length))
    values = np.empty(draws)
    for i, starts in enumerate(positions):
        rows = (starts[:, None] + offsets).ravel()[:n] % n
        values[i] = statistic(rows)
    return _quantiles(values[~np.isnan(values)], level)


def t_interval(values, level=0.95):
    n = len(values)
    if n < 2:
        return None
    mean = np.mean(values)
    margin = t.ppf((1 + level) / 2, n - 1) * np.std(values, ddof=1) / np.sqrt(n)
    return mean - margin, mean + margin


def non_overlapping(starts, window):
    selected = []
    for start in starts:
        if not selected or start >= selected[-1] + window:
            selected.append(start)
    return np.asarray(selected, dtype=int)


def summarize(values, window, seed, draws=2000):
    values = values.dropna()
    if values.empty:
        return dict.fromkeys(("independent", "mean", "median", "win_rate", "p05", "p95", "ci")) | {"count": 0}
    low, median, high = np.percentile(values, (5, 50, 95))
    return {
        "count": len(values), "independent": len(non_overlapping(values.index, window)),
        "mean": values.mean(), "median": median, "win_rate": (values < 0).mean() * 100,
        "p05": low, "p95": high, "ci": mean_interval(values, (2 * window + 4) // 5, draws=draws, seed=seed),
    }
