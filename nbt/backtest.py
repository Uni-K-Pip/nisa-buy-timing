from datetime import time
from itertools import product

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from . import score, validation
from .calendar import DAY, add_business_days, is_order_day
from .stats import stable_seed, summarize

WINDOWS = (20, 40, 60, 120)
COUNTS = (1, 2, 3, 4, 6)
THRESHOLDS = (60, 70, 80)
ML_THRESHOLD = 0.4
PULL_FORWARD_BONUS = 15
PULL_FORWARD_MAX = 95
GRID_PERIODS = ("all", "nav", "recent_3y")
COMPARISONS = ("regular", "lump", "placebo")
DESCRIPTION = (
    "注文できる国内営業日（銘柄ごとの休場日を除く）で数え、5位置ごとに検証期間を始めます。"
    "朝の判断時点のスコアまたはウォークフォワードの確率で判断し、締切が7:30以前なら次の注文可能日に注文します。"
    "銘柄ごとの約定日数だけ国内営業日を進めた確定値で約定すると仮定し、同額購入の平均単価を比べます。"
    "約定値とシグナルが全位置でそろった期間を集計し、一括はスコア戦略と同じ期間で比べます。"
    "偽シグナルは、開始が期間の長さ以上離れた期間から買う位置の並びを借り、その単価を平均した比較相手です。"
    "全期間は代理系列による延長を含み、基準価額のある期間と直近3年は開始日で絞ります。"
    "過去は最後の約定日が版の基準日以前、前向きは開始日が基準日より後の期間です。"
    "平均の95%区間は、開始順に並べた期間を期間の長さの約2倍相当の連続ブロックで復元抽出し、"
    "2,000回の平均の2.5%点と97.5%点で求めます。"
    "判定日は補正後の水準で50,000回の抽出を行い、重ならない期間のt区間も使います。差が負なら安く買えています。"
)


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
                limit = threshold if day >= start else min(threshold + PULL_FORWARD_BONUS, PULL_FORWARD_MAX)
                if value >= limit:
                    break
        days.append(day)
    return days


def average_cost(prices, days):
    fills = np.take_along_axis(prices, np.asarray(days), axis=-1)
    return fills.shape[-1] / np.reciprocal(fills).sum(axis=-1)


def _execution_day(day, lag, early, closed):
    if early:
        day += DAY
        while not is_order_day(day, closed):
            day += DAY
    return add_business_days(day, lag)


def execution_prices(price, fund):
    closed = fund.get("order_closed_calendars", ())
    params = fund["settlement"]
    early = time.fromisoformat(params["order_cutoff_jst"]) <= time(7, 30)
    orderable = np.array([is_order_day(day.date(), closed) for day in price.index], dtype=bool)
    dates = price.index[orderable & np.isfinite(price.to_numpy(dtype=float))].sort_values()
    fill_dates = pd.DatetimeIndex([
        _execution_day(day.date(), params["trade_lag_bd"], early, closed) for day in dates
    ])
    return pd.DataFrame({"last_fill": fill_dates, "price": price.reindex(fill_dates).to_numpy(dtype=float)}, index=dates)


def _difference(ratio):
    return np.where(np.isclose(ratio, 1, rtol=1e-12, atol=0), 0.0, (ratio - 1) * 100)


def placebo_differences(reciprocal, starts, bought, regular_cost, window):
    result = np.full(len(starts), np.nan)
    if not len(starts):
        return result
    left = np.searchsorted(starts, starts - window, side="right")
    right = np.searchsorted(starts, starts + window)
    eligible = len(starts) - (right - left)
    patterns, frequencies = np.unique(bought, axis=0, return_counts=True)
    near = left[:, None] + np.arange((right - left).max())
    overlaps = near < right[:, None]
    near = np.minimum(near, len(starts) - 1)
    count = bought.shape[1]
    # 同じ位置の並びをまとめ、重なる期間の寄与だけを差し引く。
    for offset in range(0, len(starts), 128):
        batch = slice(offset, offset + 128)
        paths = reciprocal[batch]
        total = sum(paths[:, days] for days in patterns.T)
        total = (count / total * frequencies).sum(axis=1)
        nearby = np.take_along_axis(paths[:, None, :], bought[near[batch]], axis=2).sum(axis=2)
        total -= np.where(overlaps[batch], count / nearby, 0).sum(axis=1)
        mask = eligible[batch] > 0
        ratio = np.divide(total, eligible[batch] * regular_cost[batch], out=np.full(len(paths), np.nan), where=mask)
        result[batch] = _difference(ratio)
    return result


