import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from nbt import ml
from nbt.calendar import add_business_days
from nbt.series import _domestic_range


def test_targets_and_training_rows_do_not_look_ahead(monkeypatch):
    dates = pd.bdate_range("2018-01-01", periods=1200)
    price = pd.Series(np.arange(len(dates), 0.0, -1), index=dates)
    got = ml.targets(price)
    assert got.iloc[:-21].eq(1).all()
    assert got.iloc[-21:].isna().all()

    features = pd.DataFrame({"known": np.arange(len(price))}, index=dates)
    fitted = []

    class FakeModel:
        def __init__(self, as_of):
            self.as_of = as_of

        def predict_proba(self, rows):
            assert rows[0, 0] == self.as_of
            return np.tile([0.5, 0.5], (len(rows), 1))

    def fake_fit(_, outcome, rows):
        assert np.isfinite(outcome[rows]).all()
        # 学習時点の朝には当日の価格がないので、答えは前日までの価格で決まる。
        as_of = rows[-1] + ml.HORIZON + 1
        assert np.all(rows + ml.HORIZON < as_of)
        fitted.append(as_of)
        return FakeModel(as_of)

    monkeypatch.setattr(ml, "fit", fake_fit)
    forward, latest, previous, result = ml.experiment(price, features)
    assert fitted[:-2] == list(range(771, 1200, 21))
    assert fitted[-2:] == [1198, 1199]
    assert forward.iloc[:771].isna().all()
    assert (latest, previous) == (0.5, 0.5)
    assert result["valid"] is False


def test_noise_model_is_invalid():
    rng = np.random.default_rng(321)
    price = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.01, 1700))))
    features = pd.DataFrame(rng.normal(size=(len(price), 10)))
    _, probability, _, result = ml.experiment(price, features)
    assert 0 <= probability <= 1
    assert result["count"] >= 250
    assert result["valid"] is False
    assert result["auc_ci"] is not None
    assert result["brier_skill_ci"] is not None
    assert result["independent"] == result["count"] // 21
    assert len(result["calibration"]) == 10
    assert sum(group["count"] for group in result["calibration"]) == result["count"]


def test_validation_needs_both_lower_bounds():
    assert ml.is_valid(250, 0.6, 0.02, (0.51, 0.65), (0.01, 0.04))
    assert not ml.is_valid(250, 0.6, 0.02, (0.5, 0.65), (0.01, 0.04))
    assert not ml.is_valid(250, 0.6, 0.02, (0.51, 0.65), (0, 0.04))
    assert not ml.is_valid(250, 0.6, 0.02, None, (0.01, 0.04))


def test_auc_bootstrap_counts_repeated_rows_and_tied_probabilities():
    actual = np.array([1, 0, 1, 0, 0])
    probabilities = np.array([0.25, 0.25, 0.75, 0.5, 0.75])
    rows = np.array([4, 4, 0, 1, 3, 0, 2])
    auc = ml._sample_auc(actual, probabilities)
    assert auc(rows) == pytest.approx(roc_auc_score(actual[rows], probabilities[rows]))
    assert np.isnan(auc([4, 3]))


def test_nondefault_lag_and_decision_features_for_walk_forward_and_latest(monkeypatch):
    days = _domestic_range(pd.Timestamp("2024-01-04"), pd.Timestamp("2024-07-31"))
    count = len(days)
    rng = np.random.default_rng(608)
    price = pd.Series(rng.uniform(80, 120, count), index=days)
    features = pd.DataFrame({"row": np.arange(count), "marker": 0.2}, index=days)
    decision = features.assign(marker=0.8)
    next_day = pd.Timestamp(add_business_days(days[-1].date(), 1))
    decision.loc[next_day] = [count, 0.9]
    lag = 3
    wait = lag + 20
    outcome = ml.targets(price, lag)
    np.testing.assert_equal(outcome.iloc[:-wait].to_numpy(), (price.to_numpy()[wait:] < price.to_numpy()[lag:-20]).astype(float))
    assert outcome.iloc[-wait:].isna().all()
    assert ml.training_rows(np.ones(count, dtype=bool), outcome, 30, lag)[-1] == 30 - wait - 1
    train_ends = []

    class Model:
        def predict_proba(self, rows):
            if rows[0, 1] == 0.8:
                assert train_ends[-1] + wait < rows[0, 0]
            return np.stack([1 - rows[:, 1], rows[:, 1]], axis=1)

    def fit(values, labels, rows):
        assert (values[:, 1] == 0.2).all()
        assert np.isfinite(labels[rows]).all()
        train_ends.append(rows[-1])
        return Model()

    monkeypatch.setattr(ml, "MIN_TRAIN", 10)
    monkeypatch.setattr(ml, "fit", fit)
    first = 10 + wait
    registered = days[first + 10]
    forecasts, latest, previous, result = ml.experiment(
        price, features, decision, lag=lag, registered=registered, nav_start=days[first + 4], latest_basis="estimate",
    )
    assert train_ends[:-2] == list(range(first - wait - 1, count - wait - 1, ml.STEP))
    assert train_ends[-2:] == [count - 2 - wait, count - 1 - wait]
    assert forecasts.iloc[:first].isna().all()
    assert forecasts.iloc[first:].eq(0.8).all()
    assert (latest, previous) == (0.9, 0.8)
    assert result["forward"]["count"] == count - wait - first - 11
    impact = result["estimate_impact"]
    assert impact["prob_abs_diff_mean"] == pytest.approx(0.6)
    assert impact["prob_abs_diff_p95"] == pytest.approx(0.6)
    assert impact["auc_confirmed"] == impact["auc_estimate"] == 0.5
    assert impact["brier_skill_confirmed"] != impact["brier_skill_estimate"]
