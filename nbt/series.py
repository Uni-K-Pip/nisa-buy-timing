import numpy as np
import pandas as pd

from .calendar import DAY, add_business_days, is_business_day


def adjusted_nav(frame):
    return frame["nav"] * (1 + frame["distribution"] / frame["nav"]).cumprod()


def domestic_dates(values):
    """Map each US date to the next JP session, keeping the latest close per session."""
    if values.empty:
        return values
    mapped = values.sort_index()
    mapped.index = pd.DatetimeIndex([
        add_business_days(day.date(), 1) for day in mapped.index
    ])
    return mapped.loc[~mapped.index.duplicated(keep="last")]


def yen_proxy(index, fx):
    aligned_fx = fx.reindex(index.index, method="ffill")
    return index.mul(aligned_fx).dropna()


def price_series(nav, index, fx):
    nav = nav.loc[[is_business_day(day.date()) for day in nav.index]]
    proxy_us = yen_proxy(index, fx)
    proxy_jp = domestic_dates(proxy_us)
    main = adjusted_nav(nav) if not nav.empty else proxy_jp
    if nav.empty and not proxy_jp.empty:
        start, end = proxy_jp.index[0].date(), proxy_jp.index[-1].date()
        domestic = pd.DatetimeIndex([
            day for offset in range((end - start).days + 1)
            if is_business_day(day := start + DAY * offset)
        ])
        main = proxy_jp.reindex(domestic, method="ffill")
    return main, nav, proxy_us, proxy_jp


def nowcast(nav, proxy_us):
    if nav.empty or proxy_us.empty:
        return None
    day = nav.index[-1]
    reference = pd.Timestamp(add_business_days(day.date(), -1, "NYSE"))
    if reference not in proxy_us.index or proxy_us.index[-1] <= reference:
        return None
    value = nav["nav"].iloc[-1]
    ratio = proxy_us.iloc[-1] / proxy_us.loc[reference]
    proxy_jp = domestic_dates(proxy_us)
    # A JP session can have no new US close, so carry the most recent one.
    proxy_returns = proxy_jp.reindex(nav.index, method="ffill").pct_change()
    errors = (adjusted_nav(nav).pct_change() - proxy_returns).loc[day - pd.DateOffset(years=1):day]
    error = errors.std() * 100
    return {
        "us_date": proxy_us.index[-1].date().isoformat(),
        "value": value * ratio,
        "change_pct": (ratio - 1) * 100,
        "error_pct": error if np.isfinite(error) else None,
    }
