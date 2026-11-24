import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nbt import backtest, explore, ml, validation
from nbt.series import _domestic_range

FUND = {"id": "demo", "short_name": "合成銘柄", "settlement": {"order_cutoff_jst": "15:00", "trade_lag_bd": 1}}


def test_every_target_including_missing_prices_and_flat_volatility():
    price = pd.Series([80.0, 90, 100, 105, 97, 102, 101, 98, 106, 110, 109, 113, 115, 94, 116, 117, 118,
                       119, 120, 101, 94, 100, 96, 104, 105, 106])
    outcome = explore.targets(price, 2)
    assert outcome.iloc[0].to_dict() == pytest.approx({
        "down20": 1.0, "ret5": -0.02, "ret10": 0.15, "ret20": -0.04,
        "drop3_10": 1.0, "drop5_10": 0.0, "drop3_20": 1.0, "drop5_20": 1.0,
        "low20": -0.06, "vol20": np.log(np.diff(np.log(price.iloc[2:23])).std(ddof=1) * np.sqrt(252)),
    })
    assert outcome.iloc[-3:].isna().all().all()
    missing = price.copy()
    missing.iloc[8] = np.nan
    result = explore.targets(missing, 2).iloc[0]
    ends = ["down20", "ret5", "ret10", "ret20"]
    assert result.dropna().to_dict() == outcome.iloc[0][ends].to_dict()
    pd.testing.assert_series_equal(explore.targets(missing, 2)["down20"], ml.targets(missing, 2), check_names=False)
    assert explore.targets(pd.Series(np.full(30, 100.0)), 1)["vol20"].isna().all()


@pytest.mark.parametrize("horizon", [5, 10, 20])
def test_walk_forward_uses_only_resolved_rows_and_their_mean(monkeypatch, horizon):
    monkeypatch.setattr(ml, "MIN_TRAIN", 5)
    monkeypatch.setattr(ml, "STEP", 4)
    n, lag = 40, 2
    outcome = np.arange(n, dtype=float) / 100
    outcome[5] = np.nan
    values = np.arange(n, dtype=float)[:, None]
    complete = np.ones(n, dtype=bool)
    complete[3] = False
    predictable = complete.copy()
    predictable[17] = False
    calls = []

    class Model:
        def fit(self, rows, labels):
            calls.append((rows[:, 0].astype(int), labels))
            return self

        def predict(self, rows):
            return rows[:, 0]

    predicted, means = ml.walk_forward(outcome, values, values, complete, predictable, lag, horizon, Model, binary=False)
    first = 7 + lag + horizon
    assert len(calls) == len(range(first, n, ml.STEP))
    for (rows, labels), as_of in zip(calls, range(first, n, ml.STEP)):
        expected = np.setdiff1d(np.arange(as_of - lag - horizon), [3, 5])
        np.testing.assert_array_equal(rows, expected)
        assert (rows + lag + horizon < as_of).all()
        end = min(as_of + ml.STEP, n)
        eligible = predictable[as_of:end]
        assert (means[as_of:end][eligible] == labels.mean()).all()
        np.testing.assert_array_equal(predicted[as_of:end][eligible], np.arange(as_of, end)[eligible])
    assert np.isnan(predicted[:first]).all()
    assert np.isnan(predicted[17])


def test_strategy_sign_and_equality_final_day_and_common_windows():
    days = _domestic_range(pd.Timestamp("2024-01-04"), pd.Timestamp("2025-01-31"))
    price = pd.Series(100 + np.arange(len(days)), index=days)
    baseline = np.full(len(days), 0.4)
    predictions = {
        model: {name: (baseline.copy(), baseline.copy()) for name in explore.TARGETS} for model in ("A", "B")
    }
    predictions["A"]["down20"][0][:explore.WINDOW] = 0.5
    predictions["A"]["ret5"][0][0:2] = [0.3, 0.5]
    predictions["A"]["low20"][0][0:2] = [0.3, 0.5]
    predictions["B"]["drop5_10"][0][105] = np.nan
    predictions["B"]["vol20"][0][:] = np.nan
    common, signals = explore.strategy_signals(days, predictions)
    assert not common[105] and common.sum() == len(days) - 1
    assert all(pd.isna(signal.iloc[105]) for signal, _ in signals.values())
    assert signals[("A", "down20", "baseline")][0].iloc[0] > 0
    for target in ("ret5", "low20"):
        rule = signals[("A", target, "baseline")][0]
        assert rule.iloc[0] > 0 > rule.iloc[1]
    fills = backtest.execution_prices(price, FUND)
    bought = {}
    for (model, target, rule), (signal, threshold) in signals.items():
        result = backtest.window_results(fills, signal, explore.WINDOW, explore.COUNT, threshold, strategy="ml")
        bought[(model, target, rule)] = result.bought[0].tolist()
    bounds = backtest.intervals(explore.WINDOW, explore.COUNT)
    assert bought[("A", "down20", "registered")] == [end for _, end in bounds]
    assert bought[("B", "down20", "registered")] == [start for start, _ in bounds]
    assert bought[("A", "ret5", "baseline")] == [1, bounds[1][0], bounds[2][0]]

    first = explore._strategy_evaluation(price, FUND, predictions, days[60], 32)
    second = explore._strategy_evaluation(price, FUND, predictions, days[60], 32)
    assert first == second
    assert len({(item["all"]["count"], item["nav"]["count"]) for item in first["results"].values()}) == 1
    assert first["model_difference"]["down20:registered"]["all"]["regular"]["ci"] is not None


