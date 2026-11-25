from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from nbt.backtest import average_cost, compare, decision_days, intervals
from nbt.build import JST
from nbt.calendar import add_business_days, is_business_day, is_order_day, latest_us_session
from nbt.fetch import DataSource, parse_nav
from nbt.indicators import decision_indicators, indicators, wilder_rsi
from nbt.score import category, decision_score_series, score_series
from nbt.series import adjusted_nav, domestic_dates, estimated_series, latest_estimate, morning_fx, nowcast
from nbt.series import price_series, remove_fx_outliers
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


@pytest.mark.parametrize(("local", "expected"), [
    ("2026-11-25T11:00", "2026-11-24"),
    ("2026-11-25T05:30", "2026-11-23"),
    ("2026-11-25T06:00", "2026-11-24"),
    ("2026-11-27T07:30", "2026-11-25"),
    ("2026-11-30T07:30", "2026-11-27"),
    ("2026-07-07T05:30", "2026-07-06"),
    ("2026-07-07T04:30", "2026-07-02"),
    ("2026-11-24T21:30", "2026-11-23"),
])
def test_latest_us_session(local, expected):
    now = datetime.fromisoformat(local).replace(tzinfo=JST)
    assert latest_us_session(now) == date.fromisoformat(expected)


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


@pytest.mark.parametrize("multi_index", [False, True])
def test_fx_download_cleans_and_sorts_both_columns(monkeypatch, multi_index):
    import yfinance as yf

    ticker = "USDJPY=X"
    days = pd.to_datetime(["2026-11-19", "2026-11-18", "2026-11-17", "2026-11-16", "2026-11-13"])
    prices = pd.DataFrame({"Open": [114.0, 113.0, 0.0, 111.0, 110.0],
                           "Close": [114.5, np.nan, 112.5, -1.0, 110.5]}, index=days)
    if multi_index:
        prices.columns = pd.MultiIndex.from_product([prices.columns, [ticker]])
    pauses = []

    def download(symbol, **kwargs):
        assert symbol == ticker
        assert kwargs["period"] == "max"
        assert kwargs["auto_adjust"] is False
        assert kwargs["timeout"] == 30
        if not pauses:
            raise OSError
        return prices

    monkeypatch.setattr(yf, "download", download)
    monkeypatch.setattr("nbt.fetch.sleep", pauses.append)
    expected = pd.DataFrame({"open": [110.0, 114.0], "close": [110.5, 114.5]}, index=days[[4, 0]])
    pd.testing.assert_frame_equal(DataSource().fx(ticker), expected)
    assert pauses == [1]


def test_morning_fx_uses_open_and_only_uses_close_after_last_day():
    days = pd.bdate_range("2026-11-16", periods=6)
    fx = pd.DataFrame({"open": [120.0, 130.0], "close": [128.0, 140.0]}, index=days[[1, 3]])
    np.testing.assert_array_equal(morning_fx(fx, days), [np.nan, 120, 120, 130, 140, 140])
    assert morning_fx(fx.iloc[:0], days).empty


def test_proxy_alignment_and_nowcast():
    index = pd.Series([100.0, 110.0, 120.0, 130.0, 140.0, 145.0], index=pd.to_datetime([
        "2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27",
    ]))
    days = pd.bdate_range("2026-11-24", "2026-11-30")
    fx = pd.DataFrame({"open": [150.0, 151.0, 152.0, 153.0],
                       "close": [149.0, 154.0, 155.0, 156.0]}, index=days[:-1])
    nav = pd.DataFrame({"nav": [900.0, 920.0, 1000.0, 980.0], "distribution": [0.0, 10.0, 0.0, 10.0]},
                       index=days[:-1])
    price, _, proxy, daily_fx, _ = price_series(nav, index, fx)
    assert proxy.index.tolist() == days.tolist()
    assert proxy.tolist() == [120 * 150, 130 * 151, 140 * 152, 140 * 153, 145 * 156]
    assert daily_fx.tolist() == [150, 151, 152, 153, 156]
    assert not is_business_day(date(2026, 11, 26), "NYSE")
    assert proxy.iloc[3] / proxy.iloc[2] == pytest.approx(153 / 152)
    ratio = proxy.iloc[-1] / proxy.iloc[-2]
    result = nowcast(nav, proxy, index)
    assert result["us_date"] == "2026-11-27"
    assert result["value"] == pytest.approx(nav["nav"].iloc[-1] * ratio)
    assert result["change_pct"] == pytest.approx((ratio - 1) * 100)
    assert result["error_pct"] == pytest.approx((price.pct_change() - proxy.iloc[:-1].pct_change()).std() * 100)
    assert nowcast(nav, proxy.iloc[:-1], index) is None
    assert nowcast(nav, proxy.iloc[-1:], index) is None


