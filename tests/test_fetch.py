from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
import yfinance as yf

from nbt import fetch


ZONE = "America/New_York"
FETCHED_AT = datetime(2026, 11, 25, 2, 8, tzinfo=timezone.utc)
FILLED = {
    "status": "filled", "date": "2026-11-24", "close": 148.14, "source": "regularMarketPrice",
    "price_time": "2026-11-24T16:00:01-05:00", "fetched_at": "2026-11-25T11:08:00+09:00",
}


@pytest.fixture
def daily():
    prices = pd.DataFrame({
        "Open": [148.0, 147.705], "High": [149.0, 148.65], "Low": [147.0, 146.94],
        "Close": [148.94, np.nan],
    }, index=pd.to_datetime(["2026-11-23", "2026-11-24"]))
    meta = {
        "regularMarketPrice": 148.14,
        "regularMarketTime": pd.Timestamp("2026-11-24 16:00:01", tz=ZONE),
        "exchangeTimezoneName": ZONE,
        "currentTradingPeriod": {"regular": {
            "start": pd.Timestamp("2026-11-24 09:30", tz=ZONE),
            "end": pd.Timestamp("2026-11-24 16:00", tz=ZONE),
        }},
    }
    return prices, meta


@pytest.mark.parametrize("empty", [False, True])
def test_latest_close_already_present_or_empty(daily, empty):
    prices, _ = daily
    prices = prices.iloc[:0] if empty else prices.assign(Close=[np.nan, 148.14])
    close, note = fetch.fill_latest_close(prices, {}, FETCHED_AT)
    pd.testing.assert_series_equal(close, prices["Close"])
    assert close is not prices["Close"]
    assert note is None


@pytest.mark.parametrize("unix_seconds", [False, True])
def test_fills_latest_close_only_and_preserves_inputs(daily, unix_seconds):
    prices, meta = daily
    prices.loc[pd.Timestamp("2026-11-20")] = prices.iloc[-1]
    prices = prices.sort_index()
    before = prices.copy()
    meta.update(postMarketPrice=148.25, preMarketPrice=148.55)
    if unix_seconds:
        meta["regularMarketTime"] = int(meta["regularMarketTime"].timestamp())
        regular = meta["currentTradingPeriod"]["regular"]
        regular.update({key: int(value.timestamp()) for key, value in regular.items()})
    else:
        meta["regularMarketTime"] = meta["regularMarketTime"].tz_convert("UTC")
    close, note = fetch.fill_latest_close(prices, meta, FETCHED_AT)
    expected = prices["Close"].copy()
    expected.iloc[-1] = 148.14
    pd.testing.assert_series_equal(close, expected)
    pd.testing.assert_frame_equal(prices, before)
    assert note == FILLED


@pytest.mark.parametrize("value_day", ["2026-11-23", "2026-11-25"])
def test_latest_close_rejects_other_trade_dates(daily, value_day):
    prices, meta = daily
    meta["regularMarketTime"] = pd.Timestamp(f"{value_day} 16:00:01", tz=ZONE)
    close, note = fetch.fill_latest_close(prices, meta, FETCHED_AT)
    pd.testing.assert_series_equal(close, prices["Close"])
    assert note == {
        "status": "unfilled", "date": "2026-11-24", "reason": "date_mismatch",
        "fetched_at": "2026-11-25T11:08:00+09:00",
    }


@pytest.mark.parametrize(("fetched", "status"), [("20:59", "unfilled"), ("21:00", "filled")])
def test_latest_close_requires_session_end(daily, fetched, status):
    prices, meta = daily
    close, note = fetch.fill_latest_close(prices, meta, pd.Timestamp(f"2026-11-24 {fetched}", tz="UTC"))
    assert note["status"] == status
    if status == "unfilled":
        assert note["reason"] == "session_open"
        assert pd.isna(close.iloc[-1])
    else:
        assert close.iloc[-1] == 148.14


@pytest.mark.parametrize(("field", "value"), [
    ("regularMarketPrice", None), ("regularMarketPrice", np.nan), ("regularMarketPrice", np.inf),
    ("regularMarketTime", None), ("exchangeTimezoneName", None),
])
def test_latest_close_requires_price_metadata(daily, field, value):
    prices, meta = daily
    if value is None:
        del meta[field]
    else:
        meta[field] = value
    close, note = fetch.fill_latest_close(prices, meta, FETCHED_AT)
    pd.testing.assert_series_equal(close, prices["Close"])
    assert note["reason"] == "no_price"


@pytest.mark.parametrize(("field", "value"), [
    ("price", 149.0), ("price", 146.0), ("High", np.nan), ("Low", np.nan), ("High", 0.0), ("Low", 0.0),
])
def test_latest_close_rejects_invalid_daily_range(daily, field, value):
    prices, meta = daily
    if field == "price":
        meta["regularMarketPrice"] = value
    else:
        prices.loc[prices.index[-1], field] = value
    close, note = fetch.fill_latest_close(prices, meta, FETCHED_AT)
    pd.testing.assert_series_equal(close, prices["Close"])
    assert note["reason"] == "out_of_range"