class WindowResults:
    def __init__(self, rows, prices, bought, regular_cost, window):
        self.rows = rows
        self.reciprocal = np.reciprocal(prices)
        self.bought = bought
        self.regular_cost = regular_cost
        self.window = window

    def comparisons(self, mask=None):
        mask = slice(None) if mask is None else np.asarray(mask)
        rows = self.rows.iloc[mask].copy()
        placebo = placebo_differences(
            self.reciprocal[mask], rows.index.to_numpy(), self.bought[mask],
            self.regular_cost[mask], self.window,
        )
        rows["placebo"] = rows["regular"] - placebo
        return rows


def window_results(fills, signal, window, count, threshold=None, *, strategy="score"):
    if len(fills) >= window:
        prices = sliding_window_view(fills["price"].to_numpy(), window)[::5]
        signals = sliding_window_view(signal.reindex(fills.index).to_numpy(dtype=float), window)[::5]
        complete = np.isfinite(prices).all(axis=1) & np.isfinite(signals).all(axis=1)
        starts = np.flatnonzero(complete) * 5
        prices, signals = prices[complete], signals[complete]
    else:
        starts = np.empty(0, dtype=int)
        prices, signals = np.empty((0, window)), np.empty((0, window))
    bounds = intervals(window, count)
    regular = np.broadcast_to([start for start, _ in bounds], (len(starts), count))
    if strategy == "lump":
        bought = np.zeros((len(starts), 1), dtype=int)
    else:
        bought = np.asarray([
            decision_days(bounds, path, threshold, ml=strategy == "ml") for path in signals
        ], dtype=int).reshape(-1, count)
    cost = average_cost(prices, bought)
    regular_cost = average_cost(prices, regular)
    rows = pd.DataFrame({
        "date": fills.index[starts], "last_fill": fills["last_fill"].iloc[starts + window - 1].to_numpy(),
        "regular": _difference(cost / regular_cost), "lump": _difference(cost / prices[:, 0]),
        "delay": bought.mean(axis=1) - regular.mean(axis=1),
    }, index=starts)
    return WindowResults(rows, prices, bought, regular_cost, window)


def _grid_statistics(results, period_starts, seed_parts, draws, *, lump=False):
    rows = results.rows if lump else results.comparisons()
    periods = {}
    for period, start in period_starts.items():
        subset = rows.loc[rows["date"] >= start] if start is not None else rows.iloc[:0]
        summary = summarize(subset["regular"], results.window, stable_seed(*seed_parts, "regular", period), draws)
        if not lump:
            summary["delay"] = subset["delay"].mean() if len(subset) else None
            for comparison in COMPARISONS[1:]:
                stats = summarize(subset[comparison], results.window, stable_seed(*seed_parts, comparison, period), draws)
                summary[f"vs_{comparison}"] = {key: value for key, value in stats.items() if key not in ("count", "independent")}
        periods[period] = summary
    return periods


def _grid_summary(grid):
    summary = {}
    for strategy in ("score", "ml"):
        conditions = grid if strategy == "score" else grid[::len(THRESHOLDS)]
        summary[strategy] = {}
        for comparison in COMPARISONS:
            results = [row[strategy]["all"] for row in conditions]
            intervals = [result["ci"] if comparison == "regular" else result[f"vs_{comparison}"]["ci"] for result in results]
            available = [ci for ci in intervals if ci is not None]
            summary[strategy][comparison] = {
                "favorable": sum(ci[1] < 0 for ci in available),
                "unfavorable": sum(ci[0] > 0 for ci in available),
                "total": len(available),
            }
    return summary


