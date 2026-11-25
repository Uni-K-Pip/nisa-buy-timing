from datetime import datetime, timezone
from io import StringIO
from math import isclose, isfinite
from numbers import Integral, Real
from time import sleep
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import requests

from .calendar import is_business_day

NAV_URL = "https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download"
USER_AGENT = "nisa-buy-timing/0.1 (+https://github.com/Uni-K-Pip/nisa-buy-timing)"


def parse_nav(content):
    frame = pd.read_csv(StringIO(content.decode("cp932")), dtype="str")
    dates = pd.to_datetime(frame["年月日"].str.strip(), format="%Y年%m月%d日", errors="coerce")

    def numbers(column):
        return pd.to_numeric(frame[column].str.replace(",", "", regex=False).str.strip(), errors="coerce")

    result = pd.DataFrame({
        "nav": numbers("基準価額(円)").to_numpy(),
        "distribution": numbers("分配金").fillna(0).to_numpy(),
    }, index=pd.DatetimeIndex(dates))
    result = result.loc[result.index.notna() & result["nav"].gt(0)]
    result = result.loc[~result.index.duplicated(keep="last")].sort_index()
    if result.empty:
        raise ValueError("empty NAV")
    return result


def retry(fetch):
    for attempt in range(3):
        try:
            return fetch()
        except Exception:
            if attempt == 2:
                raise
            sleep(2 ** attempt)


def _now():
    return datetime.now(timezone.utc)


def _exchange_time(value, zone):
    if isinstance(value, Integral):
        value = pd.to_datetime(value, unit="s", utc=True, errors="coerce")
    if pd.isna(value) or not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(zone)


def fill_latest_close(prices, meta, fetched_at):
    """最後の行の終値だけが欠けているとき、同じ応答の通常取引の最新値で補う(3.3)。"""
    close = prices["Close"].copy()
    if close.empty or pd.notna(close.iloc[-1]):
        return close, None

    day = close.index[-1].date()
    note = {
        "date": day.isoformat(),
        "fetched_at": fetched_at.astimezone(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
    }

    def unfilled(reason):
        return close, {"status": "unfilled", **note, "reason": reason}

    if not is_business_day(day, "NYSE"):
        return unfilled("not_trading_day")
    price = meta.get("regularMarketPrice")
    zone_name = meta.get("exchangeTimezoneName")
    if not isinstance(price, Real) or not isfinite(price) or not zone_name:
        return unfilled("no_price")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return unfilled("no_price")
    price_time = _exchange_time(meta.get("regularMarketTime"), zone)
    if price_time is None:
        return unfilled("no_price")
    if price_time.date() != day:
        return unfilled("date_mismatch")

    periods = meta.get("currentTradingPeriod") or {}
    regular = periods.get("regular") or {}
    end = _exchange_time(regular.get("end"), zone)
    if end is None or end.date() < day:
        return unfilled("session_unknown")
    if end.date() == day and fetched_at < end:
        return unfilled("session_open")

    high, low = prices["High"].iloc[-1], prices["Low"].iloc[-1]
    if pd.isna(high) or pd.isna(low) or not 0 < low <= high:
        return unfilled("out_of_range")
    # Yahoo の高値・安値には float32 の丸め誤差がある。
    if (price < low and not isclose(price, low, rel_tol=1e-6)
            or price > high and not isclose(price, high, rel_tol=1e-6)):
        return unfilled("out_of_range")

    close.iloc[-1] = price
    return close, {
        "status": "filled", **note, "close": float(price), "source": "regularMarketPrice",
        "price_time": price_time.isoformat(timespec="seconds"),
    }


class DataSource:
    def __init__(self):
        self.close_notes = {}

    def nav(self, fund):
        def download():
            response = requests.get(
                NAV_URL,
                params={"isinCd": fund["isin"], "associFundCd": fund["association_code"]},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            response.raise_for_status()
            return parse_nav(response.content)

        return retry(download)

    def close(self, ticker):
        import yfinance as yf
        from curl_cffi.requests import Session

        self.close_notes.pop(ticker, None)

        def download():
            with Session(impersonate="chrome", headers={"User-Agent": USER_AGENT}) as session:
                symbol = yf.Ticker(ticker, session=session)
                prices = symbol.history(period="max", auto_adjust=False, actions=False, timeout=30)
                fetched_at = _now()
                if prices.empty:
                    raise ValueError("empty market series")
                prices = prices.tz_localize(None)
                close, note = fill_latest_close(prices, symbol.history_metadata, fetched_at)
            if note is None:
                self.close_notes.pop(ticker, None)
            else:
                self.close_notes[ticker] = note
            close = close.dropna().sort_index()
            if close.empty:
                raise ValueError("empty market close")
            return close

        return retry(download)

    def fx(self, ticker):
        import yfinance as yf
        from curl_cffi.requests import Session

        def download():
            with Session(impersonate="chrome", headers={"User-Agent": USER_AGENT}) as session:
                prices = yf.download(
                    ticker, period="max", auto_adjust=False, progress=False,
                    threads=False, timeout=30, session=session,
                )
            if prices.empty:
                raise ValueError("empty market series")
            opening, closing = prices["Open"], prices["Close"]
            if isinstance(opening, pd.DataFrame):
                opening, closing = opening[ticker], closing[ticker]
            values = pd.DataFrame({"open": opening, "close": closing}).dropna().sort_index()
            values = values.loc[values.gt(0).all(axis=1)]
            if values.empty:
                raise ValueError("empty market FX")
            return values

        return retry(download)
