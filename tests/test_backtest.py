import numpy as np
import pandas as pd
import pytest

from nbt.backtest import average_cost, compare, execution_prices, window_results
from nbt.series import _domestic_range
from nbt.stats import mean_interval


def test_execution_uses_domestic_lag_and_excludes_order_holidays():
    dates = pd.to_datetime(["2026-12-23", "2026-12-24", "2026-12-25", "2026-12-28", "2026-12-29", "2026-12-30"])
    prices = pd.Series([100.0, 110.0, 120.0, 130.0, 140.0, 150.0], index=dates)
    fund = {"order_closed_calendars": ["NYSE"], "settlement": {"trade_lag_bd": 1, "order_cutoff_jst": "15:00"}}
    fills = execution_prices(prices, fund)
    assert fills.index.tolist() == dates[[0, 1, 3, 4, 5]].tolist()
    assert fills["last_fill"].tolist() == [*dates[[1, 2, 4, 5]], pd.Timestamp("2027-01-04")]
    np.testing.assert_equal(fills["price"].to_numpy(), [110, 120, 140, 150, np.nan])
    scores = pd.Series([0, 0, 100, 0, 90, 0], index=dates)
    results = window_results(fills, scores, 4, 1, 70)
    np.testing.assert_equal(results.bought, [[3]])
    assert results.rows.iloc[0]["regular"] == pytest.approx((150 / 110 - 1) * 100)

    fund["settlement"].update(trade_lag_bd=2, order_cutoff_jst="07:30")
    early = execution_prices(prices, fund)
    assert early.loc[dates[0], "last_fill"] == dates[3]
    assert early.loc[dates[1], "last_fill"] == dates[5]
    assert early.loc[dates[1], "price"] == 150
    assert np.isnan(early.loc[dates[3], "price"])
    missing = execution_prices(prices.drop(dates[5]), fund)
    assert np.isnan(missing.loc[dates[1], "price"])


def test_placebo_matches_every_non_overlapping_period():
    rng = np.random.default_rng(13)
    dates = pd.bdate_range("2020-01-01", periods=60)
    prices = rng.uniform(80, 120, len(dates))
    fills = pd.DataFrame({"price": prices, "last_fill": dates}, index=dates)
    scores = pd.Series(rng.uniform(0, 100, len(dates)), index=dates)
    scores.iloc[5] = np.nan
    window, count = 20, 3
    result = window_results(fills, scores, window, count, 70)
    rows = result.comparisons()
    for start, row in rows.iterrows():
        donor_days = result.bought[np.abs(rows.index - start) >= window]
        if not len(donor_days):
            assert np.isnan(row["placebo"])
            continue
        path = prices[start:start + window]
        regular = average_cost(path, [0, 6, 13])
        expected = np.mean([(average_cost(path, days) / regular - 1) * 100 for days in donor_days])
        assert row["placebo"] == pytest.approx(row["regular"] - expected, abs=1e-11)


def test_placebo_distinguishes_random_and_oracle_signals():
    rng = np.random.default_rng(521)
    window = 20
    prices = rng.uniform(90, 110, (220, window))
    gaps = np.full((len(prices), 5), np.nan)
    path = np.c_[prices, gaps].ravel()
    dates = pd.bdate_range("2000-01-01", periods=len(path))
    fills = pd.DataFrame({"price": path, "last_fill": dates}, index=dates)
    random_score = rng.uniform(0, 100, len(path))
    oracle_score = np.zeros_like(path)
    oracle_score[np.arange(len(prices)) * (window + 5) + prices.argmin(axis=1)] = 90

    def differences(signal):
        return window_results(fills, pd.Series(signal, index=dates), window, 1, 70).comparisons()["placebo"]

    random = differences(random_score)
    low, high = mean_interval(random, 8, seed=56)
    assert abs(random.mean()) < 0.5
    assert low < 0 < high
    oracle = differences(oracle_score)
    assert oracle.mean() < -5
    assert mean_interval(oracle, 8, seed=56)[1] < 0
    flat = fills.assign(price=np.where(np.isfinite(path), 100, np.nan))
    rows = window_results(flat, pd.Series(random_score, index=dates), window, 3, 70).comparisons()
    assert rows[["regular", "lump", "placebo"]].eq(0).all().all()


def test_grid_counts_ml_once_per_window_and_purchase_count():
    dates = _domestic_range(pd.Timestamp("2017-01-04"), pd.Timestamp("2020-01-04"))
    rng = np.random.default_rng(693)
    price = pd.Series(100 * np.exp(rng.normal(0, 0.01, len(dates)).cumsum()), index=dates)
    scores = pd.Series(rng.uniform(0, 100, len(dates)), index=dates)
    probabilities = pd.Series(rng.uniform(0, 1, len(dates)), index=dates)
    fund = {"id": "demo", "settlement": {"trade_lag_bd": 1, "order_cutoff_jst": "15:00"}}
    nav_start = dates[350]
    result = compare(price, scores, probabilities, fund=fund, confirmed_scores=scores, nav_start=nav_start)
    assert all(summary["total"] == 60 for summary in result["grid_summary"]["score"].values())
    assert all(summary["total"] == 20 for summary in result["grid_summary"]["ml"].values())
    impact = result["estimate_impact"]
    assert impact["days"] == len(dates) - 350
    assert impact["score_abs_diff_mean"] == impact["score_abs_diff_p95"] == 0
    assert impact["category_mismatch_rate"] == impact["threshold_mismatch_rate"] == 0
    assert impact["primary"]["difference"] == 0
