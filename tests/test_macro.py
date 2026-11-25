import numpy as np
import pandas as pd
import pytest

from nbt import macro
from nbt.series import _domestic_range


def test_morning_dates_cover_delay_holidays_and_collisions():
    values = pd.Series([4.0, 3.8, 3.9, 4.1], index=pd.to_datetime([
        "2026-11-19", "2026-11-20", "2026-11-23", "2026-11-25",
    ]))
    assert macro.domestic_close(values, 0).to_dict() == {
        pd.Timestamp("2026-11-20"): 4.0, pd.Timestamp("2026-11-24"): 3.9, pd.Timestamp("2026-11-26"): 4.1,
    }
    assert macro.domestic_close(values, 1).to_dict() == {
        pd.Timestamp("2026-11-24"): 3.8, pd.Timestamp("2026-11-25"): 3.9, pd.Timestamp("2026-11-27"): 4.1,
    }


def test_bond_yield_keeps_negative_and_zero_rates():
    assert macro.bond_yield(5) == pytest.approx(100 * 365 * 0.05 / (360 - 91 * 0.05))
    assert macro.bond_yield(-0.1) == pytest.approx(-0.1013632665076328)
    assert macro.bond_yield(0) == 0


def test_features_use_full_domestic_history_and_limit_forward_fill():
    days = _domestic_range(pd.Timestamp("2024-01-04"), pd.Timestamp("2025-02-07"))
    ten = 2 + np.arange(len(days)) / 100
    three = np.linspace(-0.1, 1, len(days))
    dollar = 100 + np.arange(len(days)) / 10
    raw = {
        "us10y": pd.Series(ten, index=days - pd.Timedelta(days=1)),
        "us3m": pd.Series(three, index=days - pd.Timedelta(days=1)),
        "dxy": pd.Series(dollar, index=days - pd.Timedelta(days=2)),
    }
    i = 220
    requested = days[[i, i + 1]]
    result = macro.features(raw, requested, ["rates_dollar"])
    spread = ten - macro.bond_yield(three)
    assert result.index.equals(requested)
    assert result.iloc[0].to_dict() == pytest.approx({
        "us10y_chg20": 0.2, "term_spread": spread[i], "term_spread_chg20": spread[i] - spread[i - 20],
        "dxy_dev": dollar[i] / dollar[i - 199:i + 1].mean() - 1, "dxy_ret20": dollar[i] / dollar[i - 20] - 1,
    })
    for values in raw.values():
        values.iloc[i + 2:] *= 3
    pd.testing.assert_frame_equal(result, macro.features(raw, requested, ["rates_dollar"]))

    raw["us3m"] = raw["us3m"].iloc[:i + 1]
    result = macro.features(raw, days[i:i + 8], ["rates_dollar"])
    assert result["term_spread"].iloc[:6].notna().all()
    assert result["term_spread"].iloc[6:].isna().all()
    raw["dxy"] = raw["dxy"].iloc[:0]
    assert macro.features(raw, requested, ["rates_dollar"]) is None
