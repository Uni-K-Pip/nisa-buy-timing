from datetime import date

import numpy as np
import pandas as pd
import pytest

from nbt import backtest, validation


def test_registered_fingerprints_and_limit():
    registration = validation.load_registration()
    for entry in registration["strategies"]:
        assert entry["fingerprint"] == validation.fingerprint(entry)
    assert validation.judgment_level(registration["protocol"]) == 0.998
    registration["strategies"] *= 3
    with pytest.raises(ValueError, match="上限"):
        validation.load_registration(registration)


def test_status_requires_margin_intervals_nav_and_judgment():
    assert validation.status(None, None, None, None, True, 0.5) == "unconfirmed"
    assert validation.status(0.3, (0.1, 0.6), None, None, True, 0.5) == "unfavorable"
    assert validation.status(-0.4, (-0.6, -0.2), (-0.6, -0.2), -1, True, 0.5, passed=True) == "unconfirmed"
    assert validation.status(-0.5, (-0.6, -0.2), (-0.6, -0.2), 0, True, 0.5) == "unconfirmed"
    assert validation.status(-0.5, (-0.6, -0.2), (-0.6, 0), -1, True, 0.5) == "unconfirmed"
    assert validation.status(-0.5, (-0.6, -0.2), (-0.6, -0.2), -1, True, 0.5) == "candidate"
    assert validation.status(-0.5, (-0.6, -0.2), (-0.6, -0.2), None, False, 0.5, passed=True) == "confirmed"
    assert validation.status(-0.5, (-0.6, -0.2), (-0.6, -0.2), None, False, 0.5, closed=True) == "unconfirmed"


def test_periods_exclude_windows_crossing_registration():
    rows = pd.DataFrame({
        "date": pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-25", "2026-11-26"]),
        "last_fill": pd.to_datetime(["2026-11-25", "2026-11-26", "2026-11-27", "2026-11-30"]),
    })
    history, forward = validation.period_masks(rows, date(2026, 11, 25))
    assert history.tolist() == [True, False, False, False]
    assert forward.tolist() == [False, False, False, True]


def test_look_schedule_in_leap_year_and_at_close():
    registered = date(2024, 2, 29)
    years = [2, 3, 4, 5, 6]
    expected = ["2026-02-28", "2027-02-28", "2028-02-29", "2029-02-28", "2030-02-28"]
    assert validation.look_schedule(registered, years, date(2026, 2, 27)) == {
        "dates": expected, "last": None, "next": "2026-02-28", "closed": False,
    }
    end = date(2030, 2, 28)
    assert validation.look_schedule(registered, years, end) == {
        "dates": expected, "last": "2030-02-28", "next": None, "closed": True,
    }
    assert not validation.look_schedule(registered, years, end, confirmed=True)["closed"]


def test_evidence_changes_at_look_and_only_uses_windows_completed_by_then():
    registration = validation.load_registration()
    protocol = registration["protocol"]
    entry = registration["strategies"][0] | {"registered": "2020-01-01"}
    dates = pd.bdate_range("2017-01-01", "2022-05-01")
    prices = 1000 * np.exp(-0.002 * np.arange(len(dates)))
    fills = pd.DataFrame({"price": prices, "last_fill": dates + pd.offsets.BDay()}, index=dates)
    rng = np.random.default_rng(753)
    scores = pd.Series(np.where(dates > "2022-01-01", rng.uniform(0, 100, len(dates)), 0), index=dates)

    def evidence(today, fills):
        results = backtest.window_results(fills, scores, **entry["primary"])
        return validation.evidence(
            "demo", entry, protocol, results, dates[0], fills.index[-1], today, backtest.COMPARISONS,
        )["comparisons"]

    before = evidence(date(2021, 12, 31), fills)
    assert before["regular"]["status"] == "candidate"
    assert before["regular"]["judgment"] is None
    at_look = evidence(date(2022, 1, 1), fills.loc[fills["last_fill"] <= "2022-01-01"])
    later = evidence(date(2022, 5, 1), fills)
    assert later["regular"]["status"] == "confirmed"
    assert later["regular"]["judgment"]["independent"] >= 12
    assert later["regular"]["judgment"]["passed"]
    assert later["regular"]["forward"]["count"] > at_look["regular"]["forward"]["count"]
    for comparison in backtest.COMPARISONS:
        assert later[comparison]["judgment"] == at_look[comparison]["judgment"]
        assert later[comparison]["history"] == at_look[comparison]["history"]
    assert later["regular"]["judgment"]["level"] == 0.998