@pytest.mark.parametrize(("values", "kept"), [
    ([92.82, 109.24, 92.30], [0, 2]),
    ([133.85, 130.34, 121.65, 119.75], [0, 1, 2, 3]),
    ([93.19, 98.20, 97.52], [0, 1, 2]),
    ([93.19, 98.20], [0, 1]),
])
def test_remove_fx_outliers(values, kept):
    fx = pd.Series(values, index=pd.bdate_range("2024-01-01", periods=len(values)))
    pd.testing.assert_series_equal(remove_fx_outliers(fx), fx.iloc[kept])


@pytest.mark.parametrize("start", ["2026-11-24", "2026-11-25"])
def test_price_series_extends_nav_with_domestic_sessions(start):
    index = pd.Series([80.0, 100.0, 120.0], index=pd.to_datetime([
        "2026-11-17", "2026-11-19", "2026-11-23",
    ]))
    fx = pd.DataFrame({"open": 2.0, "close": 2.0}, index=index.index)
    nav = pd.DataFrame({"nav": [900.0, 1000.0], "distribution": [100.0, 0.0]},
                       index=pd.to_datetime([start, "2026-11-26"]))
    price, _, proxy, _, nav_start = price_series(nav, index, fx)
    assert nav_start == pd.Timestamp(start)
    before = price.loc[price.index < nav_start]
    days = ["2026-11-18", "2026-11-19", "2026-11-20"]
    if start == "2026-11-25":
        days.append("2026-11-24")
    assert before.index.tolist() == list(pd.to_datetime(days))
    assert before.iloc[0] == before.iloc[1]
    assert before.iloc[-1] * proxy.asof(nav_start) / proxy.asof(before.index[-1]) == pytest.approx(price.loc[nav_start])
    for later_proxy in (index.iloc[:0], index.iloc[-1:].rename(index={index.index[-1]: nav.index[-1]})):
        without_extension, _, _, _, _ = price_series(nav, later_proxy, fx)
        pd.testing.assert_series_equal(without_extension, adjusted_nav(nav))
        pd.testing.assert_series_equal(price.loc[nav_start:], without_extension)


def test_estimated_series_follows_proxy_and_uses_previous_confirmed_price():
    dates = pd.bdate_range("2026-11-16", periods=5)
    proxy = pd.Series([50.0, 100.0, 200.0, 400.0, 800.0], index=dates)
    price = proxy * 2
    pd.testing.assert_series_equal(estimated_series(price, proxy, dates[1]), price)

    changed = price.copy()
    changed.iloc[2] = 350.0
    estimated = estimated_series(changed, proxy, dates[1])
    assert estimated.iloc[2] == price.iloc[2]
    assert estimated.iloc[3] == 700
    pd.testing.assert_series_equal(estimated_series(changed, proxy), changed)

    sparse_price = price.drop(dates[2])
    sparse_proxy = proxy.iloc[[1, 3]]
    assert estimated_series(sparse_price, sparse_proxy, dates[1]).tolist() == [100, 100, 800, 800]
    assert estimated_series(price, proxy.iloc[:0], dates[2]).tolist() == [100, 200, 200, 400, 800]


def test_estimates_match_nav_only_with_domestic_date_fx():
    index = pd.Series([100.0, 105.0, 104.0, 106.0, 108.0], index=pd.to_datetime([
        "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27", "2026-11-30",
    ]))
    days = pd.bdate_range("2026-11-23", "2026-12-01")
    fx = pd.DataFrame({"open": [118.0, 120.0, 124.0, 125.0, 121.0, 129.0, 133.0],
                       "close": [119.0, 121.0, 123.0, 126.0, 127.0, 130.0, 134.0]}, index=days)
    nav = pd.DataFrame({"nav": np.array([100, 105, 104, 104, 106, 108]) * fx["open"].iloc[1:],
                        "distribution": 0.0})
    price, _, proxy, _, start = price_series(nav, index, fx)
    pd.testing.assert_series_equal(estimated_series(price, proxy, start), price, atol=1e-9, rtol=0)
    old_proxy = domestic_dates(index * fx["close"].reindex(index.index, method="ffill"))
    assert not np.allclose(estimated_series(price, old_proxy, start), price)


def test_latest_estimate_uses_last_mapped_session_and_carries_reference():
    dates = pd.to_datetime(["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-24"])
    proxy = pd.Series([80.0, 100.0, 120.0], index=dates[[0, 2, 3]])
    price = pd.Series([200.0, 300.0], index=dates[:2])
    assert latest_estimate(price, proxy) == (dates[-1], 450.0)
    assert latest_estimate(price, proxy.iloc[:1]) is None
    assert latest_estimate(price, proxy.iloc[1:]) is None


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


def test_fx_deviation_uses_domestic_dates_and_warmup_before_price():
    days = pd.DatetimeIndex([
        day for day in pd.bdate_range("2026-01-01", periods=230) if is_business_day(day.date())
    ])
    fx = pd.Series(np.arange(100.0, 100.0 + len(days)), index=days)
    price = pd.Series(1000.0, index=days[198:201])
    values = indicators(price, fx)
    assert np.isnan(values["fx_dev"].iloc[0])
    assert values["fx_dev"].iloc[1] == pytest.approx(299 / 199.5 - 1)
    assert values["fx_dev"].iloc[2] == pytest.approx(300 / 200.5 - 1)


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