@pytest.mark.parametrize(("field", "price"), [("High", 148.65), ("Low", 146.94)])
def test_latest_close_allows_float32_rounding_at_boundaries(daily, field, price):
    prices, meta = daily
    direction = -np.inf if field == "High" else np.inf
    prices.loc[prices.index[-1], field] = float(np.nextafter(np.float32(price), np.float32(direction)))
    meta["regularMarketPrice"] = price
    close, note = fetch.fill_latest_close(prices, meta, FETCHED_AT)
    assert close.iloc[-1] == price
    assert note["status"] == "filled"


@pytest.mark.parametrize("day", ["2026-11-26", "2026-11-28", "2026-11-29"])
def test_latest_close_rejects_non_trading_days(daily, day):
    prices, _ = daily
    prices.index = pd.to_datetime(["2026-11-23", day])
    close, note = fetch.fill_latest_close(prices, {}, FETCHED_AT)
    pd.testing.assert_series_equal(close, prices["Close"])
    assert note["reason"] == "not_trading_day"


@pytest.mark.parametrize(("fetched", "status"), [("20:05", "filled"), ("19:55", "unfilled")])
def test_latest_close_uses_daylight_saving_time(daily, fetched, status):
    prices, meta = daily
    prices.index = pd.to_datetime(["2026-07-02", "2026-07-06"])
    meta["regularMarketTime"] = pd.Timestamp("2026-07-06 16:00:01", tz=ZONE)
    meta["currentTradingPeriod"]["regular"] = {
        "start": pd.Timestamp("2026-07-06 09:30", tz=ZONE),
        "end": pd.Timestamp("2026-07-06 16:00", tz=ZONE),
    }
    close, note = fetch.fill_latest_close(prices, meta, pd.Timestamp(f"2026-07-06 {fetched}", tz="UTC"))
    assert note["status"] == status
    if status == "filled":
        assert close.iloc[-1] == 148.14
        assert note["price_time"] == "2026-07-06T16:00:01-04:00"
    else:
        assert note["reason"] == "session_open"
        assert pd.isna(close.iloc[-1])


def test_latest_close_accepts_next_trading_period(daily):
    prices, meta = daily
    regular = meta["currentTradingPeriod"]["regular"]
    regular.update({key: value + pd.Timedelta(days=1) for key, value in regular.items()})
    close, note = fetch.fill_latest_close(prices, meta, FETCHED_AT)
    assert note == FILLED
    assert close.iloc[-1] == 148.14


@pytest.mark.parametrize("missing", ["period", "regular", "end", "previous_day"])
def test_latest_close_requires_usable_session_end(daily, missing):
    prices, meta = daily
    periods = meta["currentTradingPeriod"]
    if missing == "period":
        del meta["currentTradingPeriod"]
    elif missing == "regular":
        del periods["regular"]
    elif missing == "end":
        del periods["regular"]["end"]
    else:
        periods["regular"]["end"] -= pd.Timedelta(days=1)
    close, note = fetch.fill_latest_close(prices, meta, FETCHED_AT)
    pd.testing.assert_series_equal(close, prices["Close"])
    assert note["reason"] == "session_unknown"


def test_data_source_close_uses_same_history_and_clears_notes(daily, monkeypatch):
    prices, meta = daily
    localized = prices.tz_localize(ZONE)
    wrong_date = dict(meta, regularMarketTime=meta["regularMarketTime"] - pd.Timedelta(days=1))
    responses = iter([
        (localized, meta),
        (localized, wrong_date),
        (localized.assign(Close=[148.94, 148.15]), {}),
    ])

    class FakeTicker:
        def __init__(self, ticker, *, session):
            assert ticker == "ACWI"
            assert session is not None

        def history(self, **kwargs):
            assert kwargs == {"period": "max", "auto_adjust": False, "actions": False, "timeout": 30}
            prices, self.history_metadata = next(responses)
            return prices

    def unexpected(*args, **kwargs):
        pytest.fail("yf.download called")

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    monkeypatch.setattr(yf, "download", unexpected)
    monkeypatch.setattr(fetch, "_now", lambda: FETCHED_AT)
    source = fetch.DataSource()

    close = source.close("ACWI")
    pd.testing.assert_index_equal(close.index, prices.index)
    assert close.iloc[-1] == 148.14
    assert source.close_notes["ACWI"] == FILLED

    close = source.close("ACWI")
    pd.testing.assert_series_equal(close, prices["Close"].dropna())
    assert source.close_notes["ACWI"]["reason"] == "date_mismatch"

    close = source.close("ACWI")
    assert close.iloc[-1] == 148.15
    assert source.close_notes == {}
    assert next(responses, None) is None