def test_rank_correlation_uses_fixed_average_ranks():
    actual = np.array([0, 0, 0, 2, 3, 4])
    predicted = np.array([1, 2, 3, 2, 3, 4])
    rows = [0, 0, 1, 3, 4]
    actual_ranks = [2, 2, 2, 4, 5]
    predicted_ranks = [1, 1, 2.5, 2.5, 4.5]
    assert explore._rank_corr(actual, predicted)(rows) == pytest.approx(np.corrcoef(actual_ranks, predicted_ranks)[0, 1])


@pytest.mark.parametrize("oracle", [False, True])
def test_paired_predictions_and_report_on_synthetic_data(monkeypatch, oracle):
    monkeypatch.setattr(ml, "MIN_TRAIN", 45)
    days = _domestic_range(pd.Timestamp("2023-01-04"), pd.Timestamp("2025-05-31"))
    rng = np.random.default_rng(364)
    price = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(days)))), index=days)
    base = pd.DataFrame({"noise": rng.normal(size=len(days))}, index=days)
    extra_values = ml.targets(price).fillna(0.5) if oracle else rng.normal(size=len(days))
    extra = pd.DataFrame({"additional": extra_values}, index=days)
    reference = ml.experiment(price, base)[0]
    run = explore.run_info("2026-11-25T08:00:00+09:00", validation.load_registration())
    captured = []
    walk_forward = ml.walk_forward

    def record(outcome, training, inputs, complete, predictable, lag, horizon, *args, **kwargs):
        forecast, baseline = walk_forward(outcome, training, inputs, complete, predictable, lag, horizon, *args, **kwargs)
        captured.append((complete, predictable, np.isfinite(forecast), baseline))
        return forecast, baseline

    monkeypatch.setattr(ml, "walk_forward", record)
    result = explore.evaluate(FUND, price, base, base, extra, days[100], reference, {}, run, 52)
    for a, b in zip(captured[:10], captured[10:]):
        for a_values, b_values in zip(a, b):
            np.testing.assert_array_equal(a_values, b_values)
    assert result["reference_check"]["probability_abs_diff_max"] == 0
    down = result["prediction"]["down20"]
    summary = down["A"]["all"]
    assert summary["count"] == summary["positives"] + summary["negatives"]
    assert summary["positive_rate"] == round(summary["positives"] / summary["count"], 6)
    assert summary["independent"] == summary["count"] // 21
    low, high = down["difference"]["all"]["auc"]["ci"]
    if oracle:
        assert low > 0
    else:
        assert low < 0 < high
    assert {key: result["tried"][key] for key in ("targets", "models", "prediction_cells", "strategies", "comparisons")} == {
        "targets": 10, "models": 2, "prediction_cells": 40, "strategies": 20, "comparisons": 414,
    }
    assert result["tried"]["intervals"]["prediction_difference"]["total"] > 0
    assert 0 < result["tried"]["intervals"]["prediction"]["total"] <= 80
    costs = result["strategy"]["results"]
    assert all(costs["A:down20:registered"][period]["vs_reference"] is None for period in explore.PERIODS)
    assert costs["B:down20:registered"]["all"]["vs_reference"]["regular"]["ci"] is not None
    assert result["tried"]["intervals"]["strategy_vs_reference"]["total"] <= 19 * 2 * 3
    assert set(run["packages"]) == {"numpy", "pandas", "scikit-learn", "scipy", "yfinance"}
    report = explore.report([result])
    assert all(word in report for word in ("正例数", "負例数", "正例率", "探索", "有効性未確認", "B と A の差", "原油"))
    assert str(Path.cwd()) not in report
    assert str(Path.cwd()) not in json.dumps(result, ensure_ascii=False, allow_nan=False)
