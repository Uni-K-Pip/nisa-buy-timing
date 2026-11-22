from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from nbt.backtest import average_cost, compare, decision_days, intervals
from nbt.build import JST
from nbt.calendar import add_business_days, is_business_day, is_order_day
from nbt.fetch import parse_nav
from nbt.indicators import indicators, wilder_rsi
from nbt.score import category, score_series
from nbt.series import adjusted_nav, domestic_dates, nowcast, yen_proxy
from nbt.settlement import last_order_day, settlement_date, settlement_summary


@pytest.mark.parametrize(
    ("count", "closed", "expected"),
    [(6, ["NYSE"], 23), (5, ["NYSE"], 24), (4, ["NYSE"], 24), (4, [], 25)],
)
def test_year_end_2026(count, closed, expected):
    last = last_order_day(2026, count, closed)
    assert last == date(2026, 12, expected)
    final_domestic_day = add_business_days(date(2026, 12, 31), -1)
    assert final_domestic_day == date(2026, 12, 30)
    assert settlement_date(last, count) <= final_domestic_day


def test_order_calendar_and_cutoff():
    assert not is_business_day(date(2026, 11, 23))
    assert not is_business_day(date(2026, 12, 31))
    assert not is_business_day(date(2027, 1, 3))
    assert is_business_day(date(2026, 12, 25))
    assert not is_order_day(date(2026, 12, 25), ["NYSE"])
    fund = {
        "order_closed_calendars": ["NYSE"],
        "settlement": {"verified": False, "trade_lag_bd": 1, "settle_bd_from_order": 6, "order_cutoff_jst": "15:00"},
    }
    result = settlement_summary(fund, datetime(2026, 12, 23, 15, tzinfo=JST))
    assert result["remaining_business_days"] == 0
    assert result["last_settle_date"] == "2026-12-30"
    assert len(result["upcoming_orders"]) == 5
    assert result["upcoming_orders"][:2] == [
        {"order_date": "2026-12-24", "trade_date": "2026-12-25", "settle_date": "2027-01-04"},
        {"order_date": "2026-12-28", "trade_date": "2026-12-29", "settle_date": "2027-01-06"},
    ]


def test_csv_cp932_and_distribution():
    csv = (
        "年月日,基準価額(円),純資産総額（百万円）,分配金,決算期\n"
        "2026年11月20日,\"1,000\",10,100,決算\n"
        "2026年11月19日,\"1,100\",10,,\n"
    ).encode("cp932")
    frame = parse_nav(csv)
    assert frame.index.strftime("%Y-%m-%d").tolist() == ["2026-11-19", "2026-11-20"]
    assert frame["nav"].tolist() == [1100, 1000]
    assert frame["distribution"].tolist() == [0, 100]
    assert adjusted_nav(frame).tolist() == pytest.approx([1100, 1100])


def test_proxy_alignment_and_nowcast():
    idx = pd.Series([100.0, 110.0, 120.0], index=pd.to_datetime(["2026-11-19", "2026-11-20", "2026-11-23"]))
    fx = pd.Series([150.0, 160.0], index=idx.index[[0, 2]])
    proxy = yen_proxy(idx, fx)
    assert proxy.tolist() == [15000, 16500, 19200]
    assert domestic_dates(proxy).to_dict() == {
        pd.Timestamp("2026-11-20"): 15000, pd.Timestamp("2026-11-24"): 19200,
    }
    nav = pd.DataFrame({"nav": [900.0, 1000.0], "distribution": [0.0, 0.0]},
                       index=pd.to_datetime(["2026-11-19", "2026-11-20"]))
    result = nowcast(nav, proxy)
    assert result["us_date"] == "2026-11-23"
    assert result["value"] == 1280
    assert result["change_pct"] == pytest.approx(28)


def test_known_indicators():
    price = pd.Series(np.arange(1.0, 301.0), index=pd.bdate_range("2024-01-01", periods=300))
    values = indicators(price)
    latest = values.iloc[-1]
    assert latest["dd252"] == 0
    assert latest["ma200_dev"] == pytest.approx(300 / 200.5 - 1)
    assert latest["ma25_dev"] == pytest.approx(300 / 288 - 1)
    assert latest["rsi14"] == 100
    for length in (5, 20, 60):
        assert latest[f"ret{length}"] == pytest.approx(300 / (300 - length) - 1)
    daily_logs = np.log(price).diff().dropna()
    assert latest["vol20"] == pytest.approx(daily_logs.iloc[-20:].std() * np.sqrt(252))
    assert latest["vol_ratio"] == pytest.approx(daily_logs.iloc[-20:].std() / daily_logs.iloc[-252:].std())
    moves = pd.Series([10.0, 12.0, 11.0, 14.0, 13.0])
    np.testing.assert_allclose(wilder_rsi(moves, 3).iloc[3:], [100 * 5 / 6, 100 * 10 / 15])
    assert wilder_rsi(price * 0 + 100).iloc[-1] == 50


def test_score_ties_lower_price_and_no_future():
    price = pd.Series(np.repeat(100.0, 460), index=pd.bdate_range("2024-01-01", periods=460))
    price.iloc[400] = 80
    price.iloc[440:] = 200
    scores, pct = score_series(indicators(price))
    partial, _ = score_series(indicators(price.iloc[:410]))
    pd.testing.assert_series_equal(partial, scores.iloc[:410])
    assert scores.dropna().between(0, 100).all()
    assert scores.iloc[399] == 0
    assert scores.iloc[400] > 80
    assert pct["dd252"].iloc[400] == pytest.approx(1 / 150)
    assert category(80)[1] == "かなり割安圏"
    assert category(20)[1] == "割高寄り"


def test_backtest_uses_harmonic_cost_deadlines_and_one_purchase_per_day():
    bounds = intervals(20, 3)
    assert bounds == [(0, 5), (6, 12), (13, 19)]
    signal = np.zeros(20)
    assert decision_days(bounds, signal, 70) == [5, 12, 19]
    signal[[2, 3, 4]] = [70, 85, 95]
    days = decision_days(bounds, signal, 70)
    assert days == [2, 3, 4]
    assert len(set(days)) == len(days) == len(bounds)
    assert all(day <= end for day, (_, end) in zip(days, bounds))
    prices = np.array([90.0, 100.0, 200.0])
    average = average_cost(prices, [0, 1])
    assert average == pytest.approx(2 / (1 / 100 + 1 / 200))
    assert average == pytest.approx(2 / sum(1 / fill for fill in prices[1:]))
    assert decision_days(bounds, np.full(20, 0.4), 0.4, ml=True) == [0, 6, 13]


def test_backtest_flat_and_v_shape():
    dates = pd.bdate_range("2025-01-01", periods=21)
    flat = pd.Series(100.0, index=dates)
    scores = flat * 0 + 70
    prob = flat * 0 + 0.3
    result = compare(flat, scores, prob)
    assert len(result["grid"]) == 60
    row = next(row for row in result["grid"] if (row["window"], row["count"], row["threshold"]) == (20, 3, 70))
    for key in ("score", "lump", "ml"):
        assert row[key]["all"] == {"count": 1, "mean": 0, "median": 0, "win_rate": 0, "p05": 0, "p95": 0}
    price = pd.Series(np.r_[np.linspace(125, 50, 10), np.linspace(55, 125, 11)], index=dates)
    score = pd.Series(np.where(price <= 65, 90, 0), index=dates)
    one = compare(price, score, prob)["grid"][1]
    assert one["score"]["all"]["mean"] < 0
    assert one["score"]["recent_3y"]["win_rate"] == 100
