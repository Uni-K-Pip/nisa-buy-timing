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


def morning_fx(fx, days):
    if fx.empty:
        return pd.Series(dtype=float, index=days[:0])
    opening = fx["open"].dropna().reindex(days, method="ffill")
    return opening.mask(days > fx.index[-1], fx["close"].iloc[-1])


def remove_fx_outliers(fx):
    change = np.log(fx).diff()
    following = change.shift(-1)
    outlier = (change.abs() >= 0.03) & (change * following < 0)
    return fx.loc[~(outlier & ((change + following).abs() <= 0.5 * change.abs()))]


def _domestic_range(start, end):
    start, end = start.date(), end.date()
    return pd.DatetimeIndex([
        day for offset in range((end - start).days + 1)
        if is_business_day(day := start + DAY * offset)
    ])


def price_series(nav, index, fx):
    nav = nav.loc[[is_business_day(day.date()) for day in nav.index]]
    index_jp = domestic_dates(index)
    end = max((days[-1] for days in (nav.index, index_jp.index) if len(days)), default=None)
    fx_days = _domestic_range(fx.index[0], end) if not fx.empty and end is not None else pd.DatetimeIndex([])
    daily_fx = morning_fx(fx, fx_days)

    proxy_jp = index_jp
    if not index_jp.empty:
        proxy_fx = daily_fx.loc[index_jp.index[0]:index_jp.index[-1]]
        proxy_jp = index_jp.reindex(proxy_fx.index, method="ffill").mul(proxy_fx).dropna()

    nav_start = nav.index[0] if not nav.empty else None
    if nav_start is None:
        main = proxy_jp
    else:
        main = adjusted_nav(nav)
        if not proxy_jp.empty and proxy_jp.index[0] < nav_start:
            domestic = _domestic_range(proxy_jp.index[0], nav_start)
            history = proxy_jp.reindex(domestic, method="ffill")
            main = pd.concat([history.iloc[:-1] * (main.iloc[0] / history.iloc[-1]), main])
    return main, nav, proxy_jp, daily_fx, nav_start


def estimated_series(price, proxy_jp, nav_start=None):
    if nav_start is None:
        # 基準価額がない銘柄は、確定系列が代理系列そのものなので推定誤差がない。
        return price.copy()
    proxy = proxy_jp.reindex(price.index, method="ffill")
    ratio = proxy / proxy.shift()
    estimated = price.shift() * ratio.fillna(1)
    estimated.iloc[:1] = price.iloc[:1]
    before_nav = price.index < nav_start
    estimated.loc[before_nav] = price.loc[before_nav]
    return estimated


def latest_estimate(price, proxy_jp):
    if price.empty or proxy_jp.empty or proxy_jp.index[-1] <= price.index[-1]:
        return None
    reference = proxy_jp.asof(price.index[-1])
    if pd.isna(reference):
        return None
    return proxy_jp.index[-1], price.iloc[-1] * (proxy_jp.iloc[-1] / reference)


def nowcast(nav, proxy_jp, index):
    if nav.empty:
        return None
    point = latest_estimate(nav["nav"], proxy_jp)
    if point is None:
        return None
    day = nav.index[-1]
    _, value = point
    ratio = value / nav["nav"].iloc[-1]
    proxy_returns = proxy_jp.reindex(nav.index, method="ffill").pct_change()
    errors = (adjusted_nav(nav).pct_change() - proxy_returns).loc[day - pd.DateOffset(years=1):day]
    error = errors.std() * 100
    return {
        "us_date": index.index[-1].date().isoformat(),
        "value": value,
        "change_pct": (ratio - 1) * 100,
        "error_pct": error if np.isfinite(error) else None,
    }
