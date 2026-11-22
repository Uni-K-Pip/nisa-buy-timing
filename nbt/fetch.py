from io import StringIO
from time import sleep

import pandas as pd
import requests

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


class DataSource:
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

        def download():
            with Session(impersonate="chrome", headers={"User-Agent": USER_AGENT}) as session:
                prices = yf.download(
                    ticker, period="max", auto_adjust=False, progress=False,
                    threads=False, timeout=30, session=session,
                )
            if prices.empty:
                raise ValueError("empty market series")
            close = prices["Close"]
            if isinstance(close, pd.DataFrame):
                close = close[ticker]
            close = close.dropna().sort_index()
            if close.empty:
                raise ValueError("empty market close")
            return close

        return retry(download)