def _estimate_impact(fills, scores, confirmed, nav_start, primary):
    if nav_start is None:
        return None
    paired = np.isfinite(scores) & np.isfinite(confirmed)
    estimate, actual = scores.where(paired), confirmed.where(paired)
    dates = paired & (paired.index >= nav_start)
    estimated_days, actual_days = estimate.loc[dates], actual.loc[dates]
    absolute = (estimated_days - actual_days).abs()
    result = dict.fromkeys(("score_abs_diff_mean", "score_abs_diff_p95", "category_mismatch_rate", "threshold_mismatch_rate"))
    result["days"] = len(absolute)
    if len(absolute):
        result.update(
            score_abs_diff_mean=absolute.mean(), score_abs_diff_p95=absolute.quantile(0.95),
            category_mismatch_rate=np.mean([
                score.category(a)[0] != score.category(b)[0] for a, b in zip(estimated_days, actual_days)
            ]) * 100,
            threshold_mismatch_rate=(estimated_days.ge(70) != actual_days.ge(70)).mean() * 100,
        )
    primary_means = {}
    for key, signal in (("with_estimate", estimate), ("with_confirmed", actual)):
        rows = window_results(fills, signal, **primary).rows
        eligible = rows.loc[rows["date"] >= nav_start, "regular"]
        primary_means[key] = eligible.mean() if len(eligible) else None
    a, b = primary_means.values()
    result["primary"] = primary_means | {"difference": a - b if a is not None and b is not None else None}
    return result


def _grid(fills, signals, probabilities, start_dates, fund_id, draws):
    grid = []
    for window, count in product(WINDOWS, COUNTS):
        common = (window, count)
        lump = _grid_statistics(
            window_results(fills, signals, *common, strategy="lump"), start_dates, (fund_id, "lump", *common, None), draws, lump=True,
        )
        ml = _grid_statistics(
            window_results(fills, probabilities, *common, ML_THRESHOLD, strategy="ml"),
            start_dates, (fund_id, "ml", *common, ML_THRESHOLD), draws,
        )
        for threshold in THRESHOLDS:
            score_stats = _grid_statistics(
                window_results(fills, signals, *common, threshold), start_dates, (fund_id, "score", *common, threshold), draws,
            )
            grid.append({
                "window": window, "count": count, "threshold": threshold,
                "score": score_stats, "lump": lump, "ml": ml,
            })
    return grid


def _period_ranges(dates, starts):
    periods = {}
    for name, start in starts.items():
        matching = dates[dates >= start] if start is not None else dates[:0]
        periods[name] = {
            "from": matching[0].date().isoformat(), "to": matching[-1].date().isoformat(),
        } if len(matching) else None
    return periods


def compare(price, signals, probabilities, *, fund, confirmed_scores=None, nav_start=None, registration=None, today=None):
    registration = validation.load_registration(registration)
    price = price.sort_index()
    last = price.index[-1]
    today = today if today is not None else last.date()
    nav_start = pd.Timestamp(nav_start) if nav_start is not None else None
    start_dates = dict(zip(GRID_PERIODS, (price.index[0], nav_start, last - pd.DateOffset(years=3))))
    fills = execution_prices(price, fund)
    fund_id = fund["id"]
    protocol = registration["protocol"]
    grid = _grid(fills, signals, probabilities, start_dates, fund_id, protocol["bootstrap_draws"])
    strategies = {}
    for entry in registration["strategies"]:
        strategy, primary = entry["id"], entry["primary"]
        signal = signals if strategy == "score" else probabilities
        threshold = primary.get("threshold") if strategy == "score" else primary["probability_at_most"]
        results = window_results(fills, signal, primary["window"], primary["count"], threshold, strategy=strategy)
        strategies[strategy] = validation.evidence(
            fund_id, entry, protocol, results, nav_start, last, today, COMPARISONS,
        )
    primary = next((entry["primary"] for entry in registration["strategies"] if entry["id"] == "score"),
                   {"window": 40, "count": 3, "threshold": 70})
    return {
        "schema": 2, "description": DESCRIPTION, "ml_probability_at_most": ML_THRESHOLD,
        "periods": _period_ranges(price.index, start_dates), "grid": grid, "grid_summary": _grid_summary(grid),
        "evidence": {"protocol": validation.public_protocol(protocol), "strategies": strategies},
        "estimate_impact": _estimate_impact(fills, signals, confirmed_scores, nav_start, primary),
    }