def test_decision_indicators_and_scores_match_confirmed_when_prices_match():
    rng = np.random.default_rng(123)
    dates = pd.bdate_range("2018-01-01", periods=1500)
    price = pd.Series(100.0, index=dates)
    price.iloc[300:] *= np.exp(np.cumsum(rng.normal(0, 0.015, len(price) - 300)))
    fx = pd.Series(rng.uniform(100, 120, len(dates)), index=dates)
    vix = pd.Series(rng.uniform(15, 25, len(dates)), index=dates)
    confirmed = indicators(price, fx, vix)
    decision = decision_indicators(price, price, fx, vix)
    pd.testing.assert_frame_equal(decision, confirmed, atol=1e-9, rtol=0)
    scores, pct = score_series(confirmed)
    decision_scores, decision_pct = decision_score_series(confirmed, decision)
    pd.testing.assert_series_equal(decision_scores, scores, atol=1e-9, rtol=0)
    pd.testing.assert_frame_equal(decision_pct, pct, atol=1e-9, rtol=0)


def test_decision_indicators_match_replacing_only_the_last_price():
    rng = np.random.default_rng(456)
    dates = pd.bdate_range("2020-01-01", periods=950)
    price = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(dates)))), index=dates)
    estimated = price * np.exp(rng.normal(0, 0.05, len(price)))
    fx = price * 0.8
    vix = 1000 / price
    result = decision_indicators(price, estimated, fx, vix)
    for end in (0, 13, 14, 15, 19, 20, 24, 25, 199, 200, 250, 251, 252, 340, 759, 949):
        replaced = price.iloc[:end + 1].copy()
        replaced.iloc[-1] = estimated.iloc[end]
        expected = indicators(replaced, fx, vix).iloc[-1]
        pd.testing.assert_series_equal(result.iloc[end], expected, atol=1e-9, rtol=0)


def test_decision_scores_rank_estimates_against_only_past_confirmed_features():
    rng = np.random.default_rng(789)
    dates = pd.bdate_range("2019-01-01", periods=1503)
    choices = [1.0, 2.0, 3.0, 4.0, np.nan]
    history = pd.DataFrame(rng.choice(choices, (1502, 2)), index=dates[:-1], columns=["dd252", "rsi14"])
    decision = pd.DataFrame(rng.choice(choices, (1503, 2)), index=dates, columns=history.columns)
    scores, pct = decision_score_series(history, decision)
    for end in (118, 119, 150, 300, 1258, 1259, 1260, 1261, 1502):
        replaced = pd.concat([history.iloc[:end], decision.iloc[end:end + 1]])
        expected_scores, expected_pct = score_series(replaced)
        np.testing.assert_allclose(scores.iloc[end], expected_scores.iloc[-1], atol=1e-9, rtol=0)
        pd.testing.assert_series_equal(pct.iloc[end], expected_pct.iloc[-1], atol=1e-9, rtol=0)


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
    average = average_cost(prices, [1, 2])
    assert average == pytest.approx(2 / (1 / 100 + 1 / 200))
    assert average == pytest.approx(2 / sum(1 / fill for fill in prices[1:]))
    assert decision_days(bounds, np.full(20, 0.4), 0.4, ml=True) == [0, 6, 13]


def test_backtest_flat_and_v_shape():
    dates = pd.DatetimeIndex([
        day for day in pd.bdate_range("2025-01-01", periods=40) if is_business_day(day.date())
    ][:21])
    fund = {"id": "demo", "settlement": {"trade_lag_bd": 1, "order_cutoff_jst": "15:00"}}
    flat = pd.Series(100.0, index=dates)
    scores = flat * 0 + 70
    prob = flat * 0 + 0.3
    result = compare(flat, scores, prob, fund=fund)
    assert len(result["grid"]) == 60
    row = next(row for row in result["grid"] if (row["window"], row["count"], row["threshold"]) == (20, 3, 70))
    for key in ("score", "lump", "ml"):
        values = row[key]["all"]
        expected = {"count": 1, "independent": 1, "mean": 0, "median": 0, "win_rate": 0, "p05": 0, "p95": 0, "ci": None}
        assert {name: values[name] for name in expected} == expected
        if key != "lump":
            assert values["vs_lump"]["mean"] == 0
            assert values["vs_placebo"]["mean"] is None
    price = pd.Series(np.r_[np.linspace(125, 50, 10), np.linspace(55, 125, 11)], index=dates)
    score = pd.Series(np.where(price <= 65, 90, 0), index=dates)
    one = compare(price, score, prob, fund=fund)["grid"][1]
    assert one["score"]["all"]["mean"] < 0
    assert one["score"]["recent_3y"]["win_rate"] == 100
