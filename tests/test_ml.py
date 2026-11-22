import numpy as np
import pandas as pd

from nbt import ml


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
        as_of = rows[-1] + ml.HORIZON
        assert np.all(rows + ml.HORIZON <= as_of)
        fitted.append(as_of)
        return FakeModel(as_of)

    monkeypatch.setattr(ml, "fit", fake_fit)
    forward, latest, previous, result = ml.experiment(price, features)
    assert fitted[:-2] == list(range(770, 1200, 21))
    assert fitted[-2:] == [1198, 1199]
    assert forward.iloc[:770].isna().all()
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
    assert len(result["calibration"]) == 10
    assert sum(group["count"] for group in result["calibration"]) == result["count"]
