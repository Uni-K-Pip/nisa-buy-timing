from itertools import product

import numpy as np
import pandas as pd

WINDOWS = (20, 40, 60, 120)
COUNTS = (1, 2, 3, 4, 6)
THRESHOLDS = (60, 70, 80)
ML_THRESHOLD = 0.4


def intervals(window, count):
    return [(k * window // count, (k + 1) * window // count - 1) for k in range(count)]


def decision_days(bounds, signal, threshold, *, ml=False):
    days = []
    for start, end in bounds:
        first = days[-1] + 1 if days and not ml else start
        for day in range(first, end + 1):
            value = signal[day]
            if day == end:
                break
            if ml and value <= threshold:
                break
            if not ml:
                limit = threshold if day >= start else min(threshold + 15, 95)
                if value >= limit:
                    break
        days.append(day)
    return days


def average_cost(prices, days):
    fills = prices[np.asarray(days) + 1]
    return len(fills) / np.reciprocal(fills).sum()


def statistics(values):
    count = len(values)
    if not count:
        return dict.fromkeys(("mean", "median", "win_rate", "p05", "p95")) | {"count": 0}
    values = np.asarray(values)
    low, median, high = np.percentile(values, (5, 50, 95))
    return {
        "count": count, "mean": values.mean(), "median": median, "win_rate": (values < 0).mean() * 100,
        "p05": low, "p95": high,
    }


def compare(price, signals, probabilities):
    prices = price.to_numpy(dtype=float)
    scores = signals.to_numpy()
    probs = probabilities.to_numpy()
    recent_from = price.index[-1] - pd.DateOffset(years=3)
    rows = []

    def difference(cost, regular):
        if np.isclose(cost, regular, rtol=1e-12, atol=0):
            return 0.0
        return (cost / regular - 1) * 100

    for window, count in product(WINDOWS, COUNTS):
        bounds = intervals(window, count)
        results = {key: [] for key in (*THRESHOLDS, "lump", "ml")}
        for start in range(0, len(prices) - window, 5):
            end = start + window
            score = scores[start:end]
            probability = probs[start:end]
            path = prices[start:end + 1]
            regular = average_cost(path, [first for first, _ in bounds])
            recent = price.index[start] >= recent_from
            if np.isfinite(probability).all():
                days = decision_days(bounds, probability, ML_THRESHOLD, ml=True)
                results["ml"].append((difference(average_cost(path, days), regular), recent))
            if np.isfinite(score).all():
                # 一括もスコア戦略と同じ期間の集まりで比べる。
                results["lump"].append((difference(path[1], regular), recent))
                for threshold in THRESHOLDS:
                    days = decision_days(bounds, score, threshold)
                    results[threshold].append((difference(average_cost(path, days), regular), recent))

        def summarize(key):
            values = results[key]
            return {
                "all": statistics([value for value, _ in values]),
                "recent_3y": statistics([value for value, recent in values if recent]),
            }

        lump, ml = summarize("lump"), summarize("ml")
        for threshold in THRESHOLDS:
            rows.append({
                "window": window, "count": count, "threshold": threshold,
                "score": summarize(threshold), "lump": lump, "ml": ml,
            })
    return {
        "description": "判断の翌国内営業日に約定と仮定し、同額で分けて購入した平均単価を比較。"
        "定期購入は各小区間の初日。期間は5営業日ごとに開始し、直近3年は開始日で集計。"
        "スコアと一括はスコアが全日そろう期間、MLは予測が全日そろう期間を集計。差がマイナスなら安く、同値は勝ちに含めません。",
        "ml_probability_at_most": ML_THRESHOLD,
        "grid": rows,
    }
